"""Markdown for GitHub: one inline comment per finding and a summary for the review body."""

from __future__ import annotations

from .review import Finding, Review

MARK = "<!-- pr-review-agent -->"
ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def comment(f: Finding) -> str:
    parts = [f"**{ICON[f.severity]} {f.severity.title()} · {f.category.title()}** · {f.title}", "", f.explanation]
    if f.suggestion:
        sug = f.suggestion
        looks_like_code = "\n" in sug or any(t in sug for t in ("(", "=", "import ", "def "))
        parts += ["", "**Suggested fix:**", f"```python\n{sug}\n```" if looks_like_code else sug]
    notes = []
    if f.evidence:
        notes.append("evidence: " + ", ".join(f.evidence))
    if f.source == "linter":
        notes.append("rule-based finding")
    elif f.verdict == "confirmed":
        notes.append("confirmed by a second review pass")
    if notes:
        parts += ["", f"<sub>{' · '.join(notes)}</sub>"]
    parts.append(f"<!-- pr-review-agent:key={f.key} -->")
    return "\n".join(parts)


def summary(r: Review, sha: str = "", model: str = "") -> str:
    counts = {s: sum(1 for f in r.findings if f.severity == s) for s in ("high", "medium", "low")}
    n = len(r.findings)
    files = len(r.files_reviewed)
    head = f"{MARK}\n<!-- pr-review-agent:sha={sha} -->\n### 🤖 AI review\n\n"
    if not files:
        return head + "No Python files changed, so there was nothing for me to review."
    if n == 0:
        line = f"I reviewed the changed lines in {files} Python file{'s' * (files != 1)} and found no issues worth flagging."
    else:
        bits = ", ".join(f"{counts[s]} {s}" for s in ("high", "medium", "low") if counts[s])
        line = f"I reviewed {files} Python file{'s' * (files != 1)} and left **{n} comment{'s' * (n != 1)}** ({bits})."
    rows = "\n".join(f"| {ICON[f.severity]} | `{f.path}` | {f.line} | {f.category} | {f.title} |" for f in r.findings)
    table = f"\n\n| | File | Line | Category | Issue |\n|---|---|---|---|---|\n{rows}" if n else ""
    skipped = f"\n\nNot reviewed (not Python): {', '.join(f'`{p}`' for p in r.skipped[:10])}" if r.skipped else ""
    errs = "\n\n⚠️ Part of the review could not run: " + "; ".join(r.errors[:3]) if r.errors else ""
    foot = (
        f"\n\n<sub>pr-review-agent · ruff + bandit for evidence{', ' + model if model else ''} · "
        f"LLM cost ${r.cost_usd:.4f} · These are suggestions; a person makes the call.</sub>"
    )
    return head + line + table + skipped + errs + foot
