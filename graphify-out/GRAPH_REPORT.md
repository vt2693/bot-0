# Graph Report - .  (2026-08-16)

## Corpus Check
- 1 files · ~21,590 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 285 nodes · 536 edges · 20 communities (16 shown, 4 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 28 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Hermes Bridge Core & LLM Failover
- Scheduler Engine & Job Dispatching
- Memory Store & Skill Registry
- Android Bot & Voice Processing
- Telegram Bot Actions & System Handlers
- Telegram Bot Callback & Menu System
- Telegram Bot Core & Queue Worker
- Composio MCP Integration
- PDF Document Handler
- Jira Integration & Workbench Parser
- Message Routing & Typing Refresher
- Jira ADF Text Parser
- TTS Audio Handler
- Text-to-Speech Opus Synthesis
- Start Android Script
- Project Documentation
- Setup Android Script
- Jira Workbench Code
- Graphify Rules

## God Nodes (most connected - your core abstractions)
1. `TelegramBot` - 66 edges
2. `HermesBridge` - 35 edges
3. `MemoryStore` - 30 edges
4. `SchedulerEngine` - 27 edges
5. `ComposioMCP` - 12 edges
6. `main()` - 11 edges
7. `_process_voice()` - 9 edges
8. `_action_jira_run()` - 9 edges
9. `Settings` - 8 edges
10. `_action_jira_show()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `HermesBridge` --uses--> `Settings`  [INFERRED]
  hermes_bridge.py → config.py
- `_drain_outbox()` --references--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py
- `_process_voice()` --references--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py
- `_poll_loop()` --references--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py
- `main()` --calls--> `ComposioMCP`  [EXTRACTED]
  android_bot.py → composio_mcp.py

## Import Cycles
- None detected.

## Communities (20 total, 4 thin omitted)

### Community 0 - "Hermes Bridge Core & LLM Failover"
Cohesion: 0.07
Nodes (14): HermesBridge, _is_transient_llm_error(), True if the provider error dict/str describes a transient upstream failure., Temporarily switch to another configured provider after capacity exhaustion.…, Render a RetryableError/httpx error as the short user-facing message., Parse the LLM's expansion reply into a list of terms. Accepts a JSON object…, LLM query expansion: turn the message into better search terms. Reuses chat()…, Return True for trivial conversational messages that should take the fast path. (+6 more)

### Community 1 - "Scheduler Engine & Job Dispatching"
Cohesion: 0.09
Nodes (14): Connection, Row, Load active jobs' next_run_at into the timer map (cold-boot path)., Wake at the earliest next_run_at and spawn due jobs promptly. The 30s poll…, Create and track a fire_job task, shared by poll loop and run_now. Returns True…, Given a daily job's anchor time, return next occurrence at same HH:MM., Lightweight in-process scheduler using SQLite persistence. Runs an async poll…, Execute one job: LLM call -> send result -> update DB. When manual=True… (+6 more)

### Community 2 - "Memory Store & Skill Registry"
Cohesion: 0.08
Nodes (8): MemoryStore, Connection, Row, No-op — remote backup removed., Add a skill. Upserts on normalized title match., LIKE-based token match on title + problem + tags. Excludes inactive., Search + increment injection_count. For injection pipeline., Return a fresh connection to the same DB (for SchedulerEngine).

### Community 3 - "Android Bot & Voice Processing"
Cohesion: 0.10
Nodes (29): _drain_outbox(), _get_updates_sync(), main(), _poll_loop(), _process_voice(), Path, Hermes Agent — Android/Termux entry point (headless Telegram bot). Reuses all…, Poll getUpdates, process voice inline, feed into enqueue_update. (+21 more)

### Community 4 - "Telegram Bot Actions & System Handlers"
Cohesion: 0.17
Nodes (21): _action_chat_summarize(), _action_memory_cleanup(), _action_memory_clear(), _action_memory_status(), _action_memory_view(), _action_pdf_stop(), _action_schedule_add(), _action_skill_autolearn_toggle() (+13 more)

### Community 5 - "Telegram Bot Callback & Menu System"
Cohesion: 0.15
Nodes (10): _action_model_switch(), _action_schedule_list(), _action_schedule_pause_by_id(), _action_schedule_remove_by_id(), _action_schedule_resume_by_id(), _action_schedule_run_by_id(), _action_tts_model_switch(), Switch TTS model for this chat. Persists to memory_store. (+2 more)

### Community 6 - "Telegram Bot Core & Queue Worker"
Cohesion: 0.14
Nodes (4): Return outbox items without draining (for diagnostics)., Enqueue an editMessageText to the outbox., Try calling api.telegram.org directly. Returns True if sent., TelegramBot

### Community 8 - "PDF Document Handler"
Cohesion: 0.24
Nodes (8): extract_text_from_pdf_bytes(), is_pdf(), PDF helpers for Hermes Agent — detect, download, and extract text from Telegram…, Return True when a Telegram document is a PDF. Telegram sometimes reports…, Extract all text from a PDF. Returns "" when the PDF has no extractable text…, Trim text to `limit` chars, cutting on a word boundary., truncate(), Auto-analyze an uploaded PDF: download, extract text, summarize, offer Q&A.

### Community 9 - "Jira Integration & Workbench Parser"
Cohesion: 0.22
Nodes (10): _action_jira_open_tasks(), _action_jira_subtasks(), _call_composio(), _parse_jira_result(), _parse_workbench_issues(), Call a Composio tool (async, awaits directly in running loop)., Extract issues list from workbench stdout output., Parse issues from Composio workbench response. (+2 more)

### Community 10 - "Message Routing & Typing Refresher"
Cohesion: 0.28
Nodes (4): _action_jira_run(), Fetch Jira issue description and run it as an LLM prompt., Send inline confirmation for a detected skill., Parse /schedule add <text>, show confirmation with Yes/No inline.

### Community 11 - "Jira ADF Text Parser"
Cohesion: 0.33
Nodes (6): _action_jira_show(), _adf_to_plaintext(), _parse_jira_single(), Parse single issue from JIRA_GET_ISSUE workbench response. Response shape:…, Convert Atlassian Document Format (ADF) JSON to plain text., Fetch and display a single Jira issue's description (read-only view).

### Community 12 - "TTS Audio Handler"
Cohesion: 0.33
Nodes (4): Split text at sentence boundaries, each chunk ≤ max_chars. Uses regex to split…, Send Opus audio as a voice message directly to Telegram API. Uses httpx…, Background task: synthesize TTS, send voice messages. Called via…, _split_tts_text()

### Community 13 - "Text-to-Speech Opus Synthesis"
Cohesion: 0.33
Nodes (5): TTS helpers for Hermes Agent — synthesize speech via local router-0., Synthesize text to MP3 audio via router-0 TTS endpoint. Args: text: Text to…, Convert MP3 bytes to OggOpus bytes via ffmpeg (pipe). Same pattern as…, synthesize(), to_opus()

### Community 14 - "Start Android Script"
Cohesion: 0.40
Nodes (4): PATH, start_android.sh script, TEMP_DIR, WORK_DIR

### Community 15 - "Project Documentation"
Cohesion: 0.67
Nodes (3): Deploying Hermes Agent Guide, Hermes Agent Overview, Project Dependencies

## Knowledge Gaps
- **8 isolated node(s):** `setup_android.sh script`, `start_android.sh script`, `PATH`, `TEMP_DIR`, `WORK_DIR` (+3 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramBot` connect `Telegram Bot Core & Queue Worker` to `Android Bot & Voice Processing`, `Telegram Bot Actions & System Handlers`, `Telegram Bot Callback & Menu System`, `PDF Document Handler`, `Jira Integration & Workbench Parser`, `Message Routing & Typing Refresher`, `Jira ADF Text Parser`, `TTS Audio Handler`?**
  _High betweenness centrality (0.329) - this node is a cross-community bridge._
- **Why does `HermesBridge` connect `Hermes Bridge Core & LLM Failover` to `Android Bot & Voice Processing`?**
  _High betweenness centrality (0.262) - this node is a cross-community bridge._
- **Why does `SchedulerEngine` connect `Scheduler Engine & Job Dispatching` to `Android Bot & Voice Processing`?**
  _High betweenness centrality (0.224) - this node is a cross-community bridge._
- **What connects `setup_android.sh script`, `start_android.sh script`, `PATH` to the rest of the system?**
  _8 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Hermes Bridge Core & LLM Failover` be split into smaller, more focused modules?**
  _Cohesion score 0.07474747474747474 - nodes in this community are weakly interconnected._
- **Should `Scheduler Engine & Job Dispatching` be split into smaller, more focused modules?**
  _Cohesion score 0.08819345661450925 - nodes in this community are weakly interconnected._
- **Should `Memory Store & Skill Registry` be split into smaller, more focused modules?**
  _Cohesion score 0.08412698412698413 - nodes in this community are weakly interconnected._