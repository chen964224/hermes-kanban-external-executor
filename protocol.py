"""Terminal-state protocol for tool-less kanban card workers.

A card worker that has no Hermes kanban tools cannot call ``kanban_complete`` /
``kanban_block`` / ``kanban_request_review``. This module defines and parses the
file-based substitute: a result document whose *first line* carries a terminal
token, plus the two rules that keep a supervisor from misreading it.

Nothing here is Hermes-specific — it is the contract described in the README.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The only tokens that count as a terminal state. Anything else is not a verdict.
VERDICT_TOKENS = ("DONE", "FAIL", "BLOCKED", "PARTIAL")

#: Chinese spellings seen in practice, mapped onto the canonical tokens.
_ZH = {"完成": "DONE", "通过": "DONE", "失败": "FAIL", "不通过": "FAIL",
       "阻塞": "BLOCKED", "部分完成": "PARTIAL", "未能验证": "FAIL"}

_VERDICT_EN = re.compile(r"\bVERDICT\s*[:=]\s*(%s)\b" % "|".join(VERDICT_TOKENS), re.I)
_VERDICT_ZH = re.compile(r"\b(?:verdict|判定|结论)\s*[:：=]?\s*(%s)" % "|".join(_ZH))

#: A document this small carrying one of these markers is a *skeleton*, not a result.
SKELETON_MARKERS = ("骨架", "进行中", "随进度更新", "待补", "尚未完成",
                    "in progress", "skeleton", "TODO", "PLACEHOLDER")
SKELETON_MAX_BYTES = 4096

#: Lines a CLI prints that are chrome, not the worker speaking.
_DROP_PREFIX = ("session_id:", "Query:", "Initializing agent")
_CHROME_RE = re.compile(r"[─━═╭╮╰╯│┃┌┐└┘]+|☤\s*Hermes")


def scan_verdict(text: str, prefer_last: bool = True) -> str:
    """Return the terminal token in *text*, or ``"none"``.

    ``"none"`` means *no terminal state was declared* — it is never a conclusion.
    """
    if not text:
        return "none"
    m = _VERDICT_EN.findall(text)
    if m:
        return m[-1 if prefer_last else 0].upper()
    m2 = _VERDICT_ZH.findall(text)
    if m2:
        v = m2[-1 if prefer_last else 0]
        return _ZH.get(v, "none")
    return "none"


def is_skeleton_doc(path) -> bool:
    """True when *path* is a placeholder skeleton rather than a finished result.

    Briefs tell workers to land a skeleton early and fill it in, so the first line
    is often a *placeholder* terminal token. Reading it as terminal interrupts a
    worker that is still running — this is the guard against that.
    """
    p = Path(path)
    try:
        if p.stat().st_size > SKELETON_MAX_BYTES:
            return False
        head = p.read_text(encoding="utf-8", errors="ignore")[:800]
    except OSError:
        return False
    return any(m in head for m in SKELETON_MARKERS)


def worker_last_words(capture: str, limit: int = 400) -> str:
    """The worker's own last words, with CLI chrome stripped.

    Quoting this in a block reason is the difference between "we don't know why"
    and "here is why".
    """
    if not capture:
        return ""
    out = []
    for ln in capture.splitlines():
        s = ln.strip()
        # Drop the whole line: stripping only the prefix would leave the value behind.
        if not s or s.startswith(_DROP_PREFIX) or "☤" in s:
            continue
        s = _CHROME_RE.sub("", s).strip()
        if s:
            out.append(s)
    return "\n".join(out)[-limit:]


def verdict_candidates(root):
    """Files worth scanning for a terminal token, conclusion documents first.

    Evidence dirs (repro/, logs/) come last: a *test-case label* inside them
    (e.g. ``verdict=PARTIAL_MISS``) is not a verdict, and scanning them early has
    mis-closed cards whose real conclusion lived in the report.
    """
    root = Path(root)
    docs, others, evidence = [], [], []
    for f in sorted(root.rglob("*.md")) + sorted(root.rglob("*.txt")):
        if "/in/" in str(f):
            continue
        rel = "/" + str(f)
        if any(m in rel for m in ("/repro/", "/logs/")):
            evidence.append(f)
        elif f.suffix == ".md":
            docs.append(f)
        else:
            others.append(f)
    return docs + others + evidence


def read_verdict(root, *, skip_skeletons: bool = True) -> tuple[str, str]:
    """Best-effort terminal token from a workspace's result documents.

    Returns ``(verdict, source)``; ``verdict == "none"`` means *not finished*,
    which the caller must treat as "no conclusion yet" — never as a failure.
    """
    for f in verdict_candidates(root):
        if f.name in ("TASK.md", "cap.txt"):
            continue
        if skip_skeletons and f.suffix == ".md" and is_skeleton_doc(f):
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        # The token is specified to be on the first line; scan the head, then fall
        # back to the whole document for workers that bury it.
        v = scan_verdict("\n".join(lines[:20]), prefer_last=False)
        if v == "none":
            v = scan_verdict("\n".join(lines), prefer_last=False)
        if v != "none":
            return v, f.name
    return "none", ""
