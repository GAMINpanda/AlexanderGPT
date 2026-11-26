# Codex handoff

**Update and compact this file after each substantive repository change.** Replace stale details with the current state and keep only information needed to resume work. Record decisions, changed entry points, meaningful verification, and unresolved work. Use the harness guide for durable detail and Git history for completed changes.

## Project and runtime

- AlexanderGPT is a Windows-local chat and coding harness around llama.cpp and Qwen3-4B Q4_K_M. Start it with `.\.local-ai\start-chat.cmd` from the repository root. Open the custom chat on `http://127.0.0.1:8082` or native llama.cpp chat on `http://127.0.0.1:8080`. They share one loaded model and maintain separate chat histories.
- The verified RX 570 4 GB profile uses llama.cpp build b12734, Vulkan, 28 of 37 layers on GPU, q8_0 KV, Flash Attention, and one inference slot. Default context is 8,192. Pass `4k` for 4,096 or `8k` to select 8,192 explicitly. `LOCAL_AI_CONTEXT` can override the default on a plain launch. Full GPU offload has previously exhausted VRAM.
- Runtime binaries, model weights, chat SQLite, virtual environments, logs, smoke files, attachments, and credentials are local. A clean checkout needs the runner and model from [README.md](README.md). The shared files are explicitly allowlisted in `.gitignore`. Review any allowlist change and scan the staged contents before publication.

## Where to continue

- `.local-ai/compact-chat.py` serves the loopback chat and drives llama.cpp. `harness_context.py` uses rendered-template token counts to budget input, evidence, and output. Auto mode uses Quick for straightforward work and can escalate to thinking. Token limits, diagnostics, and hardware settings are in [HARNESS.md](.local-ai/HARNESS.md).
- `.local-ai/chat_memory.py` stores original turns, evidence references, task state and review notes in chat-scoped SQLite FTS5. Routine turns archive without an extra inference. Original turns are the source of truth for recall and reviews.
- `.local-ai/compact-chat.html` provides the sidebar, chat switching, live thinking, metrics and attachment controls. `reply-markdown.js` renders streamed and saved replies with local markdown-it and KaTeX. The vendor folders contain upstream notices.
- `file-sharing.js` and `local_files.py` handle text attachments and explicit local path sharing. A Qwen folder-search proposal shows its reason and query, then waits for the user to choose a folder. The browser filters candidates and sends bounded excerpts. Web search is suppressed on file turns.
- SearXNG research can run multiple bounded searches and carry forward evidence. The optional template in `.local-ai/searxng/` expects Docker or a separately supplied JSON-enabled instance. Provider behaviour was tested with a fixture. A live instance depends on local setup.
- **Review answer** runs one explicitly requested reviewer pass on the same model. It starts with a 3,072-token working budget and can expand to the startup context. Notes are saved separately beside the draft. Changing GPU context allocation requires a server restart.
- `.local-ai/start-aider.cmd` is an optional client for the native API. `start-chat.cmd coder` launches the older Qwen2.5-Coder 3B preset if its weights are present.

## Verification

```powershell
python -E -B .\.local-ai\test_harness.py
python -E -B .\.local-ai\benchmark_harness.py
```

The benchmark uses synthetic tasks, a frozen harness baseline, and 4K on the same runner. Its saved results compare two harness revisions. Live checks have covered 8K inference, browser rendering, chat switching, local file permission and reviewer persistence. Repeat the relevant tests before updating the handoff.
