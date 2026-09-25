"""Tests for the terminal-state protocol.

These pin the three rules that were learned the expensive way; each one has a
before/after that used to fail.
"""

from pathlib import Path

from protocol import (is_skeleton_doc, read_verdict, scan_verdict,
                      verdict_candidates, worker_last_words)


# ---- §1 terminal tokens -------------------------------------------------------

def test_scan_verdict_reads_the_four_tokens():
    assert scan_verdict("VERDICT: DONE") == "DONE"
    assert scan_verdict("VERDICT: FAIL") == "FAIL"
    assert scan_verdict("VERDICT: BLOCKED") == "BLOCKED"
    assert scan_verdict("VERDICT: PARTIAL") == "PARTIAL"


def test_scan_verdict_prefers_the_last_token():
    text = "we said VERDICT: PARTIAL earlier\n...work...\nVERDICT: DONE"
    assert scan_verdict(text, prefer_last=True) == "DONE"
    assert scan_verdict(text, prefer_last=False) == "PARTIAL"


def test_non_token_text_is_not_a_verdict():
    # 'verdict=PARTIAL_MISS' is a test-case label, not a verdict.
    assert scan_verdict("verdict=PARTIAL_MISS") == "none"
    assert scan_verdict("no conclusion here") == "none"
    assert scan_verdict("") == "none"


# ---- §2 skeletons are never terminal -----------------------------------------

def test_skeleton_is_recognised(tmp_path: Path):
    p = tmp_path / "RESULT.md"
    p.write_text("VERDICT: PARTIAL\n<!-- skeleton, updated as we go -->\n"
                 "# task — skeleton\n- status: in progress\n", encoding="utf-8")
    assert is_skeleton_doc(p) is True


def test_finished_report_is_not_a_skeleton(tmp_path: Path):
    p = tmp_path / "RESULT.md"
    p.write_text("VERDICT: DONE\n\n" + ("full findings line\n" * 300), encoding="utf-8")
    assert is_skeleton_doc(p) is False


def test_large_file_with_skeleton_word_is_not_a_skeleton(tmp_path: Path):
    # Size wins: a real report that happens to contain the word must still be read.
    p = tmp_path / "RANK.md"
    p.write_text("VERDICT: DONE\n" + ("TODO / 骨架 mentioned in passing\n" * 300),
                 encoding="utf-8")
    assert is_skeleton_doc(p) is False


def test_read_verdict_skips_a_skeleton_and_finds_the_real_report(tmp_path: Path):
    (tmp_path / "RESULT.md").write_text(
        "VERDICT: PARTIAL\n<!-- skeleton -->\n- status: 进行中\n", encoding="utf-8")
    (tmp_path / "REPORT.md").write_text("VERDICT: DONE\nreal findings\n", encoding="utf-8")
    v, src = read_verdict(tmp_path)
    assert v == "DONE", "the skeleton's placeholder must not win"
    assert src == "REPORT.md"


def test_read_verdict_reports_none_when_nothing_is_finished(tmp_path: Path):
    (tmp_path / "RESULT.md").write_text(
        "VERDICT: PARTIAL\n<!-- skeleton -->\n- 状态：未完成\n", encoding="utf-8")
    assert read_verdict(tmp_path)[0] == "none"


# ---- §3 evidence dirs are scanned last ---------------------------------------

def test_verdict_candidates_put_evidence_last(tmp_path: Path):
    (tmp_path / "RESULT.md").write_text("VERDICT: DONE\n", encoding="utf-8")
    (tmp_path / "repro").mkdir()
    (tmp_path / "repro" / "case.txt").write_text("verdict=PARTIAL_MISS\n", encoding="utf-8")
    order = [f.name for f in verdict_candidates(tmp_path)]
    assert order.index("RESULT.md") < order.index("case.txt")


# ---- §3 quoting the worker's own last words ----------------------------------

def test_worker_last_words_drops_chrome_entirely():
    cap = ("Initializing agent\n"
           "☤ Hermes ────────────────────────────\n"
           "session_id: abc123\n"
           "Query: do the thing\n"
           "line-1: running the market simulation\n"
           "VERDICT: PARTIAL not finished yet\n")
    out = worker_last_words(cap)
    assert "abc123" not in out, "stripping only the prefix would leave the value"
    assert "Hermes" not in out and "────" not in out
    assert out.endswith("VERDICT: PARTIAL not finished yet")


def test_worker_last_words_respects_the_limit():
    assert len(worker_last_words("x" * 5000, limit=400)) <= 400
