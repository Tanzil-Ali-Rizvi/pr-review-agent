"""Unified diffs: which lines a review may comment on, and how to show a change to the model.

GitHub only accepts inline comments on lines that are part of the diff. Comments here are limited further, to lines
the pull request added or changed, so a review never blames the author for code they didn't touch.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FileDiff:
    path: str
    status: str = "modified"  # added | modified | removed | renamed
    added: dict[int, str] = field(default_factory=dict)  # new-file line number -> text, for + lines
    hunks: list[tuple[int, int]] = field(default_factory=list)  # (first, last) new-file lines of each hunk

    @property
    def is_python(self) -> bool:
        return self.path.endswith(".py")

    def nearest_added(self, line: int, within: int = 3) -> int | None:
        """The changed line closest to `line`, if one is within `within` lines (models are often off by one)."""
        if line in self.added:
            return line
        near = [n for n in self.added if abs(n - line) <= within]
        return min(near, key=lambda n: (abs(n - line), n)) if near else None


def parse(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            cur = None
            continue
        if raw.startswith("--- "):
            continue
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                cur = None  # deleted file: nothing to comment on
                continue
            cur = FileDiff(path=target[2:] if target.startswith("b/") else target)
            files.append(cur)
            continue
        if cur is None:
            continue
        m = HUNK.match(raw)
        if m:
            new_line = int(m.group(3))
            length = int(m.group(4)) if m.group(4) is not None else 1
            cur.hunks.append((new_line, new_line + max(length, 1) - 1))
            continue
        if raw.startswith("+"):
            cur.added[new_line] = raw[1:]
            new_line += 1
        elif raw.startswith("-"):
            pass
        elif raw.startswith("\\"):
            pass  # "\ No newline at end of file"
        else:
            new_line += 1
    return files


def from_patches(patches: dict[str, str]) -> list[FileDiff]:
    """GitHub's PR files API returns one hunk-only patch per file; give each the headers `parse` expects."""
    text = "".join(f"--- a/{p}\n+++ b/{p}\n{patch}\n" for p, patch in patches.items() if patch)
    return parse(text)


def make_diff(before: dict[str, str], after: dict[str, str], context: int = 3) -> str:
    """A git-style unified diff between two {path: content} snapshots (used by the benchmark and the demo)."""
    out: list[str] = []
    for path in sorted(set(before) | set(after)):
        a, b = before.get(path), after.get(path)
        if a == b:
            continue
        a_lines = [] if a is None else a.splitlines(keepends=True)
        b_lines = [] if b is None else b.splitlines(keepends=True)
        out.append(f"diff --git a/{path} b/{path}\n")
        for line in difflib.unified_diff(
            a_lines,
            b_lines,
            fromfile="/dev/null" if a is None else f"a/{path}",
            tofile="/dev/null" if b is None else f"b/{path}",
            n=context,
        ):
            out.append(line if line.endswith("\n") else line + "\n")
    return "".join(out)


def numbered_view(fd: FileDiff, content: str, context: int = 6) -> str:
    """The new version of the file around each hunk, with line numbers; changed lines are marked with '+'.

    The model comments by line number, so it must see the same numbers GitHub uses.
    """
    lines = content.splitlines()
    keep: set[int] = set()
    for first, last in fd.hunks or [(1, len(lines))]:
        keep.update(range(max(1, first - context), min(len(lines), last + context) + 1))
    out, prev = [], 0
    for n in sorted(keep):
        if prev and n != prev + 1:
            out.append("     ...")
        mark = "+" if n in fd.added else " "
        out.append(f"{n:>4} {mark} {lines[n - 1]}")
        prev = n
    return "\n".join(out)
