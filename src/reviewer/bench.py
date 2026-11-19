"""Planted-bug benchmark: does the reviewer catch known bugs without crying wolf on clean pull requests?

Each case is a small realistic PR (before/after files). Lines ending in "#@bug" are planted bugs; "#@ok" marks lines
where a comment is acceptable but not required. Markers are stripped before anything is reviewed.

A comment is a hit if it is in the right file, within 2 lines of a planted bug, and names the problem (one of the bug's
keywords appears in its title, explanation or suggestion), so a different complaint about the same line does not
count. Three systems are scored from one run:
  linters    ruff + bandit only (no LLM)
  llm        LLM reviewer with linter evidence, before the verification pass
  llm+verify the full pipeline (what the GitHub Action posts)

Cases are split into `dev` (used while building the prompts) and `test` (held out: run once with frozen prompts).
The run saves after every case and resumes, because the free Groq tier has a daily token limit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .diff import make_diff
from .llm import from_env
from .review import Finding, review_diff

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "cases"
OUT = ROOT / "results"
MARK = re.compile(r"\s*#@(bug|ok)\s*$")
TOLERANCE = 2
SYSTEMS = ("linters", "llm", "llm+verify")


@dataclass
class Case:
    id: str
    split: str
    title: str
    body: str
    before: dict[str, str]
    after: dict[str, str]
    bugs: list[dict]
    bug_lines: dict[str, set[int]] = field(default_factory=dict)
    ok_lines: dict[str, set[int]] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return "bug" if self.bugs else "clean"

    @property
    def category(self) -> str:
        return self.bugs[0]["category"] if self.bugs else "clean"

    @property
    def severity(self) -> str:
        return self.bugs[0].get("severity", "medium") if self.bugs else ""


def _strip(text: str) -> tuple[str, set[int], set[int]]:
    bug, ok, out = set(), set(), []
    for n, line in enumerate(text.splitlines(), start=1):
        m = MARK.search(line)
        if m:
            (bug if m.group(1) == "bug" else ok).add(n)
            line = line[: m.start()]
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), bug, ok


def load_cases(folder: Path = CASES) -> list[Case]:
    cases = []
    for path in sorted(folder.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text()):
            after, bug_lines, ok_lines = {}, {}, {}
            for p, text in (raw.get("after") or {}).items():
                clean, bug, ok = _strip(text or "")
                after[p] = clean
                if bug:
                    bug_lines[p] = bug
                if ok:
                    ok_lines[p] = ok
            c = Case(raw["id"], raw.get("split", "test"), raw.get("title", ""), raw.get("body", ""),
                     {p: t or "" for p, t in (raw.get("before") or {}).items()}, after, raw.get("bugs") or [],
                     bug_lines, ok_lines)  # fmt: skip
            if c.bugs and not c.bug_lines:
                raise ValueError(f"{c.id}: has bugs but no #@bug lines")
            cases.append(c)
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return cases


def _near(lines: set[int], line: int) -> bool:
    return any(abs(line - n) <= TOLERANCE for n in lines)


def _names_bug(case: Case, f: dict) -> bool:
    words = [w.lower() for b in case.bugs for w in b.get("keywords", [])]
    if not words:
        return True
    text = f"{f.get('title', '')} {f.get('explanation', '')} {f.get('suggestion', '')}".lower()
    return any(w in text for w in words)


def score_findings(case: Case, findings: list[dict]) -> dict[str, Any]:
    hits = [f for f in findings if _near(case.bug_lines.get(f["path"], set()), f["line"]) and _names_bug(case, f)]
    ok = [f for f in findings if f not in hits and _near(case.ok_lines.get(f["path"], set()), f["line"])]
    false = [f for f in findings if f not in hits and f not in ok]
    return {"caught": bool(hits), "comments": len(findings), "hits": len(hits), "acceptable": len(ok),
            "false": len(false), "false_titles": [f"{f['path']}:{f['line']} {f['title']}" for f in false]}  # fmt: skip


def _slim(fs: list[Finding]) -> list[dict]:
    return [{"path": f.path, "line": f.line, "severity": f.severity, "category": f.category, "title": f.title,
             "explanation": f.explanation[:400], "suggestion": f.suggestion[:200], "source": f.source,
             "verdict": f.verdict, "verdict_reason": f.verdict_reason[:200]} for f in fs]  # fmt: skip


async def run_case(case: Case, llm) -> dict[str, Any]:
    diff = make_diff(case.before, case.after)
    lint = await review_diff(diff, case.after, None, title=case.title, body=case.body)
    t0 = time.perf_counter()
    full = await review_diff(diff, case.after, llm, title=case.title, body=case.body, verify=True)
    row = {
        "id": case.id, "split": case.split, "kind": case.kind, "category": case.category, "severity": case.severity,
        "systems": {"linters": _slim(lint.findings), "llm": _slim(full.candidates), "llm+verify": _slim(full.findings)},
        "llm_calls": full.llm_calls, "tokens": full.tokens, "cost_usd": full.cost_usd,
        "llm_ms": round(full.llm_ms, 1), "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        "errors": full.errors,
        "dropped": [{"line": f.line, "title": f.title, "reason": why} for f, why in full.dropped],
    }  # fmt: skip
    return row


def summarise(rows: list[dict], cases: dict[str, Case]) -> dict[str, Any]:
    out: dict[str, Any] = {"cases": len(rows), "bug_cases": sum(r["kind"] == "bug" for r in rows),
                           "clean_cases": sum(r["kind"] == "clean" for r in rows), "systems": {}}  # fmt: skip
    for sysname in SYSTEMS:
        scored = [(r, score_findings(cases[r["id"]], r["systems"][sysname])) for r in rows]
        bug = [(r, s) for r, s in scored if r["kind"] == "bug"]
        clean = [(r, s) for r, s in scored if r["kind"] == "clean"]
        comments = sum(s["comments"] for _, s in scored)
        good = sum(s["hits"] + s["acceptable"] for _, s in scored)
        by_cat = {}
        for cat in ("security", "correctness", "performance", "reliability"):
            sub = [s for r, s in bug if r["category"] == cat]
            if sub:
                by_cat[cat] = {"n": len(sub), "caught": sum(s["caught"] for s in sub)}
        high = [s for r, s in bug if r["severity"] == "high"]
        out["systems"][sysname] = {
            "recall": round(sum(s["caught"] for _, s in bug) / len(bug), 3) if bug else None,
            "caught": sum(s["caught"] for _, s in bug),
            "high_recall": round(sum(s["caught"] for s in high) / len(high), 3) if high else None,
            "precision": round(good / comments, 3) if comments else None,
            "comments": comments,
            "false_alarms": sum(s["false"] for _, s in scored),
            "clean_prs_flagged": sum(s["comments"] > 0 for _, s in clean),
            "by_category": by_cat,
        }
    llm_rows = [r for r in rows if r["llm_calls"]]
    if llm_rows:
        per_pr = [r["llm_ms"] for r in llm_rows]
        out["cost_usd"] = round(sum(r["cost_usd"] for r in llm_rows), 4)
        out["cost_per_pr"] = round(out["cost_usd"] / len(llm_rows), 5)
        out["tokens"] = sum(r["tokens"] for r in llm_rows)
        out["llm_ms_p50"] = round(statistics.median(per_pr))
    return out


def to_md(summary: dict, rows: list[dict], cases: dict[str, Case], split: str, pending: int) -> str:
    s = summary["systems"]
    lines = [
        "# Planted-bug benchmark",
        "",
        f"Split: **{split}** · {summary['cases']} pull requests ({summary['bug_cases']} with a planted bug, "
        f"{summary['clean_cases']} clean). A comment is a hit if it is within {TOLERANCE} lines of a planted bug "
        "and names the problem (keyword match), so a different complaint about the same line does not count.",
        "",
        "| | Linters only (ruff + bandit) | LLM reviewer | LLM + verifier (posted) |",
        "|---|---|---|---|",
    ]

    def row(label: str, fn) -> str:
        return f"| {label} | " + " | ".join(fn(s[k]) for k in SYSTEMS) + " |"

    pct = lambda v: "n/a" if v is None else f"{v:.0%}"  # noqa: E731
    lines += [
        row("Bugs caught", lambda x: f"**{x['caught']} / {summary['bug_cases']}** ({pct(x['recall'])})"),
        row("High-severity bugs caught", lambda x: pct(x["high_recall"])),
        row("Comments that point at a real bug", lambda x: f"{pct(x['precision'])} of {x['comments']}"),
        row("False alarms (comments)", lambda x: str(x["false_alarms"])),
        row("Clean PRs with any comment", lambda x: f"{x['clean_prs_flagged']} / {summary['clean_cases']}"),
    ]
    for cat in ("security", "correctness", "performance", "reliability"):
        if cat in s["llm+verify"]["by_category"]:
            lines.append(row(f"{cat.title()} bugs caught",
                             lambda x, c=cat: f"{x['by_category'][c]['caught']} / {x['by_category'][c]['n']}"))  # fmt: skip
    if "cost_usd" in summary:
        lines += ["", f"LLM cost: ${summary['cost_usd']:.4f} in total, ${summary['cost_per_pr']:.5f} per PR · "
                      f"{summary['tokens']:,} tokens · LLM time per PR p50 {summary['llm_ms_p50'] / 1000:.1f} s "
                      "(includes waits for free-tier rate limits)."]  # fmt: skip
    lines += [
        "",
        "| Case | Planted bug | Linters | LLM | LLM + verifier | False alarms (posted) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        c = cases[r["id"]]
        sc = {k: score_findings(c, r["systems"][k]) for k in SYSTEMS}
        what = c.bugs[0]["what"] if c.bugs else "clean PR"

        def mark(x: dict, has_bug: bool = bool(c.bugs)) -> str:
            if has_bug:
                return "✅" if x["caught"] else "❌"
            return "✅" if x["comments"] == 0 else f"⚠️ {x['comments']}"

        fa = "; ".join(sc["llm+verify"]["false_titles"])[:160] or ""
        lines.append(
            f"| `{r['id']}` | {what} | {mark(sc['linters'])} | {mark(sc['llm'])} | {mark(sc['llm+verify'])} | {fa} |"
        )
    if pending:
        lines += ["", f"_{pending} cases still to run._"]
    return "\n".join(lines) + "\n"


def save(rows: list[dict], cases: dict[str, Case], split: str, pending: int, meta: dict) -> dict:
    OUT.mkdir(exist_ok=True)
    summary = summarise(rows, cases)
    summary.update(meta)
    (OUT / f"bench_{split}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False)
    )
    (OUT / f"bench_{split}.md").write_text(to_md(summary, rows, cases, split, pending))
    return summary


async def main_async(split: str, fresh: bool, limit: int | None, pause: float) -> int:
    all_cases = load_cases()
    cases = {c.id: c for c in all_cases}
    todo = [c for c in all_cases if split == "all" or c.split == split]
    path = OUT / f"bench_{split}.json"
    rows = [] if fresh or not path.exists() else json.loads(path.read_text())["rows"]
    done = {r["id"] for r in rows}
    llm = from_env("eval")
    if llm is None:
        print("Set GROQ_API_KEY (or LLM_BASE_URL) to run the LLM systems.", file=sys.stderr)
        return 2
    meta = {"model": "openai/gpt-oss-120b (Groq) via llm-gateway", "split": split}
    strikes = 0
    for c in todo:
        if c.id in done:
            continue
        if limit is not None and limit <= 0:
            break
        row = await run_case(c, llm)
        if row["errors"]:
            strikes += 1
            print(f"{c.id}: infrastructure error, will retry next run: {row['errors'][0][:160]}")
            if strikes >= 2:
                print("Two failures in a row (probably the daily token limit). Stopping; rerun to resume.")
                break
            continue
        strikes = 0
        rows.append(row)
        done.add(c.id)
        if limit is not None:
            limit -= 1
        sc = score_findings(c, row["systems"]["llm+verify"])
        print(f"{c.id:32} {'caught' if sc['caught'] else ('clean' if not c.bugs else 'MISSED'):7} "
              f"comments={sc['comments']} false={sc['false']} ${row['cost_usd']:.4f}")  # fmt: skip
        save(rows, cases, split, len([x for x in todo if x.id not in done]), meta)
        await asyncio.sleep(pause)
    pending = len([x for x in todo if x.id not in done])
    summary = save(rows, cases, split, pending, meta)
    print(json.dumps(summary["systems"]["llm+verify"], indent=1))
    print("complete" if not pending else f"{pending} pending")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"])
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--pause", type=float, default=4)
    a = ap.parse_args()
    sys.exit(asyncio.run(main_async(a.split, a.fresh, a.limit, a.pause)))


if __name__ == "__main__":
    main()
