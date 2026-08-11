# Graph Report - bot-0  (2026-08-11)

## Corpus Check
- 16 files · ~20,693 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 319 nodes · 584 edges · 15 communities (10 shown, 5 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 40 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9bbf2d59`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Deploying Hermes Agent
- MemoryStore
- android_bot.py
- SchedulerEngine
- HermesBridge
- TelegramBot
- ._handle_document
- tg_tts.py
- start_android.sh
- setup_android.sh
- _jira_workbench_code
- CLAUDE.md
- ._send_direct
- .peek_outbox

## God Nodes (most connected - your core abstractions)
1. `TelegramBot` - 66 edges
2. `HermesBridge` - 34 edges
3. `MemoryStore` - 30 edges
4. `SchedulerEngine` - 27 edges
5. `Deploying Hermes Agent` - 23 edges
6. `ComposioMCP` - 12 edges
7. `main()` - 11 edges
8. `Hermes Agent Bot 0` - 10 edges
9. `_process_voice()` - 9 edges
10. `_action_jira_run()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `_drain_outbox()` --references--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py
- `_process_voice()` --references--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py
- `_poll_loop()` --references--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py
- `main()` --calls--> `get_settings()`  [EXTRACTED]
  android_bot.py → config.py
- `main()` --calls--> `HermesBridge`  [EXTRACTED]
  android_bot.py → hermes_bridge.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Voice Pipeline (download -> ffmpeg -> STT transcription, and TTS synthesize -> OggOpus -> sendVoice)** — docs_skills_deploying_hermes_agent_md_voice_pipeline, docs_skills_deploying_hermes_agent_md_tts, readme_md_router_0_stt, readme_md_voice_memo_transcription [EXTRACTED 1.00]
- **Persistence Layer (SQLite facts, skills, scheduled jobs co-located)** — readme_md_sqlite_memory, docs_skills_deploying_hermes_agent_md_memory_store, docs_skills_deploying_hermes_agent_md_learned_skills, readme_md_scheduler_engine [EXTRACTED 1.00]

## Communities (15 total, 5 thin omitted)

### Community 0 - "Deploying Hermes Agent"
Cohesion: 0.07
Nodes (36): Deploying Hermes Agent, Architecture, Composio MCP Integration, Deployment (Clone/ADB/SSH), Edge Cases Covered, Error Recovery Patterns, Jira Integrated Menu, Learned Skills / Auto-Learn (+28 more)

### Community 1 - "MemoryStore"
Cohesion: 0.08
Nodes (8): MemoryStore, Connection, Row, No-op — remote backup removed., Add a skill. Upserts on normalized title match., LIKE-based token match on title + problem + tags. Excludes inactive., Search + increment injection_count. For injection pipeline., Return a fresh connection to the same DB (for SchedulerEngine).

### Community 2 - "android_bot.py"
Cohesion: 0.08
Nodes (26): _drain_outbox(), _get_updates_sync(), main(), _poll_loop(), _process_voice(), Path, Hermes Agent — Android/Termux entry point (headless Telegram bot). Reuses all…, Poll getUpdates, process voice inline, feed into enqueue_update. (+18 more)

### Community 3 - "SchedulerEngine"
Cohesion: 0.09
Nodes (14): Connection, Row, Load active jobs' next_run_at into the timer map (cold-boot path)., Wake at the earliest next_run_at and spawn due jobs promptly. The 30s poll…, Create and track a fire_job task, shared by poll loop and run_now. Returns True…, Given a daily job's anchor time, return next occurrence at same HH:MM., Lightweight in-process scheduler using SQLite persistence. Runs an async poll…, Execute one job: LLM call -> send result -> update DB. When manual=True… (+6 more)

### Community 4 - "HermesBridge"
Cohesion: 0.07
Nodes (18): get_settings(), Settings, Exception, HermesBridge, _is_transient_llm_error(), A provider error worth retrying (transient) that surfaced as HTTP 200 body., True if the provider error dict/str describes a transient upstream failure., Temporarily switch to another configured provider after capacity exhaustion.… (+10 more)

### Community 7 - "TelegramBot"
Cohesion: 0.07
Nodes (53): _action_chat_summarize(), _action_jira_open_tasks(), _action_jira_run(), _action_jira_show(), _action_jira_subtasks(), _action_memory_cleanup(), _action_memory_clear(), _action_memory_status() (+45 more)

### Community 9 - "._handle_document"
Cohesion: 0.10
Nodes (12): extract_text_from_pdf_bytes(), is_pdf(), PDF helpers for Hermes Agent — detect, download, and extract text from Telegram…, Return True when a Telegram document is a PDF. Telegram sometimes reports…, Extract all text from a PDF. Returns "" when the PDF has no extractable text…, Trim text to `limit` chars, cutting on a word boundary., truncate(), Auto-analyze an uploaded PDF: download, extract text, summarize, offer Q&A. (+4 more)

### Community 13 - "tg_tts.py"
Cohesion: 0.33
Nodes (5): TTS helpers for Hermes Agent — synthesize speech via local router-0., Synthesize text to MP3 audio via router-0 TTS endpoint. Args: text: Text to…, Convert MP3 bytes to OggOpus bytes via ffmpeg (pipe). Same pattern as…, synthesize(), to_opus()

### Community 14 - "start_android.sh"
Cohesion: 0.40
Nodes (4): PATH, start_android.sh script, TEMP_DIR, WORK_DIR

## Knowledge Gaps
- **9 isolated node(s):** `setup_android.sh script`, `start_android.sh script`, `PATH`, `TEMP_DIR`, `WORK_DIR` (+4 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramBot` connect `TelegramBot` to `._handle_document`, `android_bot.py`, `._send_direct`, `.peek_outbox`?**
  _High betweenness centrality (0.259) - this node is a cross-community bridge._
- **Why does `HermesBridge` connect `HermesBridge` to `android_bot.py`?**
  _High betweenness centrality (0.198) - this node is a cross-community bridge._
- **Why does `SchedulerEngine` connect `SchedulerEngine` to `android_bot.py`?**
  _High betweenness centrality (0.177) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Deploying Hermes Agent` (e.g. with `README.md` and `Hermes Agent Bot 0`) actually correct?**
  _`Deploying Hermes Agent` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `setup_android.sh script`, `start_android.sh script`, `PATH` to the rest of the system?**
  _9 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Deploying Hermes Agent` be split into smaller, more focused modules?**
  _Cohesion score 0.07396870554765292 - nodes in this community are weakly interconnected._
- **Should `MemoryStore` be split into smaller, more focused modules?**
  _Cohesion score 0.08412698412698413 - nodes in this community are weakly interconnected._