# AlexanderGPT

A Windows-local chat harness for Qwen3-4B and llama.cpp. It adds token-budgeted context, SQLite recall and task state, approval-based file search, optional SearXNG research, and an on-demand reviewer pass.

## Run from a fresh checkout

1. Install Python 3.10 or later with SQLite FTS5 available. The launcher expects `python` on your PATH.
2. Download [llama.cpp b12734 for Windows x64 Vulkan](https://github.com/ggml-org/llama.cpp/releases/download/b12734/llama-b12734-bin-win-vulkan-x64.zip). Extract its contents to `.local-ai/runner/` so `llama-server.exe` and the companion DLLs are in that directory.
3. Download [Qwen3-4B Q4_K_M GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/main/Qwen3-4B-Q4_K_M.gguf) to `.local-ai/Qwen3-4B-Q4_K_M.gguf`. The model file is about 2.5 GB.
4. Run `.\.local-ai\start-chat.cmd` in PowerShell, then open [the custom chat](http://127.0.0.1:8082). [Native llama.cpp chat](http://127.0.0.1:8080) is served by the same runner. Use `.\.local-ai\start-chat.cmd 4k` for a smaller context allocation.

The tested setup uses an AMD RX 570 with 4 GB VRAM. [HARNESS.md](.local-ai/HARNESS.md) covers settings, optional SearXNG search, testing, and the synthetic benchmark. [CODEX.md](CODEX.md) is the compact continuation guide.

The repository shares harness source, browser dependencies with their licenses, example search configuration and synthetic benchmarks. Install the runner and weights separately and keep local chat databases, environments, credentials and file samples outside the published tree.
