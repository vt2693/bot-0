# Graph Report - bot-0  (2026-08-31)

## Corpus Check
- 17 files · ~21,590 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 321 nodes · 568 edges · 25 communities (11 shown, 14 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 26 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- For Workbench Composio
- The Provider Error
- Telegram Py To
- Job Poll Jobs
- Add Search Connection
- Py Auto Learn
- Py Composiomcp Close
- Split Uses To
- Synthesize Via Text
- Sh Path Script
- Py Http Json
- Hermes Agent Overview
- Sh Script
- Wrap Python Code
- Return Outbox Items
- Try Calling Api
- Graphify Knowledge Graph
- Community 18
- Hermes Tokens Env
- Dispatch
- Requirements Txt
- Sh
- Sh
- Community 24

## God Nodes (most connected - your core abstractions)
1. `TelegramBot` - 66 edges
2. `HermesBridge` - 34 edges
3. `MemoryStore` - 30 edges
4. `SchedulerEngine` - 27 edges
5. `ComposioMCP` - 12 edges
6. `main()` - 11 edges
7. `_process_voice()` - 9 edges
8. `_action_jira_run()` - 9 edges
9. `_action_jira_show()` - 8 edges
10. `android_bot.py` - 8 edges

## Surprising Connections (you probably didn't know these)
- `_drain_outbox()` --references--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py
- `_process_voice()` --references--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py
- `_poll_loop()` --references--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py
- `main()` --calls--> `ComposioMCP`  [EXTRACTED]
  android_bot.py → composio_mcp.py
- `main()` --calls--> `HermesBridge`  [EXTRACTED]
  android_bot.py → hermes_bridge.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Core Bot Components** — docs_skills_deploying-hermes-agent_android_bot_py, docs_skills_deploying-hermes-agent_telegrambot, docs_skills_deploying-hermes-agent_hermesbridge, docs_skills_deploying-hermes-agent_config_py, docs_skills_deploying-hermes-agent_memorystore, docs_skills_deploying-hermes-agent_scheduler_py, docs_skills_deploying-hermes-agent_composio_mcp_py [INFERRED 0.95]
- **Voice Subsystem** — docs_skills_deploying-hermes-agent_tg_voice_py, docs_skills_deploying-hermes-agent_tg_tts_py, docs_skills_deploying-hermes-agent_router0, docs_skills_deploying-hermes-agent_tts_toggle [INFERRED 0.95]
- **Scheduler Subsystem** — docs_skills_deploying-hermes-agent_scheduler_py, docs_skills_deploying-hermes-agent_schedulerengine, docs_skills_deploying-hermes-agent_event_driven_dispatch, docs_skills_deploying-hermes-agent_sqlite_store [INFERRED 0.95]

## Communities (25 total, 14 thin omitted)

### Community 0 - "For Workbench Composio"
Cohesion: 0.06
Nodes (53): _action_chat_summarize(), _action_jira_open_tasks(), _action_jira_run(), _action_jira_show(), _action_jira_subtasks(), _action_memory_cleanup(), _action_memory_clear(), _action_memory_status() (+45 more)

### Community 1 - "The Provider Error"
Cohesion: 0.07
Nodes (18): Exception, HermesBridge, _is_transient_llm_error(), A provider error worth retrying (transient) that surfaced as HTTP 200 body., True if the provider error dict/str describes a transient upstream failure., Temporarily switch to another configured provider after capacity exhaustion.…, Render a RetryableError/httpx error as the short user-facing message., Parse the LLM's expansion reply into a list of terms. Accepts a JSON object… (+10 more)

### Community 2 - "Telegram Py To"
Cohesion: 0.08
Nodes (34): _drain_outbox(), _get_updates_sync(), main(), _poll_loop(), _process_voice(), Path, Hermes Agent — Android/Termux entry point (headless Telegram bot). Reuses all…, Poll getUpdates, process voice inline, feed into enqueue_update. (+26 more)

### Community 3 - "Job Poll Jobs"
Cohesion: 0.09
Nodes (14): Connection, Row, Load active jobs' next_run_at into the timer map (cold-boot path)., Wake at the earliest next_run_at and spawn due jobs promptly. The 30s poll…, Create and track a fire_job task, shared by poll loop and run_now. Returns True…, Given a daily job's anchor time, return next occurrence at same HH:MM., Lightweight in-process scheduler using SQLite persistence. Runs an async poll…, Execute one job: LLM call -> send result -> update DB. When manual=True… (+6 more)

### Community 4 - "Add Search Connection"
Cohesion: 0.08
Nodes (8): MemoryStore, Connection, Row, No-op — remote backup removed., Add a skill. Upserts on normalized title match., LIKE-based token match on title + problem + tags. Excludes inactive., Search + increment injection_count. For injection pipeline., Return a fresh connection to the same DB (for SchedulerEngine).

### Community 5 - "Py Auto Learn"
Cohesion: 0.11
Nodes (26): android_bot.py, Auto-learn, ComposioMCP, config.py, Event-driven dispatch, getUpdates polling, HermesBridge, Inline keyboard menus (+18 more)

### Community 7 - "Split Uses To"
Cohesion: 0.33
Nodes (4): Split text at sentence boundaries, each chunk ≤ max_chars. Uses regex to split…, Send Opus audio as a voice message directly to Telegram API. Uses httpx…, Background task: synthesize TTS, send voice messages. Called via…, _split_tts_text()

### Community 8 - "Synthesize Via Text"
Cohesion: 0.33
Nodes (5): TTS helpers for Hermes Agent — synthesize speech via local router-0., Synthesize text to MP3 audio via router-0 TTS endpoint. Args: text: Text to…, Convert MP3 bytes to OggOpus bytes via ffmpeg (pipe). Same pattern as…, synthesize(), to_opus()

### Community 9 - "Sh Path Script"
Cohesion: 0.40
Nodes (4): PATH, start_android.sh script, TEMP_DIR, WORK_DIR

### Community 10 - "Py Http Json"
Cohesion: 0.67
Nodes (3): composio_mcp.py, COMPOSIO_REMOTE_WORKBENCH, HTTP JSON-RPC

## Knowledge Gaps
- **26 isolated node(s):** `setup_android.sh script`, `start_android.sh script`, `PATH`, `TEMP_DIR`, `WORK_DIR` (+21 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramBot` connect `For Workbench Composio` to `Telegram Py To`, `Split Uses To`, `Return Outbox Items`, `Try Calling Api`?**
  _High betweenness centrality (0.260) - this node is a cross-community bridge._
- **Why does `HermesBridge` connect `The Provider Error` to `Telegram Py To`?**
  _High betweenness centrality (0.208) - this node is a cross-community bridge._
- **Why does `SchedulerEngine` connect `Job Poll Jobs` to `Telegram Py To`?**
  _High betweenness centrality (0.177) - this node is a cross-community bridge._
- **What connects `setup_android.sh script`, `start_android.sh script`, `PATH` to the rest of the system?**
  _26 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `For Workbench Composio` be split into smaller, more focused modules?**
  _Cohesion score 0.06491398896462187 - nodes in this community are weakly interconnected._
- **Should `The Provider Error` be split into smaller, more focused modules?**
  _Cohesion score 0.0653061224489796 - nodes in this community are weakly interconnected._
- **Should `Telegram Py To` be split into smaller, more focused modules?**
  _Cohesion score 0.07549361207897794 - nodes in this community are weakly interconnected._