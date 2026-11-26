# Codex handoff

**Update and compact this file after each substantive repository change.** Replace stale details with the current state and keep only information needed to resume work. Record decisions, changed entry points, meaningful verification, and unresolved work. Use the harness guide for durable detail and Git history for completed changes.

## Project and runtime

- AlexanderGPT is a local llama.cpp chat harness for Windows, macOS, and Linux. Run `.\.local-ai\start-chat.cmd` on Windows or `sh ./.local-ai/start-chat.sh` on macOS and Linux. The custom UI on `127.0.0.1:8082` and native UI on `127.0.0.1:8080` share one Qwen3-4B runner and maintain separate chat histories.
- The verified RX 570 4 GB profile uses llama.cpp build b12734, Vulkan, 28 of 37 layers on GPU, q8_0 KV, Flash Attention, and one inference slot. Default context is 8,192. Pass `4k` for 4,096 or `8k` to select 8,192 explicitly. `LOCAL_AI_CONTEXT` can override the default on a plain launch. Full GPU offload has previously exhausted VRAM.
- Runtime binaries, model weights, chat SQLite, virtual environments, logs, smoke files, attachments, and credentials are local. A clean checkout needs the runner and model from [README.md](README.md). The shared files are explicitly allowlisted in `.gitignore`. Review any allowlist change and scan the staged contents before publication.

## Where to continue

- `server/llama_runtime.py` shares runner discovery, backend options and child cleanup between the chat and benchmark. The macOS/Linux default is 4K, with automatic Metal offload on Apple Silicon and CPU defaults for Intel Mac and Linux. The runner and model can be overridden with `LOCAL_AI_LLAMA_SERVER` and `LOCAL_AI_MODEL`.
- `server/compact_chat.py` serves the loopback chat. `server/harness_context.py` budgets rendered-template tokens and routes Auto thinking. See [the harness guide](docs/HARNESS.md) for settings.
- `server/chat_memory.py` stores original turns, evidence references, task state, and review notes in chat-scoped SQLite FTS5. Routine turns archive without an extra inference.
- `web/` contains the browser UI, sidebar, live thinking, metrics, and local Markdown and KaTeX rendering. `web/file-sharing.js` and `server/local_files.py` handle attachments and approval-based folder search. File turns suppress web search.
- SearXNG research can run multiple bounded searches and carry forward evidence. The optional template in `.local-ai/searxng/` expects Docker or a separately supplied JSON-enabled instance. Provider behaviour was tested with a fixture. A live instance depends on local setup.
- **Review answer** runs one explicitly requested reviewer pass on the same model. It starts with a 3,072-token working budget and can expand to the startup context. Notes are saved separately beside the draft. Changing GPU context allocation requires a server restart.
- The `start-aider.cmd` and `start-aider.sh` launchers are optional clients for the native API. `start-chat.cmd coder` is the legacy Windows preset.

## Verification

```powershell
python -E -B .\tests\test_harness.py
python -E -B .\benchmarks\benchmark_harness.py
```

Use the same scripts with `python3` on macOS and Linux. The benchmark fixes context at 4K and uses the frozen baseline. All 14 tests passed, including platform profiles and path rules. The POSIX launcher options passed a shell smoke test, and the 8K RX 570 profile passed live Windows inference and file sharing. Native macOS and Linux inference and shutdown still need verification.
