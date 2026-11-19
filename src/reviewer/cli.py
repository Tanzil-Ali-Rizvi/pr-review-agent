"""Review local changes before pushing: `pr-review` (against origin/main) or `pr-review --base develop`."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from .llm import from_env
from .review import review_diff

ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI review of the Python changes on this branch.")
    ap.add_argument("--base", default="origin/main", help="branch or commit to compare against")
    ap.add_argument("--no-verify", action="store_true", help="skip the second (verification) pass")
    ap.add_argument("--json", action="store_true", help="print the full review as JSON")
    args = ap.parse_args(argv)
    try:
        diff = subprocess.run(["git", "diff", f"{args.base}...HEAD"], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        print(e.stderr.strip(), file=sys.stderr)
        return 2
    paths = [line[6:] for line in diff.splitlines() if line.startswith("+++ b/")]
    files = {p: Path(p).read_text() for p in paths if p.endswith(".py") and Path(p).exists()}
    llm = from_env()
    if llm is None:
        print("No GROQ_API_KEY or LLM_BASE_URL set: running linters only.", file=sys.stderr)
    r = asyncio.run(review_diff(diff, files, llm, verify=not args.no_verify))
    if args.json:
        print(json.dumps(r.to_dict(), indent=2, ensure_ascii=False))
        return 0
    for f in r.findings:
        print(f"{ICON[f.severity]} {f.path}:{f.line} [{f.category}] {f.title}\n   {f.explanation}")
        if f.suggestion:
            print(f"   fix: {f.suggestion.splitlines()[0]}")
    print(f"\n{len(r.findings)} finding(s) in {len(r.files_reviewed)} file(s); LLM cost ${r.cost_usd:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
