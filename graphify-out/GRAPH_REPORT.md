# Graph Report - bot-0  (2026-10-28)

## Corpus Check
- 17 files · ~23,092 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 339 nodes · 582 edges · 20 communities (14 shown, 6 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 38 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `56e19e46`
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
- ._handle_callback
- _action_jira_show
- ._send_message
- ._send_tts_async
- tg_tts.py
- start_android.sh
- Hermes Agent Overview
- setup_android.sh
- .peek_outbox
- ._send_direct
- Graphify Knowledge Graph Rules
- deploy_android.ps1

## God Nodes (most connected - your core abstractions)
1. `TelegramBot` - 70 edges
2. `HermesBridge` - 41 edges
3. `MemoryStore` - 33 edges
4. `SchedulerEngine` - 27 edges
5. `ComposioMCP` - 12 edges
6. `TelegramImageTests` - 12 edges
7. `main()` - 11 edges
8. `Settings` - 11 edges
9. `hermes_bridge.py` - 10 edges
10. `_process_voice()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `_drain_outbox()` --uses--> `TelegramBot`  [INFERRED]
  android_bot.py → telegram_bot.py
- `_process_voice()` --uses--> `TelegramBot`  [INFERRED]
  android_bot.py → telegram_bot.py
- `_poll_loop()` --uses--> `TelegramBot`  [INFERRED]
  android_bot.py → telegram_bot.py
- `HermesBridge` --uses--> `Settings`  [INFERRED]
  hermes_bridge.py → config.py
- `TelegramImageTests` --uses--> `HermesBridge`  [INFERRED]
  tests/test_telegram_images.py → hermes_bridge.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **LLM Provider Failover Chain** — docs_skills_deploying_hermes_agent_router_0, docs_skills_deploying_hermes_agent_opencode_zen, docs_skills_deploying_hermes_agent_openrouter, docs_skills_deploying_hermes_agent_provider_failover [EXTRACTED 1.00]
- **Bot Startup Sequence** — docs_skills_deploying_hermes_agent_start_android_sh, docs_skills_deploying_hermes_agent_android_bot, docs_skills_deploying_hermes_agent_composio_mcp, docs_skills_deploying_hermes_agent_memorystore, docs_skills_deploying_hermes_agent_hermes_bridge, docs_skills_deploying_hermes_agent_telegram_bot, docs_skills_deploying_hermes_agent_scheduler [EXTRACTED 1.00]
- **Voice Processing Pipeline** — docs_skills_deploying_hermes_agent_tg_voice, docs_skills_deploying_hermes_agent_tg_tts, docs_skills_deploying_hermes_agent_router_0, docs_skills_deploying_hermes_agent_in_process_voice, docs_skills_deploying_hermes_agent_send_voice_direct [EXTRACTED 1.00]

## Communities (20 total, 6 thin omitted)

### Community 0 - "HermesBridge"
Cohesion: 0.07
Nodes (14): HermesBridge, Send a user message and image through the configured vision model., Temporarily switch to another configured provider after capacity exhaustion.…, Render a RetryableError/httpx error as the short user-facing message., Parse the LLM's expansion reply into a list of terms. Accepts a JSON object…, LLM query expansion: turn the message into better search terms. Reuses chat()…, Return True for trivial conversational messages that should take the fast path., Compute epoch for HH:MM today/tomorrow/next-weekday in local time. (+6 more)

### Community 1 - "MemoryStore"
Cohesion: 0.07
Nodes (9): MemoryStore, Connection, Row, No-op — remote backup removed., Add a skill. Upserts on normalized title match., LIKE-based token match on title + problem + tags. Excludes inactive., Search + increment injection_count. For injection pipeline., Adjust skill confidence based on feedback: +0.05 for positive, -0.10 for… (+1 more)

### Community 2 - "SchedulerEngine"
Cohesion: 0.09
Nodes (14): Connection, Row, Load active jobs' next_run_at into the timer map (cold-boot path)., Wake at the earliest next_run_at and spawn due jobs promptly. The 30s poll…, Create and track a fire_job task, shared by poll loop and run_now. Returns True…, Given a daily job's anchor time, return next occurrence at same HH:MM., Lightweight in-process scheduler using SQLite persistence. Runs an async poll…, Execute one job: LLM call -> send result -> update DB. When manual=True… (+6 more)

### Community 3 - "TelegramBot"
Cohesion: 0.09
Nodes (24): _action_chat_summarize(), _action_memory_cleanup(), _action_memory_clear(), _action_memory_status(), _action_memory_view(), _action_pdf_stop(), _action_schedule_add(), _action_skill_autolearn_toggle() (+16 more)

### Community 4 - "hermes_bridge.py"
Cohesion: 0.10
Nodes (31): android_bot.py, Auto-learn, composio_mcp.py, COMPOSIO_REMOTE_WORKBENCH, Confidence Scoring, config.py, Fast-path Optimization, getUpdates Polling (+23 more)

### Community 5 - "TelegramImageTests"
Cohesion: 0.11
Nodes (9): get_settings(), Settings, Exception, _is_transient_llm_error(), A provider error worth retrying (transient) that surfaced as HTTP 200 body., True if the provider error dict/str describes a transient upstream failure., RetryableError, TelegramImageTests (+1 more)

### Community 6 - "android_bot.py"
Cohesion: 0.08
Nodes (26): _drain_outbox(), _get_updates_sync(), main(), _poll_loop(), _process_voice(), Path, Hermes Agent — Android/Termux entry point (headless Telegram bot). Reuses all…, Poll getUpdates, process voice inline, feed into enqueue_update. (+18 more)

### Community 7 - "._handle_callback"
Cohesion: 0.14
Nodes (11): _action_model_switch(), _action_schedule_list(), _action_schedule_pause_by_id(), _action_schedule_remove_by_id(), _action_schedule_resume_by_id(), _action_schedule_run_by_id(), _action_tts_model_switch(), Switch TTS model for this chat. Persists to memory_store. (+3 more)

### Community 9 - "_action_jira_show"
Cohesion: 0.12
Nodes (18): _action_jira_open_tasks(), _action_jira_run(), _action_jira_show(), _action_jira_subtasks(), _adf_to_plaintext(), _call_composio(), _parse_jira_result(), _parse_jira_single() (+10 more)

### Community 11 - "._send_message"
Cohesion: 0.13
Nodes (11): extract_text_from_pdf_bytes(), is_pdf(), PDF helpers for Hermes Agent — detect, download, and extract text from Telegram…, Return True when a Telegram document is a PDF. Telegram sometimes reports…, Extract all text from a PDF. Returns "" when the PDF has no extractable text…, Trim text to `limit` chars, cutting on a word boundary., truncate(), Analyze an uploaded image, then retain it for the next user request. (+3 more)

### Community 12 - "._send_tts_async"
Cohesion: 0.33
Nodes (4): Send Opus audio as a voice message directly to Telegram API. Uses httpx…, Background task: synthesize TTS, send voice messages. Called via…, Split text at sentence boundaries, each chunk ≤ max_chars. Uses regex to split…, _split_tts_text()

### Community 13 - "tg_tts.py"
Cohesion: 0.33
Nodes (5): TTS helpers for Hermes Agent — synthesize speech via local router-0., Synthesize text to MP3 audio via router-0 TTS endpoint. Args: text: Text to…, Convert MP3 bytes to OggOpus bytes via ffmpeg (pipe). Same pattern as…, synthesize(), to_opus()

### Community 14 - "start_android.sh"
Cohesion: 0.40
Nodes (4): PATH, start_android.sh script, TEMP_DIR, WORK_DIR

## Knowledge Gaps
- **17 isolated node(s):** `setup_android.sh script`, `start_android.sh script`, `PATH`, `TEMP_DIR`, `WORK_DIR` (+12 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramBot` connect `TelegramBot` to `TelegramImageTests`, `android_bot.py`, `._handle_callback`, `_action_jira_show`, `._send_message`, `._send_tts_async`, `.peek_outbox`, `._send_direct`?**
  _High betweenness centrality (0.288) - this node is a cross-community bridge._
- **Why does `HermesBridge` connect `HermesBridge` to `TelegramImageTests`, `android_bot.py`?**
  _High betweenness centrality (0.228) - this node is a cross-community bridge._
- **Why does `MemoryStore` connect `MemoryStore` to `android_bot.py`?**
  _High betweenness centrality (0.183) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `TelegramBot` (e.g. with `_drain_outbox()` and `_poll_loop()`) actually correct?**
  _`TelegramBot` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `HermesBridge` (e.g. with `Settings` and `TelegramImageTests`) actually correct?**
  _`HermesBridge` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `setup_android.sh script`, `start_android.sh script`, `PATH` to the rest of the system?**
  _17 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `HermesBridge` be split into smaller, more focused modules?**
  _Cohesion score 0.07215541165587419 - nodes in this community are weakly interconnected._