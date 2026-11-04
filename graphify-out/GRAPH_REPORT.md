# Graph Report - bot-0  (2026-11-04)

## Corpus Check
- 26 files · ~27,485 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 422 nodes · 727 edges · 31 communities (18 shown, 13 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 46 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `01bff99a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- HermesBridge
- MemoryStore
- SchedulerEngine
- TelegramBot
- hermes_bridge.py
- TelegramImageTests
- android_bot.py
- Settings
- .chat
- ._parse_time_expr
- architecture.md
- ._handle_document
- hermes_bridge.py
- tg_tts.py
- start_android.sh
- Hermes Agent Overview
- setup_android.sh
- backend.md
- data.md
- RetrievalBenchmarkTests
- ._handle_callback
- dependencies.md
- Graphify Knowledge Graph Rules
- deploy_android.ps1
- frontend.md
- _action_jira_show
- ._handle_message
- ._send_tts_async
- ._send_direct
- .peek_outbox

## God Nodes (most connected - your core abstractions)
1. `TelegramBot` - 75 edges
2. `HermesBridge` - 57 edges
3. `MemoryStore` - 40 edges
4. `TelegramImageTests` - 35 edges
5. `SchedulerEngine` - 27 edges
6. `Settings` - 26 edges
7. `TextFlowTests` - 13 edges
8. `ComposioMCP` - 12 edges
9. `ConfidenceEvaluatorTests` - 12 edges
10. `main()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `_drain_outbox()` --uses--> `TelegramBot`  [INFERRED]
  android_bot.py → telegram_bot.py
- `_process_voice()` --uses--> `TelegramBot`  [INFERRED]
  android_bot.py → telegram_bot.py
- `_poll_loop()` --uses--> `TelegramBot`  [INFERRED]
  android_bot.py → telegram_bot.py
- `HermesBridge` --uses--> `Settings`  [INFERRED]
  hermes_bridge.py → config.py
- `ConfidenceEvaluatorTests` --uses--> `Settings`  [INFERRED]
  tests/test_confidence_evaluator.py → config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **LLM Provider Failover Chain** — docs_skills_deploying_hermes_agent_router_0, docs_skills_deploying_hermes_agent_opencode_zen, docs_skills_deploying_hermes_agent_openrouter, docs_skills_deploying_hermes_agent_provider_failover [EXTRACTED 1.00]
- **Bot Startup Sequence** — docs_skills_deploying_hermes_agent_start_android_sh, docs_skills_deploying_hermes_agent_android_bot, docs_skills_deploying_hermes_agent_composio_mcp, docs_skills_deploying_hermes_agent_memorystore, docs_skills_deploying_hermes_agent_hermes_bridge, docs_skills_deploying_hermes_agent_telegram_bot, docs_skills_deploying_hermes_agent_scheduler [EXTRACTED 1.00]
- **Voice Processing Pipeline** — docs_skills_deploying_hermes_agent_tg_voice, docs_skills_deploying_hermes_agent_tg_tts, docs_skills_deploying_hermes_agent_router_0, docs_skills_deploying_hermes_agent_in_process_voice, docs_skills_deploying_hermes_agent_send_voice_direct [EXTRACTED 1.00]

## Communities (31 total, 13 thin omitted)

### Community 0 - "HermesBridge"
Cohesion: 0.14
Nodes (5): HermesBridge, Send a user message and image through the configured vision model., Send an ordered image batch with captions through the vision model., Temporarily switch to another configured provider after capacity exhaustion.…, Render a RetryableError/httpx error as the short user-facing message.

### Community 1 - "MemoryStore"
Cohesion: 0.06
Nodes (10): MemoryStore, Connection, Row, No-op — remote backup removed., Add a skill. Upserts on normalized title match., LIKE-based token match on title + problem + tags. Excludes inactive., Search + increment injection_count. For injection pipeline., Adjust skill confidence based on feedback: +0.05 for positive, -0.10 for… (+2 more)

### Community 2 - "SchedulerEngine"
Cohesion: 0.09
Nodes (14): Connection, Row, Load active jobs' next_run_at into the timer map (cold-boot path)., Wake at the earliest next_run_at and spawn due jobs promptly. The 30s poll…, Create and track a fire_job task, shared by poll loop and run_now. Returns True…, Given a daily job's anchor time, return next occurrence at same HH:MM., Lightweight in-process scheduler using SQLite persistence. Runs an async poll…, Execute one job: LLM call -> send result -> update DB. When manual=True… (+6 more)

### Community 3 - "TelegramBot"
Cohesion: 0.09
Nodes (26): _action_chat_summarize(), _action_memory_cleanup(), _action_memory_clear(), _action_memory_status(), _action_memory_view(), _action_pdf_stop(), _action_schedule_add(), _action_skill_autolearn_toggle() (+18 more)

### Community 4 - "hermes_bridge.py"
Cohesion: 0.10
Nodes (31): android_bot.py, Auto-learn, composio_mcp.py, COMPOSIO_REMOTE_WORKBENCH, Confidence Scoring, config.py, Fast-path Optimization, getUpdates Polling (+23 more)

### Community 6 - "android_bot.py"
Cohesion: 0.08
Nodes (27): _drain_outbox(), _get_updates_sync(), main(), _poll_loop(), _process_voice(), Path, Hermes Agent — Android/Termux entry point (headless Telegram bot). Reuses all…, Poll getUpdates, process voice inline, feed into enqueue_update. (+19 more)

### Community 7 - "Settings"
Cohesion: 0.14
Nodes (3): Settings, _MemoryStub, TextFlowTests

### Community 8 - ".chat"
Cohesion: 0.18
Nodes (4): Parse the LLM's expansion reply into a list of terms. Accepts a JSON object…, Return True for trivial conversational messages that should take the fast path., LLM query expansion: turn the message into better search terms. Reuses chat()…, Evaluate confidence score (0-1) for a fact or skill using LLM.

### Community 9 - "._parse_time_expr"
Cohesion: 0.18
Nodes (6): Compute epoch for HH:MM today/tomorrow/next-weekday in local time., Convert 12-hour clock to 24-hour. ampm is 'am'/'pm' or None., Convert a matched time expression into interval_minutes or absolute_epoch., Try to extract schedule from text using regex patterns. Returns…, Parse natural-language scheduling intent. Tries deterministic regex first,…, Match

### Community 11 - "._handle_document"
Cohesion: 0.18
Nodes (9): extract_text_from_pdf_bytes(), is_pdf(), PDF helpers for Hermes Agent — detect, download, and extract text from Telegram…, Return True when a Telegram document is a PDF. Telegram sometimes reports…, Extract all text from a PDF. Returns "" when the PDF has no extractable text…, Trim text to `limit` chars, cutting on a word boundary., truncate(), Download and append an image without triggering analysis. (+1 more)

### Community 12 - "hermes_bridge.py"
Cohesion: 0.27
Nodes (5): Exception, _is_transient_llm_error(), A provider error worth retrying (transient) that surfaced as HTTP 200 body., True if the provider error dict/str describes a transient upstream failure., RetryableError

### Community 13 - "tg_tts.py"
Cohesion: 0.33
Nodes (5): TTS helpers for Hermes Agent — synthesize speech via local router-0., Synthesize text to MP3 audio via router-0 TTS endpoint. Args: text: Text to…, Convert MP3 bytes to OggOpus bytes via ffmpeg (pipe). Same pattern as…, synthesize(), to_opus()

### Community 14 - "start_android.sh"
Cohesion: 0.40
Nodes (4): PATH, start_android.sh script, TEMP_DIR, WORK_DIR

### Community 19 - "RetrievalBenchmarkTests"
Cohesion: 0.15
Nodes (11): _cosine(), DeterministicEmbedder, evaluate_retrievers(), hybrid_retrieve(), lexical_retrieve(), Offline, synthetic benchmark for lexical and hybrid fact retrieval. The…, Tiny synonym-fixture embedder; not a learned language model., Run the existing MemoryStore lexical retrieval implementation. (+3 more)

### Community 20 - "._handle_callback"
Cohesion: 0.15
Nodes (10): _action_model_switch(), _action_schedule_list(), _action_schedule_pause_by_id(), _action_schedule_remove_by_id(), _action_schedule_resume_by_id(), _action_schedule_run_by_id(), Parse /schedule add <text>, show confirmation with Yes/No inline., Enqueue an editMessageText to the outbox. (+2 more)

### Community 26 - "_action_jira_show"
Cohesion: 0.12
Nodes (18): _action_jira_open_tasks(), _action_jira_run(), _action_jira_show(), _action_jira_subtasks(), _adf_to_plaintext(), _call_composio(), _parse_jira_result(), _parse_jira_single() (+10 more)

### Community 28 - "._send_tts_async"
Cohesion: 0.33
Nodes (4): Send Opus audio as a voice message directly to Telegram API. Uses httpx…, Background task: synthesize TTS, send voice messages. Called via…, Split text at sentence boundaries, each chunk ≤ max_chars. Uses regex to split…, _split_tts_text()

## Knowledge Gaps
- **22 isolated node(s):** `setup_android.sh script`, `start_android.sh script`, `PATH`, `TEMP_DIR`, `WORK_DIR` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramBot` connect `TelegramBot` to `TelegramImageTests`, `android_bot.py`, `Settings`, `._handle_document`, `hermes_bridge.py`, `._handle_callback`, `_action_jira_show`, `._handle_message`, `._send_tts_async`, `._send_direct`, `.peek_outbox`?**
  _High betweenness centrality (0.275) - this node is a cross-community bridge._
- **Why does `HermesBridge` connect `HermesBridge` to `MemoryStore`, `TelegramImageTests`, `android_bot.py`, `Settings`, `.chat`, `._parse_time_expr`, `hermes_bridge.py`?**
  _High betweenness centrality (0.240) - this node is a cross-community bridge._
- **Why does `MemoryStore` connect `MemoryStore` to `RetrievalBenchmarkTests`, `hermes_bridge.py`, `android_bot.py`?**
  _High betweenness centrality (0.217) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `TelegramBot` (e.g. with `_drain_outbox()` and `_poll_loop()`) actually correct?**
  _`TelegramBot` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `HermesBridge` (e.g. with `Settings` and `ConfidenceEvaluatorTests`) actually correct?**
  _`HermesBridge` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `MemoryStore` (e.g. with `ConfidenceEvaluatorTests` and `RetrievalBenchmarkTests`) actually correct?**
  _`MemoryStore` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramImageTests` (e.g. with `Settings` and `HermesBridge`) actually correct?**
  _`TelegramImageTests` has 3 INFERRED edges - model-reasoned connections that need verification._