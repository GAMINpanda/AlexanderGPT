# Codex handoff

**Update and compact this file after each substantive repository change.** Keep entry points, verification and unresolved work here. See the [harness guide](docs/HARNESS.md) for runtime details and [research notes](RESEARCH.md) for design rationale, evidence and future experiments.

## Project and runtime

- AlexanderGPT is a local llama.cpp chat harness for Windows, macOS, and Linux. Run `.\.local-ai\start-chat.cmd` on Windows or `sh ./.local-ai/start-chat.sh` on macOS and Linux. The custom UI on `127.0.0.1:8082` and native UI on `127.0.0.1:8080` share one Qwen3-4B runner and maintain separate chat histories.
- The verified RX 570 4 GB profile uses llama.cpp build b12734, Vulkan, 28 of 37 layers on GPU, q8_0 KV, Flash Attention, and one inference slot. Default context is 8,192. Pass `4k` for 4,096 or `8k` to select 8,192 explicitly. `LOCAL_AI_CONTEXT` can override the default on a plain launch. Full GPU offload has previously exhausted VRAM.
- Runtime binaries, model weights, chat SQLite, virtual environments, logs, smoke files, attachments, and credentials are local. A clean checkout needs the runner and model from [README.md](README.md). The shared files are explicitly allowlisted in `.gitignore`. Review any allowlist change and scan the staged contents before publication.

## Where to continue

- `server/llama_runtime.py` shares runner discovery, backend options and child cleanup between the chat and benchmark. The macOS/Linux default is 4K, with automatic Metal offload on Apple Silicon and CPU defaults for Intel Mac and Linux. The runner and model can be overridden with `LOCAL_AI_LLAMA_SERVER` and `LOCAL_AI_MODEL`.
- `server/compact_chat.py` serves the loopback chat. Thinking streams live, while the final answer is withheld until its token count and stop reason pass the reply-budget check. An oversized draft gets one shorter retry. `server/harness_context.py` budgets rendered prompts and routes Auto thinking.
- `server/chat_memory.py` stores original turns, evidence references, task state, and review notes in chat-scoped SQLite FTS5. Routine turns archive without an extra inference.
- `web/` contains the browser UI, metrics, and Markdown and KaTeX rendering. Direct attachments stay available in the browser tab until removed. Selected excerpts go in the current user message, with token budgeting, so older missing-file replies do not take precedence. Folder grants are single-turn. File turns suppress web search.
- The chat serves coding and general tasks. Web research is opt-in. Explicit references to the user's repository can offer the existing single-turn folder picker without a model call. The optional SearXNG template expects Docker or a JSON-enabled instance.
- **Review answer** runs on the same model with a 3,072-token working budget that can expand to the startup context. The reviewer gets one shorter retry if the notes exceed the reply budget. Only validated notes are saved beside the draft. GPU context allocation changes require a restart.
- `server/terminal_agent.py` runs a 4K-first coding session. Natural-language coding requests route to the edit path; an explicit implementation request in an empty Git workspace creates and applies one validated new file. Existing-file edits and explicit `/edit` requests remain approval-gated. `server/languages/` contains the provider interface and Python implementation for declaration search, qualified definitions, edit alignment, test insertion, syntax checks and test preservation. Add a provider there and register it in `languages/__init__.py`; unsupported files keep generic line-based search and edits. Invalid proposals and failed test runs can be repaired within a shared per-task call and generation budget; identical rejected proposals stop. SQLite stores workspace-scoped Q&A. Resume with `--session` or share the live session with `--browser`.
- `RESEARCH.md` records the relevant 2026 CAKE paper (compiler-agent co-design). Its transferable idea is to turn recurring, measured failures into verifier rules, interface improvements, model calibration, or reusable tactics, then test for regressions. Begin with a small failure catalog tied to existing benchmark cases; do not build a self-modifying harness without evidence.

## Verification

```powershell
python -E -B .\tests\test_harness.py
python -E -B .\benchmarks\benchmark_harness.py
python -X utf8 -E -B .\benchmarks\benchmark_edits.py --check-fixtures
python -X utf8 -E -B .\benchmarks\benchmark_large_repo.py --check-fixtures
```

Use `python3` on macOS and Linux. Windows verification: `python -E -B tests/test_harness.py` passes 49 tests; `python -X utf8 -E -B benchmarks/benchmark_long_tasks.py --check-fixtures` validates the pinned 1,730-file CPython fixture. Native macOS/Linux runs remain unverified.

The long-task benchmark uses an 8K context, 4K pooled generation budget, the same Qwen model and seeds for the direct baseline and test-driven workflow. Earlier 3-seed comparison: direct passed 3/3; plan/checkpoint passed 0/3 and repeatedly proposed the equality-only regression. The bounded retry variant with duplicate suppression also passed 0/3 (4–6 calls, 638–907 generated tokens, 85–127 s). A later seed-7 run added behavior-preservation wording and one plan correction; it still failed after three repairs. Do not make plan-first editing the default; the direct baseline remains the control. Per-seed reports are ignored in `.local-ai/long-task-benchmark/`; see RESEARCH.md for experiment boundaries.

Natural-language implementation requests route to editing. In an empty Git workspace, an explicit request creates and applies one syntax-checked file; a disposable local-model smoke test created `sort_list.py` in one call and passed `py_compile`. Existing-file changes remain approval-gated. Failed-test `/retry` attempts share task call/generated limits, preserve rejected drafts, and stop on identical proposals.
