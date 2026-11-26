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
- `server/terminal_agent.py` runs a 4K-first coding session. `server/languages/` contains the provider interface and Python implementation for declaration search, qualified definitions, edit alignment, test insertion, syntax checks and test preservation. Add a provider there and register it in `languages/__init__.py`; unsupported files keep generic line-based search and edits. Unambiguous exact-definition questions without prior context can start with one excerpt and fall back to the normal path. Test-add requests retain relevant implementation excerpts even when a target test file is named, then anchor insertion after the last visible test. Edits still require approval and can be checked with `/test` and `/retry`. SQLite stores workspace-scoped Q&A. Resume with `--session` or share the live session with `--browser`.

## Verification

```powershell
python -E -B .\tests\test_harness.py
python -E -B .\benchmarks\benchmark_harness.py
python -X utf8 -E -B .\benchmarks\benchmark_edits.py --check-fixtures
python -X utf8 -E -B .\benchmarks\benchmark_large_repo.py --check-fixtures
```

Use `python3` on macOS and Linux. All 40 tests passed. The 4K fixture checks cover exact citations, billing repair, implementation evidence for additive tests, anchored insertion, syntax feedback, provider selection, generic edits for unregistered files, history and browser search. Native macOS/Linux runs remain unverified.

The ignored `.local-ai/agent-tasks/` directory contains clean fixtures and scored reports. In `ADAPTIVE.md`, focused lookup passed 3/3 at 218 input tokens versus 1,100. The experimental short edit prompt passed 0/3 against 3/3 for the fuller prompt, which remains in production. Repeat across more tasks before widening the focused path.

`benchmarks/benchmark_edits.py` builds two disposable repositories and checks four edits plus focused lookups across seeds 7, 19 and 42. With syntax feedback, AST-anchored test insertion and retained implementation excerpts, the full 4K run passed 12/12 edits (9 first proposal, 3 regional edits after retry) and 3/3 lookups. The initial large CPython run passed navigation 9/12, history 3/3, bug fixes 3/3 and two-file edits 3/3; it missed the HTML base callback 3/3 despite retrieving the definitions and additive test writing failed 0/3. A focused run after source grounding returned a correct source pointer on all three HTML seeds, but all used the deterministic fallback after an ungrounded answer and retry. Additive test writing passed 1/3 in the focused run: seed 7 produced a mutation-verified test, while seeds 19 and 42 still proposed an incomplete assertion after syntax feedback. Keep fallback success separate from model explanation success. Reports are ignored under `.local-ai/large-benchmark/`.
