# AlexanderGPT

A local chat harness for Qwen3-4B and llama.cpp on Windows, macOS, and Linux. It adds token-budgeted context, SQLite recall and task state, approval-based file search, optional SearXNG research, and an on-demand reviewer pass.

## Run from a fresh checkout

Install Python 3.10 or later with SQLite FTS5 and a compatible [llama.cpp build](https://github.com/ggml-org/llama.cpp/releases/tag/b12734). Download the [Qwen3-4B Q4_K_M GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/main/Qwen3-4B-Q4_K_M.gguf) to `.local-ai/Qwen3-4B-Q4_K_M.gguf`. The same 2.5 GB model file works across platforms.

- **Windows.** Extract the [b12734 x64 Vulkan build](https://github.com/ggml-org/llama.cpp/releases/download/b12734/llama-b12734-bin-win-vulkan-x64.zip) so `.local-ai/runner/` contains `llama-server.exe` and its DLLs. Run `.\.local-ai\start-chat.cmd` in PowerShell. Use `4k` for a smaller context allocation. The RX 570 preset uses Vulkan, 28 GPU layers, and an 8,192-token context.
- **macOS.** Choose the [Apple Silicon or Intel build](https://github.com/ggml-org/llama.cpp/releases/tag/b12734). Apple Silicon uses automatic GPU offload with the Metal build. Intel defaults to CPU.
- **Linux.** Choose a CPU build for your architecture or a GPU build that matches your driver. Linux starts in CPU mode by default. If no compatible release is available for your distribution or architecture, use the [upstream build instructions](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md).

On macOS and Linux, place the executable and its companion libraries in `.local-ai/runner/`, install `llama-server` on your PATH, or set `LOCAL_AI_LLAMA_SERVER` to its path. From the checkout, run:

```sh
sh ./.local-ai/start-chat.sh
```

The POSIX launcher uses `python3` and a 4,096-token context by default. It accepts `4k` and `8k`. Set `LOCAL_AI_MODEL` if you keep the GGUF elsewhere. For a Linux GPU build, set `LOCAL_AI_GPU_LAYERS=auto` to let llama.cpp choose the offload. Use `llama-server --list-devices` to check available devices before optionally setting `LOCAL_AI_DEVICE`.

Open [the custom chat](http://127.0.0.1:8082) or [native llama.cpp chat](http://127.0.0.1:8080). Both use the same local runner. The [harness guide](docs/HARNESS.md) covers configuration, Aider, SearXNG, and verification. [CODEX.md](CODEX.md) is the compact continuation guide.

## Verify your setup

Run `python3 -E -B tests/test_harness.py` on macOS or Linux, or `python -E -B .\tests\test_harness.py` on Windows. The tests exercise runner selection and file-path rules for all three platforms. Live inference and file sharing have been verified on Windows. Native inference on macOS and Linux is pending hardware validation.

## Repository layout

| Folder | Contents |
| --- | --- |
| [server/](server/) | Python chat server, context budgeting, SQLite memory, and file handling |
| [web/](web/) | Browser UI, rendering, file selection, and bundled browser libraries |
| [tests/](tests/) | Harness regression tests |
| [benchmarks/](benchmarks/) | Benchmark script, baseline, and synthetic results |
| [docs/](docs/) | Setup and configuration details |
| [`.local-ai/`](.local-ai/) | Launchers, optional SearXNG template, and ignored local runtime files |

The repository shares harness source, browser dependencies with their licenses, example search configuration and synthetic benchmarks. Install the runner and weights separately and keep local chat databases, environments, credentials and file samples outside the published tree.
