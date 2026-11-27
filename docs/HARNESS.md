# Local inference harness

Run `.\.local-ai\start-chat.cmd` on Windows or `sh ./.local-ai/start-chat.sh` on macOS and Linux, then open [local chat](http://127.0.0.1:8082). The launcher starts llama.cpp on port 8080 and the compacting browser chat on port 8082. The sidebar lists archived chats and opens each conversation with its own history and task memory. On smaller screens, use **Chats**. Press **Enter** to send and **Shift+Enter** to add a line. The browser chat defaults to Auto, with Think and Quick available for direct control.

## Model and context

The model is Qwen3-4B Q4_K_M, with a 40,960-token training context and a hybrid thinking chat template. The Windows RX 570 profile uses Vulkan, offloads 28 of 37 layers, and defaults to 8,192 tokens. macOS and Linux default to 4,096 tokens and f16 KV. Apple Silicon uses automatic offload with the Metal build. Intel Macs and Linux default to CPU. Either launcher accepts `4k` or `8k`. Use [the README](../README.md) to select a runner for your OS and architecture.

The original harness already supported SQLite FTS5 recall, an automatically rewritten rolling summary, streaming thinking, manual Think and Quick modes, and iterative SearXNG. It already used Flash Attention and an 8-bit KV cache. The changes below build on those paths in the same browser UI and launcher.

### Built-in llama.cpp UI and the harness

The installed runner's [native UI](http://127.0.0.1:8080) and the [harness UI](http://127.0.0.1:8082) share the same loaded model. The native UI already has conversation management, collapsible reasoning, streaming, full Markdown, highlighted code, KaTeX, and MCP tool support. The harness renders streaming and archived replies with locally served markdown-it and KaTeX. It escapes raw HTML and shows external images as links. Each UI keeps its own conversation history. [Native UI documentation](https://github.com/ggml-org/llama.cpp/blob/master/ui/apps/chat/README.md)

The harness adds four groups of behaviour around llama.cpp: token-budgeted context assembly and eviction, per-chat SQLite recall and structured task state, automatic reasoning and verification, and iterative SearXNG research with request-level diagnostics. The underlying inference, thinking token generation, KV cache, Flash Attention, tokenisation, and sampling all come from llama.cpp. Its context shifting can discard older tokens during generation. The harness instead builds a new prompt from selected context before inference. The benchmark compares two revisions of the harness. Native UI performance was outside that benchmark.

The harness rebuilds each answer prompt from the system instructions, the current request, relevant research, current task state, retrieved memory and recent turns. It measures the rendered template using llama.cpp's tokenizer, reserves generation tokens plus a safety margin, and adds optional material until it reaches the pressure threshold. Important material can use spare capacity above the threshold. Duplicate text is skipped. Untrusted background is supplied separately from the system instructions. The latest request stays intact. An oversized request returns an error asking for a smaller excerpt.

Archived turns, task snapshots and source references remain available after eviction. Most turns archive directly without a compaction inference. When task instructions or decisions change, the model can return a compact, schema-validated snapshot. A pressure-triggered summary can be generated from original recent turns when structured task tracking is disabled. The file archive retains the original turns in either case.

## Storage and tools

Coding questions, writing tasks, and general information use the same local chat and model. **Web research (SearXNG)** starts off each time the page loads. Enable it to allow online research independently of the Auto, Think and Quick settings. A request such as “Find the login handler in this codebase” can offer a folder picker without a model planning pass.

`chat-memory.sqlite3` holds original user requests and final answers, per-turn metadata, source links with the excerpts supplied by SearXNG, and structured task state. Existing FTS entries remain readable. Entries created before this change lack the new metadata. SQLite FTS5 combines BM25 with importance and a small recency boost. The context assembler admits matching excerpts under the token budget. The browser's New chat button starts a separate conversation while earlier records remain on disk.

Auto uses a cheap heuristic for obvious cases. An ambiguous request gives Qwen a short first pass in which it can request thinking, additional memory, or the source excerpts for a memory reference. The harness validates the request and limits additional passes. Task state updates use a schema for objectives, constraints, findings, decisions, completed work, outstanding work and references. Thinking traces appear in the browser transcript and stay out of the SQLite working memory.

**Review answer** runs the reviewer on the same loaded model. It reads the original request, draft, related memory and saved source excerpts. File excerpts can also be passed from the original turn while it is open in the same browser tab. The reviewer starts with a 3,072-token working budget and can use the full configured window if the request and draft need it. The server's KV allocation stays fixed for the session. Notes are checked against the review-token limit before display and saving. If a draft exceeds the limit, the reviewer gets one shorter retry within its inference budget. A successful review replaces any previous notes beside that draft in SQLite.

Search uses the configured SearXNG instance and can run follow-up queries. The harness retains short evidence and numbered links. It gives Qwen one chance to rephrase a duplicate query and can narrow a follow-up when a source explicitly identifies a missing fact. The loop also ends when it exhausts the request budget, hits a provider failure, or runs out of time. SearXNG snippets are evidence from the search provider. Stored source reads return those excerpts and links. The harness checks citation numbers, verifies simple integer arithmetic and parses fenced Python with the standard parser. It can attempt one syntax repair within the escalation budget. It does not execute generated code or take external actions on the model's behalf.

Use **Attach file** to open a file picker or paste an absolute local path. On macOS and Linux, paths starting with `~/` work too. It accepts up to three UTF-8 or UTF-16 text files per message, at most 512 KiB each. The browser selects question-relevant chunks from large attachments, and the harness fits excerpts into the same token budget as the rest of the prompt. If Qwen proposes a file search, the chat shows the query and reason first. **Choose folder and allow once** gives the browser a folder to scan for that turn. **Continue without files** declines the request. The scan skips common dependency, build, and credential paths and reads up to 2,400 candidates or 24 MiB. Up to three matched excerpts go to the local model. The harness suspends web search during the file turn. Raw file contents are kept out of the SQLite archive, while any file details quoted in the answer are part of that saved answer.

## Configuration

Set variables before launching. For example, use `$env:LOCAL_AI_DIAGNOSTICS = '1'` in PowerShell or `export LOCAL_AI_DIAGNOSTICS=1` on macOS and Linux. Restart the launcher to apply settings.

| Environment variable | Default | Purpose |
| --- | ---: | --- |
| `LOCAL_AI_CONTEXT` | Windows 8192, macOS/Linux 4096 | Context capacity passed to llama.cpp. Larger values can exceed available memory. |
| `LOCAL_AI_LLAMA_SERVER` | Bundled runner, then PATH | Executable path or command name to use instead of automatic discovery. |
| `LOCAL_AI_MODEL` | `.local-ai/Qwen3-4B-Q4_K_M.gguf` | Path to the local GGUF. |
| `LOCAL_AI_PYTHON` | python3 | Python executable for the POSIX launcher. |
| `LOCAL_AI_GPU_LAYERS` | Windows 28, Apple Silicon auto, Linux and Intel Mac 0 | GPU offload layers. Set `0` for CPU or `auto` for automatic offload with a compatible build. |
| `LOCAL_AI_DEVICE` | Windows Vulkan0, automatic selection elsewhere | Optional device name from `llama-server --list-devices`. Empty uses the runner's device selection. |
| `LOCAL_AI_REPLY_TOKENS` | 512 | Generation budget in Quick and final-answer reserve in Think. |
| `LOCAL_AI_REVIEW_CONTEXT` | 3072 | Preferred working context for an optional reviewer pass. |
| `LOCAL_AI_REVIEW_TOKENS` | 320 | Maximum tokens generated by one reviewer pass. |
| `LOCAL_AI_THINK_TOKENS` | 640 | Runner reasoning cap. Thinking calls share the overall generation budget of reasoning plus reply tokens. |
| `LOCAL_AI_COMPACT_PERCENT` | 80 | Target utilisation of the available input budget for optional information. |
| `LOCAL_AI_SUMMARY_TOKENS` | 192 | Structured task update or legacy summary generation limit. |
| `LOCAL_AI_MAX_CALLS` | 16 | Maximum generation calls per HTTP request; terminal edit tasks aggregate this limit across `/edit` and `/retry`. |
| `LOCAL_AI_MAX_GENERATED` | 4096 | Combined generation token ceiling per HTTP request; terminal edit tasks aggregate it across `/edit` and `/retry`. |
| `LOCAL_AI_MAX_ESCALATIONS` | 1 | Additional reasoning, retrieval or correction passes. |
| `LOCAL_AI_ADAPTIVE` | 1 | Enable Auto routing and model-requested escalation. |
| `LOCAL_AI_RETRIEVE` | 1 | Enable automatic FTS excerpts and explicit memory/source tools. |
| `LOCAL_AI_TASK_STATE` | 1 | Enable structured task-state updates. |
| `LOCAL_AI_KV` | Windows GPU q8_0, otherwise f16 | KV cache type used for keys and values. |
| `LOCAL_AI_FLASH` | Windows GPU on, otherwise auto | Flash Attention option passed to llama.cpp. |
| `LOCAL_AI_PROMPT_CACHE` | 1 | Reuse prompt prefixes where the runner supports reuse. |
| `LOCAL_AI_CACHE_RAM_MIB` | 256 | Host RAM limit for retained prompt cache entries. |
| `LOCAL_AI_DIAGNOSTICS` | 0 | Emit JSON records containing timing, counts and event types. |
| `LOCAL_AI_RESEARCH_SECONDS` | 150 | Research time window. Set to 0 to use only other stop conditions. |
| `SEARXNG_URL` | http://127.0.0.1:8888 | SearXNG instance with JSON search enabled. |

The browser shows final-call context, generation speed and reasoning tokens, plus aggregate request and compaction diagnostics. Reasoning tokens are estimated with the model tokenizer if the backend omits their breakdown. Token-count requests are reused within a turn. The optional diagnostic logs omit prompt text, replies, search queries and memory contents. Higher context, reply and reasoning settings need enough room to fit together.

Thinking can stream live. The harness holds the final answer until it checks the text with the model's tokenizer and confirms generation finished within the reply limit. A draft that exceeds the cap gets one shorter retry if the inference budget permits it.

An 8,192-token launch was tested on the RX 570 with 28 layers offloaded and the default quantised KV cache. It handled a 4,272-token prompt successfully and used a 459 MiB GPU KV buffer. Set `$env:LOCAL_AI_CONTEXT = '8192'` before starting the launcher to use that profile. Available VRAM depends on other applications, and the reply-token setting is independent of the context size.

For optional Aider use, run `.\.local-ai\start-aider.cmd` on Windows with its local venv or `sh ./.local-ai/start-aider.sh` on macOS and Linux. The shell script uses the project venv if available, then an `aider` executable on PATH. Start the chat server first. The legacy `start-chat.cmd coder` preset is Windows-specific.

## Terminal agent

```powershell
python -X utf8 -E -B server/terminal_agent.py --workspace C:\path\to\repo --browser --test python -m pytest
```

Use the test executable and arguments appropriate for that project. Put `--test` last. The agent runs the command directly from the selected workspace. With `--connect` it uses the runner already on port 8080 and caps the prompt budget at the lower of the requested and running context sizes. Add `--context 8192` to request 8K. `--prompt` runs one question or command and exits.

- Plain questions use the existing harness. Terminal `/web` and the browser checkbox independently enable optional SearXNG research for those questions.
- `/search discount_price` finds excerpts without inference. `/ask Where is discount_price called?` sends up to three line-numbered excerpts to Qwen. Plain repository lookups also search the selected workspace. Language providers supply declaration patterns and qualified symbol details; the registered Python provider handles `.py` and `.pyi`. A second pass ranks text in up to 48 matching files. Providers may also add language-specific edit alignment, syntax checks, insertion anchors and test-preservation rules. Files without a provider retain generic line-based search and edits.
- A short question asking where one exact symbol is defined can start with one excerpt and a short prompt. The agent uses the full evidence path when the definition is ambiguous, the request asks for callers or wider context, or conversation history is available. If the small reply omits the expected location or reports insufficient evidence, the agent tries the full context.
- For broad questions such as “Tell me about this codebase,” the agent supplies a bounded Git-visible file listing and an excerpt from the root README when available.
- Natural-language implementation requests (for example, `Could you implement a Python function to sort a list?`) enter the coding path. In an empty Git workspace, the agent proposes one safe new file, validates Python syntax, and applies it because the request explicitly asks for an implementation. A configured `--test` command runs after creation. Existing-file edits remain previewed until `/apply ID` approves them; explicit `/edit` requests also remain previewed. `/apply` checks the original file bytes for edits and uses exclusive creation for new-file paths.
- `/edit Fix discount_price in pricing.py to subtract the discount` asks Qwen for one replacement at numbered lines from the shown source. The response schema constrains the file and line choices. Invalid proposals receive validation feedback and can be retried while the task budget permits; identical rejected proposals stop further inference. Python replacements are syntax-checked, with the parser's line and error kind included in a syntax retry. For additive Python tests, the agent retains implementation excerpts even when the target test file is named, and anchors insertion after the last visible existing test. Validation checks that original test functions are preserved and a new one exists. `/apply ID` writes the previewed edit after checking the original file bytes.
- Edit prompts add test-preservation instructions and validation feedback when the request needs them. The file, line, syntax and approval checks still run independently of the prompt.
- `/test` runs the configured command with a 60-second timeout and shows its exit code and output tail. If it fails after applying an existing-file edit, `/retry` proposes a correction using the failure output. Review and apply the new diff, then rerun the tests. Repeat this cycle until they pass or the task's aggregate model-call or generation budget is exhausted. Every retry must follow a fresh failed test run.
- `--browser` prints a loopback URL. Both clients share the pending proposal and the browser displays the latest 20 command results, including terminal commands. Browser `/apply` and `/test` actions require confirmation. A natural-language request to implement one file in an empty workspace applies that file directly. Pending approvals end with `/quit` or Ctrl+C.
- The agent saves original questions and answers, including file-backed turns, in local SQLite. It budgets recent turns and relevant older excerpts alongside current evidence. Use `/history` to inspect recent saved turns or restart with the printed `--session` name and the same workspace to resume. The standalone chat has its own history.

The agent proposes changes to one existing UTF-8 file at a time, and can create one file from an explicit natural-language request in an empty Git workspace. It prints model calls, input and generated tokens, total time and repository search time.

On the Windows RX 570, the agent reused the running Qwen3-4B instance with a 4K agent budget. In a disposable Git workspace, it proposed an arithmetic fix in the terminal using one model call with 207 input tokens and 70 generated tokens. Search took 32 ms. The browser rejected an unapproved apply request, accepted the confirmed diff and ran the previously failing test successfully. In a separate cold 4K run, the agent found `login_handler` from a plain-language request in 47 ms of search and named the file again on the follow-up using saved history without rescanning. Larger repositories and native macOS/Linux runs still need live verification.

The [research notes](../RESEARCH.md) explain the design choices and lay out experiments for repository indexing, history retrieval and verified coding tasks.

## Tests and benchmark

### Edit regression benchmark

Run from the checkout. The full run uses seeds 7, 19 and 42, and starts one 4K runner if none is active.

```powershell
python -X utf8 -E -B benchmarks/benchmark_edits.py --check-fixtures
python -X utf8 -E -B benchmarks/benchmark_edits.py
```

Use `python3` on macOS or Linux. An active runner must already be at 4K. Use `--case billing --seed 19` for a single edit and its corresponding lookup check. By default, an unverified edit is replayed from a clean fixture with hand-supplied source. Use `--no-oracle` to skip those controls.

The four cases cover the billing control, a regional pricing change, a stock reservation boundary bug, and an additive regression test. They run against two synthetic repositories created in disposable directories. The verifier checks original tests and task-specific behaviour. For test generation it also checks that the new test catches a known broken implementation and that the original tests remain intact.

The report distinguishes a valid first model proposal, a verified first proposal, and eventual success. It records model calls and tokens, elapsed time, proposed changes, test output, and the evidence sent to the model. By default, it writes `.local-ai/edit-benchmark/results.json` and a local runner log. These files are ignored by Git.

### Large repository benchmark

This benchmark uses the pinned, local CPython 3.10.8 standard-library snapshot (commit `6fc9bf58a755731706618355a1ec2cbb027ef428`) and adds three isolated task fixtures to a temporary clone. It covers an overview, three definition lookups, saved-history recall, a bug fix, regression-test addition, and a two-file change. It checks retrieval separately from answer citations, verifies edits with tests, mutates the implementation to ensure the new test catches the regression, and records calls, tokens, search time, and elapsed time. The source snapshot is not changed.

```powershell
python -X utf8 -E -B benchmarks/benchmark_large_repo.py --check-fixtures
python -X utf8 -E -B benchmarks/benchmark_large_repo.py
```

The full run uses seeds 7, 19, and 42 at 4K. Use repeated `--case` or `--seed` arguments for a smaller run, such as `--case navigation --seed 7`. The CPython fixture must be installed by `.local-ai/agent-tasks/install.py` and remain clean at the pinned revision. Results and the runner log are written under the ignored `.local-ai/large-benchmark/` directory.

The first full run retrieved all nine target definitions in its three lookup tasks, but the model answered the base HTML callback question incorrectly for all three seeds. It passed history recall 3/3, bug fixes 3/3 and two-file edits 3/3. Additive test writing passed 0/3: the model repeated an existing test in its insertion, and the AST validator rejected the duplicate. See [the local report](../.local-ai/large-benchmark/results.json) on the benchmark machine for prompts, evidence, diffs and token counts.

### Chat benchmark

```powershell
python -E -B .\tests\test_harness.py
python -E -B .\benchmarks\benchmark_harness.py
```

```sh
python3 -E -B tests/test_harness.py
python3 -E -B benchmarks/benchmark_harness.py
```

Stop an existing chat server before benchmarking to free memory. The benchmark starts one runner at 4K on port 18080 and compares [benchmark-baseline.zip](../benchmarks/benchmark-baseline.zip) to the current server. Both use the same model, context, cache type, GPU split, reasoning cap and seed. Prompt caching is disabled for measurement. The baseline uses Think and the optimised chat uses Auto. This measures the complete change in defaults, including routing and archive work. macOS and Linux write platform-specific results by default to preserve the committed Windows run.

The benchmark seeds two chats with older exact values and 18 irrelevant turns, then checks arithmetic, coding, multi-step reasoning and recall using task-specific answer patterns. Latency includes archival and compaction. This is a focused local smoke benchmark, with one sample per case. It does not measure broad coding accuracy, live web quality or long-running agent behaviour. See [benchmark-results.json](../benchmarks/benchmark-results.json) for individual results.

| Measured on the RX 570 | Baseline | Optimised |
| --- | ---: | ---: |
| Correct and completed | 6/6 | 6/6 |
| Median end-to-end latency | 42.87 s | 10.91 s |
| Total end-to-end time | 285.72 s | 159.86 s |
| Generation calls | 12 | 6 |
| Input tokens across calls | 1,598 | 934 |
| Generated tokens across calls | 2,944 | 1,721 |

The simple arithmetic turn took 15.60 s before and 1.18 s after. The optimised multi-step reasoning turn still took 76.11 s, so measured savings are largest when Auto can answer directly and archive without an extra generation.

A separate 4K run compared the harness immediately before and after the local-first routing and system prompt update. Both passed 6/6 with six generation calls. Input tokens rose from 1,216 to 1,342 and generated tokens from 1,358 to 1,386. Total time was 138.71 s before and 136.26 s after. The suite sends direct chat requests with web research off, so it measures ordinary chat and does not quantify the savings from skipping search. A regression test verifies that an explicit local repository request needs zero generation calls to offer folder access.
