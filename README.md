# hermes-kanban-external-executor

Run **any external CLI coding agent** (OpenCode, Claude Code, Codex, aider, …) as a
first-class **kanban card worker** in [Hermes Agent](https://github.com/NousResearch/hermes-agent) —
without patching core.

Hermes' kanban dispatcher spawns its own in-tree worker (`hermes -p <profile> chat -q …`)
and expects the worker to close the card by calling `kanban_complete` /
`kanban_block` / `kanban_request_review`. A CLI agent that has **no Hermes tools**
cannot do that, so it cannot be a card worker — that is the gap this plugin fills.

> Status: extracted from a bridge that has been running real workloads for months
> (lane dispatch, persistent per-lane dirs, remote execution host, hundreds of
> completed cards). See [Why this exists](#why-this-exists).

---

## The contract (this is the reusable part)

Everything below is deliberately **protocol, not implementation**. Any supervisor —
ours, yours, or a future in-tree `harness` seam — can implement it.

### 1. Terminal state is declared in a file

A tool-less worker cannot call `kanban_complete`. So the card's brief tells it to write
a result document into its `out/` dir, with the terminal token **on the first line**:

```
VERDICT: DONE | FAIL | BLOCKED | PARTIAL
```

- The token vocabulary is fixed and small; anything else is **not** a verdict.
- `DONE` is the only token that closes the card as successful. Everything else is
  a real conclusion and must be surfaced to a human — **not** silently retried.
- A missing token is **not** a conclusion. See §3.

### 2. Never read a verdict out of a *skeleton*

Briefs commonly say *"land a skeleton early, then fill it in"* — and engineers write the
placeholder token while filling it. A supervisor that scans for a token then reads that
placeholder as terminal and **interrupts a worker that is still running**.

Rule: a small file carrying skeleton markers is **not a terminal state**.

```python
_SKELETON_MARKERS = ("骨架", "进行中", "in progress", "TODO", "PLACEHOLDER", "skeleton")
_SKELETON_MAX_BYTES = 4096

def is_skeleton_doc(path) -> bool:
    p = Path(path)
    if p.stat().st_size > _SKELETON_MAX_BYTES:
        return False
    head = p.read_text(encoding="utf-8", errors="ignore")[:800]
    return any(m in head for m in _SKELETON_MARKERS)
```

Verified both ways: a 214-byte skeleton with `VERDICT: PARTIAL` on line 1 → `True`;
the finished 6 KB report → `False`.

### 3. "Exited cleanly, wrote no terminal state" ≠ mechanical failure

This is the file-protocol analogue of Hermes' `_PROTOCOL_VIOLATION_ERROR`. The remedy
differs because the worker has no tools:

- **Do** look at what the previous run produced (`out/`, a progress file) before
  deciding anything.
- **Do** instruct the next run to **finish and re-publish on top of it**, not redo it.
- **Do** include **the worker's own last output** in the block reason. Quoting it is
  the difference between "we don't know why" and "here is why".
- **Don't** treat it as a hard failure on the first occurrence; escalate to a human
  only after N consecutive no-terminal runs.

### 4. Guards must look on the **execution** host

If the card's workspace is a remote lane, the dispatching machine sees an empty `in/`
even when the execution host's lane is fully populated. An "empty input" guard that
only stats the local path blocks workers that had all of their inputs. Check the
execution host, and accept briefs that cite absolute paths on sibling lanes.

### 5. Redact captures before they land

Captures are logs, and logs are the classic credential-leak surface. Redact **before
writing**, atomically, and key the rule on the **variable name** rather than the value
shape — a bare random token has no `sk-`/`ghp_` prefix:

```
(?i)(?P<vn>[A-Z0-9_]*(?:API_KEY|_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*)
["']?(?P<sep>\s*[=:]\s*)(?P<val>["']?)(?P<secret>[^\s"'=]{8,})(?P=val)
```

Plus a blanket rule for `Bearer …` and known vendor prefixes, applied first.

---

## Why this exists

We drive external CLI agents through kanban as the daily driver: a bridge claims `ready`
cards, runs the CLI on a separate execution host, reads the transcript and result back,
and closes the card from the file protocol above. Three of the five rules above were
learned the expensive way — the skeleton rule alone interrupted three still-running
workers before we found it.

Hermes upstream has an open, closed design for this capability
([#45975](https://github.com/NousResearch/hermes-agent/pull/45975),
*bring-your-own-harness executor* + `cli-exec` backend). It was closed as P3 with an
explicit *"happy to reopen or resubmit … if there is upstream interest"*. Per the repo's
own contribution rubric, third-party integrations of this shape ship as a **standalone
plugin** rather than as core surface — so this repo is that plugin.

## Install / status

**Status: protocol specification only — the executor code is not published yet.**
What is here today is the contract (§1–§5), written so it can be implemented by any
supervisor: ours, a future in-tree `harness` seam, or yours. The reference executor is
being extracted from the production bridge; it will land as a config-driven plugin
(`~/.hermes/plugins/kanban-external-executor`) rather than as a copy of the bridge,
which is wired to one specific topology.

If you want to implement the contract yourself in the meantime, §1–§5 is the whole
specification — there is nothing else the supervisor needs to agree on.

```
# planned layout
kanban-external-executor/
  plugin.py            # claim → run CLI on the execution host → read result → close
  protocol.py          # scan_verdict / is_skeleton_doc / worker_last_words
  guards.py            # empty-input (execution-host aware) / artifact sanity
  redact.py            # capture redaction, keyed on the variable name
  config.example.json  # cli command, execution host, lanes, timeouts
```

## License

MIT
