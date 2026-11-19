"""Static analysers as evidence: ruff (bug-finding rules only) and bandit (security), on the changed lines.

Linters are fast, free and exact, but blind to intent. The LLM sees their findings as evidence and decides what
matters; a few findings that are almost always real bugs are reported even if the model stays silent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Bug-finding rule families only: pyflakes, bugbear, syntax errors, pylint errors, async pitfalls, a few ruff rules.
# Style rules are deliberately left out; a reviewer that nags about formatting gets ignored.
RUFF_SELECT = "F,B,E9,PLE,PLW0120,PLW0602,PLW1508,PLW2901,ASYNC,RUF006,RUF012,RUF013,DTZ,S"
# Findings that are right often enough to report even if the model says nothing. SQL-from-strings (S608) is not
# here: it also fires on safely parameterised queries built from fixed clauses, so the model judges it.
ALWAYS_REPORT = {
    "F821",  # undefined name
    "F811",  # redefinition of unused name
    "B006",  # mutable default argument
    "B008",  # function call in default argument
    "B023",  # loop variable captured by closure
    "RUF006",  # dangling asyncio task
    "S602",  # subprocess with shell=True
    "S307",  # eval
    "S506",  # unsafe yaml.load
    "S301",  # pickle
    "S501",  # requests with verify=False
}


@dataclass
class Evidence:
    tool: str
    code: str
    path: str
    line: int
    message: str
    severity: str = "medium"  # high | medium | low

    def short(self) -> str:
        return f"{self.tool} {self.code} (line {self.line}): {self.message}"


def _write(tmp: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        p = tmp / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def run_ruff(files: dict[str, str]) -> list[Evidence]:
    exe = shutil.which("ruff")
    if not exe or not files:
        return []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _write(tmp, files)
        cmd = [
            exe,
            "check",
            "--no-cache",
            "--isolated",
            "--output-format",
            "json",
            "--select",
            RUFF_SELECT,
            ".",
        ]
        r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=60)
        try:
            rows = json.loads(r.stdout or "[]")
        except json.JSONDecodeError:
            return []
    out = []
    for row in rows:
        code = row.get("code") or "E999"
        sev = "high" if code in ALWAYS_REPORT or code.startswith(("F8", "E9", "PLE")) else "medium"
        rel = str(Path(row["filename"]).resolve().relative_to(tmp.resolve())) if row.get("filename") else ""
        out.append(Evidence("ruff", code, rel, row["location"]["row"], row["message"], sev))
    return out


def run_bandit(files: dict[str, str]) -> list[Evidence]:
    exe = shutil.which("bandit")
    if not exe or not files:
        return []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _write(tmp, files)
        r = subprocess.run(
            [exe, "-q", "-r", ".", "-f", "json"],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=120,
        )
        try:
            rows = json.loads(r.stdout or "{}").get("results", [])
        except json.JSONDecodeError:
            return []
    out = []
    for row in rows:
        rel = row["filename"][2:] if row["filename"].startswith("./") else row["filename"]
        sev = {"HIGH": "high", "MEDIUM": "medium"}.get(row.get("issue_severity", ""), "low")
        out.append(
            Evidence(
                "bandit",
                row["test_id"],
                rel,
                row["line_number"],
                row["issue_text"],
                sev,
            )
        )
    return out


def analyse(files: dict[str, str], changed: dict[str, set[int]]) -> list[Evidence]:
    """Run both tools on the new versions of the changed Python files; keep findings on changed lines only."""
    py = {p: c for p, c in files.items() if p.endswith(".py")}
    found = run_ruff(py) + run_bandit(py)
    seen, out = set(), []
    for e in sorted(found, key=lambda e: (e.path, e.line, e.tool)):
        if e.line not in changed.get(e.path, set()):
            continue
        key = (e.path, e.line, e.code)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out
