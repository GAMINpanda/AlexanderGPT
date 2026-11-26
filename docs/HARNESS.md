# Local inference harness

Run `.\.local-ai\start-chat.cmd` from the workspace and open [local chat](http://127.0.0.1:8082). The launcher starts llama.cpp on port 8080 and the compacting browser chat on port 8082. The sidebar lists archived chats and opens each conversation with its own history and task memory. On smaller screens, use the **Chats** button. Press **Enter** to send and **Shift+Enter** to add a line. The llama.cpp API and the previous Qwen2.5 Coder launcher option are still available. The browser chat defaults to Auto, with Think and Quick available for direct control.

## Model and context

The model is Qwen3-4B Q4_K_M. The Windows llama.cpp build uses Vulkan on the RX 570. The launcher offloads 28 of 37 layers, with the remaining layers on CPU. The GGUF reports a 40,960-token training context. The launcher defaults to 8,192 tokens. Use `.\.local-ai\start-chat.cmd 4k` to fit a tighter VRAM budget or pass `8k` to select 8,192 explicitly. This model supports both thinking and non-thinking generation through its chat template.

The original harness already supported SQLite FTS5 recall, an automatically rewritten rolling summary, streaming thinking, manual Think and Quick modes, and iterative SearXNG. It already used Flash Attention and an 8-bit KV cache. The changes below build on those paths in the same browser UI and launcher.

### Built-in llama.cpp UI and the harness

The installed runner's [native UI](http://127.0.0.1:8080) and the [harness UI](http://127.0.0.1:8082) share the same loaded model. The native UI already has conversation management, collapsible reasoning, streaming, full Markdown, highlighted code, KaTeX, and MCP tool support. The harness renders streaming and archived replies with locally served markdown-it and KaTeX. It escapes raw HTML and shows external images as links. Each UI keeps its own conversation history. [Native UI documentation](https://github.com/ggml-org/llama.cpp/blob/master/ui/apps/chat/README.md)

The harness adds four groups of behaviour around llama.cpp: token-budgeted context assembly and eviction, per-chat SQLite recall and structured task state, automatic reasoning and verification, and iterative SearXNG research with request-level diagnostics. The underlying inference, thinking token generation, KV cache, Flash Attention, tokenisation, and sampling all come from llama.cpp. Its context shifting can discard older tokens during generation. The harness instead builds a new prompt from selected context before inference. The benchmark compares two revisions of the harness. Native UI performance was outside that benchmark.

The harness rebuilds each answer prompt from the system instructions, the current request, relevant research, current task state, retrieved memory and recent turns. It measures the rendered template using llama.cpp's tokenizer, reserves generation tokens plus a safety margin, and adds optional material until it reaches the pressure threshold. Important material can use spare capacity above the threshold. Duplicate text is skipped. Untrusted background is supplied separately from the system instructions. The latest request stays intact. An oversized request returns an error asking for a smaller excerpt.

Archived turns, task snapshots and source references remain available after eviction. Most turns archive directly without a compaction inference. When task instructions or decisions change, the model can return a compact, schema-validated snapshot. A pressure-triggered summary can be generated from original recent turns when structured task tracking is disabled. The file archive retains the original turns in either case.

## Storage and tools

`chat-memory.sqlite3` holds original user requests and final answers, per-turn metadata, source links with the excerpts supplied by SearXNG, and structured task state. Existing FTS entries remain readable. Entries created before this change lack the new metadata. SQLite FTS5 combines BM25 with importance and a small recency boost. The context assembler admits matching excerpts under the token budget. The browser's New chat button starts a separate conversation while earlier records remain on disk.

Auto uses a cheap heuristic for obvious cases. An ambiguous request gives Qwen a short first pass in which it can request thinking, additional memory, or the source excerpts for a memory reference. The harness validates the request and limits additional passes. Task state updates use a schema for objectives, constraints, findings, decisions, completed work, outstanding work and references. Thinking traces appear in the browser transcript and stay out of the SQLite working memory.

**Review answer** runs one optional reviewer pass on the same loaded model. It reads the original request, draft, related memory and saved source excerpts. File excerpts can also be passed from the original turn while it is open in the same browser tab. The reviewer starts with a 3,072-token working budget and can use the full configured window if the request and draft need it. The server's KV allocation stays fixed for the session. Review notes are saved beside the draft in SQLite, and reviewing again replaces the previous notes. A review is a second model pass, so its findings can repeat an original mistake.

Search uses the configured SearXNG instance and can run follow-up queries. The harness retains short evidence and numbered links. It gives Qwen one chance to rephrase a duplicate query and can narrow a follow-up when a source explicitly identifies a missing fact. The loop also ends when it exhausts the request budget, hits a provider failure, or runs out of time. SearXNG snippets are evidence from the search provider. Stored source reads return those excerpts and links. The harness checks citation numbers, verifies simple integer arithmetic and parses fenced Python with the standard parser. It can attempt one syntax repair within the escalation budget. It does not execute generated code or take external actions on the model's behalf.

Use **Attach file** to open a file picker or paste an absolute local Windows path. It accepts up to three UTF-8 or UTF-16 text files per message, at most 512 KiB each. The browser selects question-relevant chunks from large attachments, and the harness fits excerpts into the same token budget as the rest of the prompt. If Qwen proposes a file search, the chat shows the query and reason first. **Choose folder and allow once** gives the browser a folder to scan for that turn. **Continue without files** declines the request. The scan skips common dependency, build, and credential paths and reads up to 2,400 candidates or 24 MiB. Up to three matched excerpts go to the local model. The harness suspends web search during the file turn. Raw file contents are kept out of the SQLite archive, while any file details quoted in the answer are part of that saved answer.

## Configuration

Set variables in PowerShell before starting the launcher. For example, `$env:LOCAL_AI_DIAGNOSTICS = '1'` enables structured diagnostics. Restart the launcher to apply settings.

| Environment variable | Default | Purpose |
| --- | ---: | --- |
| `LOCAL_AI_CONTEXT` | 8192 | Context capacity passed to llama.cpp. Larger values can exceed available VRAM. |
| `LOCAL_AI_REPLY_TOKENS` | 512 | Generation budget in Quick and final-answer reserve in Think. |
| `LOCAL_AI_REVIEW_CONTEXT` | 3072 | Preferred working context for an optional reviewer pass. |
| `LOCAL_AI_REVIEW_TOKENS` | 320 | Maximum tokens generated by one reviewer pass. |
| `LOCAL_AI_THINK_TOKENS` | 640 | Runner reasoning cap. Thinking calls share the overall generation budget of reasoning plus reply tokens. |
| `LOCAL_AI_COMPACT_PERCENT` | 80 | Target utilisation of the available input budget for optional information. |
| `LOCAL_AI_SUMMARY_TOKENS` | 192 | Structured task update or legacy summary generation limit. |
| `LOCAL_AI_MAX_CALLS` | 16 | Maximum generation calls per HTTP request. |
| `LOCAL_AI_MAX_GENERATED` | 4096 | Combined generation token ceiling per HTTP request. |
| `LOCAL_AI_MAX_ESCALATIONS` | 1 | Additional reasoning, retrieval or correction passes. |
| `LOCAL_AI_ADAPTIVE` | 1 | Enable Auto routing and model-requested escalation. |
| `LOCAL_AI_RETRIEVE` | 1 | Enable automatic FTS excerpts and explicit memory/source tools. |
| `LOCAL_AI_TASK_STATE` | 1 | Enable structured task-state updates. |
| `LOCAL_AI_KV` | q8_0 | KV cache type used for keys and values. |
| `LOCAL_AI_FLASH` | on | Flash Attention option passed to llama.cpp. |
| `LOCAL_AI_PROMPT_CACHE` | 1 | Reuse prompt prefixes where the runner supports reuse. |
| `LOCAL_AI_CACHE_RAM_MIB` | 256 | Host RAM limit for retained prompt cache entries. |
| `LOCAL_AI_DIAGNOSTICS` | 0 | Emit JSON records containing timing, counts and event types. |
| `LOCAL_AI_RESEARCH_SECONDS` | 150 | Research time window. Set to 0 to use only other stop conditions. |
| `SEARXNG_URL` | http://127.0.0.1:8888 | SearXNG instance with JSON search enabled. |

The browser shows final-call context, generation speed and reasoning tokens, plus aggregate request and compaction diagnostics. Reasoning tokens are estimated with the model tokenizer if the backend omits their breakdown. Token-count requests are reused within a turn. The optional diagnostic logs omit prompt text, replies, search queries and memory contents. Higher context, reply and reasoning settings need enough room to fit together.

An 8,192-token launch was tested on the RX 570 with 28 layers offloaded and the default quantised KV cache. It handled a 4,272-token prompt successfully and used a 459 MiB GPU KV buffer. Set `$env:LOCAL_AI_CONTEXT = '8192'` before starting the launcher to use that profile. Available VRAM depends on other applications, and the reply-token setting is independent of the context size.

## Tests and benchmark

```powershell
python -E -B .\tests\test_harness.py
python -E -B .\benchmarks\benchmark_harness.py
```

Stop an existing chat server before benchmarking to free VRAM. The benchmark starts one runner on port 18080 and compares the archived harness in [benchmark-baseline.zip](../benchmarks/benchmark-baseline.zip) to the current server. Both use the same model, context, cache type, GPU split, reasoning cap and seed. Prompt caching is disabled for measurement. The baseline uses its default Think mode and the optimised chat uses its default Auto mode. This measures the complete change in defaults, including routing and archive work.

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
