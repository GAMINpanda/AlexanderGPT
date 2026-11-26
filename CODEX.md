# Codex handoff

**Update and compact this file after each substantive repository change.** Replace stale details with the current state and keep only information needed to resume work. Record decisions, changed entry points, meaningful verification, and unresolved work. Use the harness guide for durable detail and Git history for completed changes.

## Project and runtime

- AlexanderGPT is a Windows-local chat and coding harness around llama.cpp and Qwen3-4B Q4_K_M. Start it with `.\.local-ai\start-chat.cmd` from the repository root. Open the custom chat on `http://127.0.0.1:8082` or native llama.cpp chat on `http://127.0.0.1:8080`. They share one loaded model and maintain separate chat histories.
- The verified RX 570 4 GB profile uses llama.cpp build b12734, Vulkan, 28 of 37 layers on GPU, q8_0 KV, Flash Attention, and one inference slot. Default context is 8,192. Pass `4k` for 4,096 or `8k` to select 8,192 explicitly. `LOCAL_AI_CONTEXT` can override the default on a plain launch. Full GPU offload has previously exhausted VRAM.
- Runtime binaries, model weights, chat SQLite, virtual environments, logs, smoke files, attachments, and credentials are local. A clean checkout needs the runner and model from [README.md](README.md). The shared files are explicitly allowlisted in `.gitignore`. Review any allowlist change and scan the staged contents before publication.

## Where to continue

- `server/compact_chat.py` serves the loopback chat and drives llama.cpp. `server/harness_context.py` budgets rendered-template tokens. Auto mode uses Quick for straightforward work and can escalate to thinking. See [the harness guide](docs/HARNESS.md) for settings.
- `server/chat_memory.py` stores original turns, evidence references, task state, and review notes in chat-scoped SQLite FTS5. Routine turns archive without an extra inference.
- `web/` contains the browser UI, sidebar, live thinking, metrics, and local Markdown and KaTeX rendering. `web/file-sharing.js` and `server/local_files.py` handle attachments and approval-based folder search. File turns suppress web search.
- SearXNG research can run multiple bounded searches and carry forward evidence. The optional template in `.local-ai/searxng/` expects Docker or a separately supplied JSON-enabled instance. Provider behaviour was tested with a fixture. A live instance depends on local setup.
- **Review answer** runs one explicitly requested reviewer pass on the same model. It starts with a 3,072-token working budget and can expand to the startup context. Notes are saved separately beside the draft. Changing GPU context allocation requires a server restart.
- `.local-ai/start-aider.cmd` is an optional client for the native API. `start-chat.cmd coder` launches the older Qwen2.5-Coder 3B preset if its weights are present.

## Verification

```powershell
python -E -B .\tests\test_harness.py
python -E -B .\benchmarks\benchmark_harness.py
```

The benchmark uses synthetic tasks, a frozen harness baseline, and 4K on the same runner. Its saved results compare two harness revisions. Live checks have covered 8K inference, browser rendering, chat switching, local file permission and reviewer persistence. Repeat the relevant tests before updating the handoff.
