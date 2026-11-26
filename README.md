# AlexanderGPT

A local chat harness for Qwen3-4B and llama.cpp on Windows, macOS, and Linux. It adds token-budgeted context, SQLite recall and task state, approval-based file search, optional SearXNG research, and an on-demand reviewer pass.

Ask coding questions and give general tasks in the same chat. Enable **Web research (SearXNG)** when you want online sources. Use the built-in terminal agent or the optional Aider client for workspace edits and tests.

## Run the terminal agent

From the AlexanderGPT checkout, start a session in the current Git workspace or pass `--workspace` with another project's path.

```powershell
python -X utf8 -E -B server/terminal_agent.py --browser --test python -E -B tests/test_harness.py
```

Use `python3` for both Python invocations on macOS and Linux. Omit `--browser` for a terminal-only session. Use `--connect` if the local llama.cpp runner is already running on port 8080. The agent defaults to a 4K context budget and starts one local model when it owns the runner.

Type a general question or use `/search`, `/ask` and `/edit` to work with your repository. An edit shows a diff and an approval ID. Apply it with `/apply ID`, then run the configured command with `/test`. See the [agent workflow](docs/HARNESS.md#terminal-agent) for details.

Try “Find the login handler in this codebase” to search the selected workspace directly. Use `/history` to inspect saved turns, or restart with the printed `--session` name and the same workspace to resume. The standalone chat keeps its own history.

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

Run `python3 -E -B tests/test_harness.py` on macOS or Linux, or `python -E -B .\tests\test_harness.py` on Windows. The regression suite covers platform profiles, workspace routing, history recall and edit approvals. Live Windows checks cover repository search, a follow-up answered from history, and a fix verified through the shared terminal and browser session. Native inference on macOS and Linux is pending hardware validation. See [RESEARCH.md](RESEARCH.md) for the design rationale, evidence and evaluation roadmap.

Run `python -X utf8 -E -B benchmarks/benchmark_edits.py` for the [4K edit regression benchmark](docs/HARNESS.md#edit-regression-benchmark). Its fixtures, logs and results are generated locally.

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
