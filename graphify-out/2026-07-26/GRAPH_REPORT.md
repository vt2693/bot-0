# Graph Report - bot-0  (2026-07-26)

## Corpus Check
- 15 files · ~17,487 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 273 nodes · 491 edges · 21 communities (13 shown, 8 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 35 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `652e87d0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Documentation & README
- Memory Store
- Android Bot Core
- Scheduler Engine
- Hermes Bridge LLM
- Telegram Bot Actions
- Telegram Bot Callbacks & Commands
- Telegram Bot Lifecycle & Queue
- Composio MCP
- Jira Operations
- Message Handling
- Jira Parsing
- TTS Voice Output
- TTS Synthesis
- Startup Script
- Setup Script
- Jira Workbench
- CLAUDE.md
- ._send_direct
- .peek_outbox

## God Nodes (most connected - your core abstractions)
1. `TelegramBot` - 63 edges
2. `MemoryStore` - 30 edges
3. `HermesBridge` - 26 edges
4. `Deploying Hermes Agent` - 23 edges
5. `SchedulerEngine` - 20 edges
6. `ComposioMCP` - 12 edges
7. `main()` - 11 edges
8. `Hermes Agent Bot 0` - 10 edges
9. `_process_voice()` - 9 edges
10. `_action_jira_run()` - 9 edges

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

## Hyperedges (group relationships)
- **Voice Pipeline (download -> ffmpeg -> STT transcription, and TTS synthesize -> OggOpus -> sendVoice)** — docs_skills_deploying_hermes_agent_md_voice_pipeline, docs_skills_deploying_hermes_agent_md_tts, readme_md_router_0_stt, readme_md_voice_memo_transcription [EXTRACTED 1.00]
- **Persistence Layer (SQLite facts, skills, scheduled jobs co-located)** — readme_md_sqlite_memory, docs_skills_deploying_hermes_agent_md_memory_store, docs_skills_deploying_hermes_agent_md_learned_skills, readme_md_scheduler_engine [EXTRACTED 1.00]

## Communities (21 total, 8 thin omitted)

### Community 0 - "Documentation & README"
Cohesion: 0.07
Nodes (36): Deploying Hermes Agent, Architecture, Composio MCP Integration, Deployment (Clone/ADB/SSH), Edge Cases Covered, Error Recovery Patterns, Jira Integrated Menu, Learned Skills / Auto-Learn (+28 more)

### Community 1 - "Memory Store"
Cohesion: 0.08
Nodes (8): MemoryStore, Connection, Row, No-op — remote backup removed., Add a skill. Upserts on normalized title match., LIKE-based token match on title + problem + tags. Excludes inactive., Search + increment injection_count. For injection pipeline., Return a fresh connection to the same DB (for SchedulerEngine).

### Community 2 - "Android Bot Core"
Cohesion: 0.11
Nodes (26): _drain_outbox(), _get_updates_sync(), main(), _poll_loop(), _process_voice(), Path, Hermes Agent — Android/Termux entry point (headless Telegram bot).  Reuses all, Poll getUpdates, process voice inline, feed into enqueue_update. (+18 more)

### Community 3 - "Scheduler Engine"
Cohesion: 0.11
Nodes (9): Connection, Row, Execute one job: LLM call -> send result -> update DB., Recompute next_run for jobs that fired while we were offline.          If a jo, Lightweight in-process scheduler using SQLite persistence.      Runs an async, Create a new scheduled job. Returns {'success': True, 'id': ...} or {'error': .., Open DB conn, catch up missed jobs, begin poll loop., Shut down poll loop and cancel any in-flight job executions. (+1 more)

### Community 4 - "Hermes Bridge LLM"
Cohesion: 0.14
Nodes (3): HermesBridge, Two-tier detection. Tier 1: heuristic. Tier 2: LLM extraction.         Returns, Parse natural-language scheduling intent via constrained LLM call.          Re

### Community 5 - "Telegram Bot Actions"
Cohesion: 0.18
Nodes (20): _action_chat_summarize(), _action_memory_clear(), _action_memory_status(), _action_memory_view(), _action_schedule_add(), _action_skill_autolearn_toggle(), _action_skill_forget_inactive(), _action_skill_list() (+12 more)

### Community 6 - "Telegram Bot Callbacks & Commands"
Cohesion: 0.14
Nodes (10): _action_model_switch(), _action_schedule_list(), _action_schedule_pause_by_id(), _action_schedule_remove_by_id(), _action_schedule_resume_by_id(), _action_tts_model_switch(), Switch TTS model for this chat. Persists to memory_store., Enqueue an editMessageText to the outbox. (+2 more)

### Community 9 - "Jira Operations"
Cohesion: 0.22
Nodes (10): _action_jira_open_tasks(), _action_jira_subtasks(), _call_composio(), _parse_jira_result(), _parse_workbench_issues(), Call a Composio tool (async, awaits directly in running loop)., Extract issues list from workbench stdout output., Parse issues from Composio workbench response. (+2 more)

### Community 10 - "Message Handling"
Cohesion: 0.28
Nodes (4): _action_jira_run(), Fetch Jira issue description and run it as an LLM prompt., Send inline confirmation for a detected skill., Parse /schedule add <text>, show confirmation with Yes/No inline.

### Community 11 - "Jira Parsing"
Cohesion: 0.33
Nodes (6): _action_jira_show(), _adf_to_plaintext(), _parse_jira_single(), Parse single issue from JIRA_GET_ISSUE workbench response.      Response shape, Convert Atlassian Document Format (ADF) JSON to plain text., Fetch and display a single Jira issue's description (read-only view).

### Community 13 - "TTS Synthesis"
Cohesion: 0.33
Nodes (5): TTS helpers for Hermes Agent — synthesize speech via local router-0., Synthesize text to MP3 audio via router-0 TTS endpoint.      Args:         text:, Convert MP3 bytes to OggOpus bytes via ffmpeg (pipe).      Same pattern as tg_vo, synthesize(), to_opus()

### Community 14 - "Startup Script"
Cohesion: 0.40
Nodes (4): PATH, start_android.sh script, TEMP_DIR, WORK_DIR

## Knowledge Gaps
- **9 isolated node(s):** `setup_android.sh script`, `start_android.sh script`, `PATH`, `TEMP_DIR`, `WORK_DIR` (+4 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramBot` connect `Telegram Bot Lifecycle & Queue` to `Android Bot Core`, `Telegram Bot Actions`, `Telegram Bot Callbacks & Commands`, `Jira Operations`, `Message Handling`, `Jira Parsing`, `TTS Voice Output`, `._send_direct`, `.peek_outbox`?**
  _High betweenness centrality (0.283) - this node is a cross-community bridge._
- **Why does `MemoryStore` connect `Memory Store` to `Android Bot Core`?**
  _High betweenness centrality (0.189) - this node is a cross-community bridge._
- **Why does `main()` connect `Android Bot Core` to `Memory Store`, `Scheduler Engine`, `Hermes Bridge LLM`, `Telegram Bot Lifecycle & Queue`, `Composio MCP`?**
  _High betweenness centrality (0.146) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Deploying Hermes Agent` (e.g. with `README.md` and `Hermes Agent Bot 0`) actually correct?**
  _`Deploying Hermes Agent` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `setup_android.sh script`, `start_android.sh script`, `PATH` to the rest of the system?**
  _9 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Documentation & README` be split into smaller, more focused modules?**
  _Cohesion score 0.07396870554765292 - nodes in this community are weakly interconnected._
- **Should `Memory Store` be split into smaller, more focused modules?**
  _Cohesion score 0.08412698412698413 - nodes in this community are weakly interconnected._