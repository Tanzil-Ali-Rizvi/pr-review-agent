"""Web demo: review a sample pull request, or your own before/after code, and see the comments inline."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reviewer.bench import load_cases  # noqa: E402
from reviewer.diff import make_diff, parse  # noqa: E402
from reviewer.llm import from_env  # noqa: E402
from reviewer.review import review_diff  # noqa: E402

st.set_page_config(page_title="AI PR review for Python", page_icon="🔎", layout="wide")

try:
    if "GROQ_API_KEY" in st.secrets and not os.getenv("GROQ_API_KEY"):
        os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
except Exception:  # noqa: BLE001  (no secrets file: run linters only)
    pass

SHOWCASE = [
    "sec-sql-search", "cor-inverted-discount", "perf-n-plus-one", "rel-missing-await",
    "sec-admin-bypass-injection", "cor-top-n-order", "clean-parameterised-sql", "clean-add-tests",
]  # fmt: skip
ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}
CSS = """
<style>
.d{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;border:1px solid #d0d7de;border-radius:8px;overflow:hidden;margin-bottom:14px}
.d .f{background:#f6f8fa;padding:8px 12px;font-weight:600;border-bottom:1px solid #d0d7de;color:#1f2328}
.d .l{white-space:pre;padding:0 12px;line-height:20px;color:#1f2328}
.d .a{background:#e6ffec}.d .r{background:#ffebe9}.d .h{background:#ddf4ff;color:#57606a}
.d .n{display:inline-block;width:38px;color:#8c959f;user-select:none}
.c{margin:6px 12px 10px 50px;border:1px solid #d0d7de;border-left:4px solid #cf222e;border-radius:6px;padding:10px 12px;background:#fff;font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:14px;white-space:normal;color:#1f2328}
.c.medium{border-left-color:#bc4c00}.c.low{border-left-color:#9a6700}
.c .t{font-weight:600;margin-bottom:4px}.c .s{color:#57606a;font-size:12px;margin-top:6px}
.c pre{background:#f6f8fa;padding:8px;border-radius:6px;white-space:pre-wrap;margin:6px 0 0}
@media (prefers-color-scheme: dark){.d{border-color:#30363d}.d .f{background:#161b22;color:#e6edf3;border-color:#30363d}
.d .l{color:#e6edf3}.d .a{background:#12261e}.d .r{background:#25171c}.d .h{background:#121d2f;color:#8b949e}
.c{background:#0d1117;border-color:#30363d;color:#e6edf3}.c .s{color:#8b949e}.c pre{background:#161b22}}
</style>
"""


@st.cache_resource
def cases():
    return {c.id: c for c in load_cases()}


@st.cache_resource
def shared_llm():
    return from_env()


@st.cache_resource
def loop():
    lp = asyncio.new_event_loop()
    import threading

    threading.Thread(target=lp.run_forever, daemon=True).start()
    return lp


@st.cache_data(show_spinner=False, max_entries=200, ttl=24 * 3600)
def run_review(diff_text: str, files_json: str, title: str, body: str, use_llm: bool, verify: bool) -> dict:
    llm = shared_llm() if use_llm else None
    fut = asyncio.run_coroutine_threadsafe(
        review_diff(diff_text, json.loads(files_json), llm, title=title, body=body, verify=verify), loop()
    )
    return fut.result(timeout=240).to_dict()


def comment_html(f: dict) -> str:
    sug = f"<pre>{html.escape(f['suggestion'])}</pre>" if f.get("suggestion") else ""
    notes = []
    if f.get("evidence"):
        notes.append("evidence: " + ", ".join(f["evidence"]))
    notes.append(
        "rule-based"
        if f["source"] == "linter"
        else ("confirmed by second pass" if f.get("verdict") == "confirmed" else "LLM")
    )
    return (f"<div class='c {f['severity']}'><div class='t'>{ICON[f['severity']]} {f['severity'].title()} · "
            f"{f['category'].title()} · {html.escape(f['title'])}</div>{html.escape(f['explanation'])}{sug}"
            f"<div class='s'>{html.escape(' · '.join(notes))}</div></div>")  # fmt: skip


def diff_html(diff_text: str, findings: list[dict]) -> str:
    by_line: dict[tuple[str, int], list[dict]] = {}
    for f in findings:
        by_line.setdefault((f["path"], f["line"]), []).append(f)
    out, path, new_no = [CSS], None, 0
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git") or raw.startswith("--- "):
            continue
        if raw.startswith("+++ "):
            if path is not None:
                out.append("</div>")
            path = raw[6:] if raw.startswith("+++ b/") else raw[4:]
            out.append(f"<div class='d'><div class='f'>{html.escape(path)}</div>")
            continue
        if raw.startswith("@@"):
            new_no = int(raw.split("+")[1].split(",")[0].split(" ")[0])
            out.append(f"<div class='l h'>{html.escape(raw)}</div>")
            continue
        if raw.startswith("-"):
            out.append(f"<div class='l r'><span class='n'></span>{html.escape(raw)}</div>")
            continue
        cls = "a" if raw.startswith("+") else ""
        out.append(f"<div class='l {cls}'><span class='n'>{new_no}</span>{html.escape(raw)}</div>")
        for f in by_line.get((path or "", new_no), []):
            out.append(comment_html(f))
        new_no += 1
    if path is not None:
        out.append("</div>")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------------------- UI
st.title("🔎 AI pull-request review for Python")
st.write(
    "Linters (ruff + bandit) gather evidence, an LLM decides what is actually wrong, and a second pass must confirm "
    "each finding before it is posted. It only comments on lines the PR changed, never approves or blocks a PR, and "
    "treats the code as untrusted. [Code, GitHub Action and benchmark](https://github.com/Tanzil-Ali-Rizvi/pr-review-agent)"
)
have_llm = shared_llm() is not None
left, right = st.columns([1, 2], gap="large")
with left:
    mode = st.radio("What to review", ["A sample pull request", "My own code"], horizontal=True)
    if mode == "A sample pull request":
        cs = cases()
        labels = {cid: f"{cs[cid].title}" + (" (clean)" if not cs[cid].bugs else "") for cid in SHOWCASE if cid in cs}
        cid = st.selectbox("Sample PR", list(labels), format_func=labels.get)
        c = cs[cid]
        before, after, title, body = c.before, c.after, c.title, c.body
        st.caption(f"PR description: {c.body}")
        st.caption("Samples come from the planted-bug benchmark; the answer key is not shown to the reviewer.")
    else:
        path = st.text_input("File path", "app/service.py")
        before_text = st.text_area(
            "Original code", height=180, value="def total(items):\n    return sum(i['price'] for i in items)\n"
        )
        after_text = st.text_area("Changed code", height=240, value=(
            "import requests\n\n\ndef total(items, coupon=None):\n    t = sum(i['price'] * i['qty'] for i in items)\n"
            "    if coupon:\n        r = requests.get(f'https://coupons.example.com/{coupon}')\n"
            "        t -= r.json()['amount']\n    return t\n"))  # fmt: skip
        before, after, title, body = {path: before_text}, {path: after_text}, "My change", ""
    use_llm = st.toggle("Use the LLM", value=have_llm, disabled=not have_llm,
                        help="Off: linters only. The LLM runs on Groq's free tier through my llm-gateway.")  # fmt: skip
    verify = st.toggle("Second-pass verification", value=True, disabled=not use_llm)
    if not have_llm:
        st.info("No LLM key on this deployment, so the review runs ruff + bandit only.")
    go = st.button("Review", type="primary", use_container_width=True)

diff_text = make_diff(before, after)
with right:
    if not parse(diff_text):
        st.warning("The two versions are identical: nothing to review.")
    elif go or mode == "A sample pull request":
        files_json = json.dumps(after, sort_keys=True)
        with st.spinner("Reviewing… (the free LLM tier can take 10-30 s)"):
            try:
                r = run_review(diff_text, files_json, title, body, use_llm and have_llm, verify)
            except Exception as e:  # noqa: BLE001
                st.error(f"The review failed: {e}")
                st.stop()
        n = len(r["findings"])
        a, b, c3 = st.columns(3)
        a.metric("Comments posted", n)
        b.metric("Filtered out", len(r["dropped"]))
        c3.metric("LLM cost", f"${r['cost_usd']:.4f}")
        if r["errors"]:
            st.warning(
                "Part of the review could not run ("
                + "; ".join(r["errors"])[:200]
                + "). Rule-based findings are shown."
            )
        if n == 0:
            st.success("No issues worth flagging in the changed lines.")
        st.html(diff_html(diff_text, r["findings"]))
        if r["dropped"]:
            with st.expander(f"Filtered out before posting ({len(r['dropped'])})"):
                for d in r["dropped"]:
                    f = d["finding"]
                    st.markdown(f"- line {f['line']} · **{f['title']}** — {d['reason']}")
        key = hashlib.sha1(diff_text.encode()).hexdigest()[:8]
        st.caption(f"Review id {key} · results are cached for a day so repeated clicks don't spend the free quota.")
    else:
        st.html(diff_html(diff_text, []))
        st.caption("Press **Review** to run it.")

bench = ROOT / "results" / "bench_test.md"
with st.expander("Benchmark: how often does it catch planted bugs?"):
    if bench.exists():
        st.markdown(bench.read_text().split("\n| Case |")[0])
    else:
        st.write("The benchmark has not been run yet.")
