# Graph Report - bot-0  (2026-08-09)

## Corpus Check
- 15 files · ~19,980 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 307 nodes · 556 edges · 22 communities (14 shown, 8 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 36 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ecac361b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Deploying Hermes Agent
- MemoryStore
- android_bot.py
- SchedulerEngine
- HermesBridge
- ._send_message
- _action_jira_subtasks
- TelegramBot
- ComposioMCP
- _action_jira_run
- _action_jira_show
- _action_tts_toggle
- ._send_tts_async
- tg_tts.py
- start_android.sh
- setup_android.sh
- _jira_workbench_code
- CLAUDE.md
- ._edit_message
- ._send_direct
- .peek_outbox

## God Nodes (most connected - your core abstractions)
1. `TelegramBot` - 64 edges
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

## Communities (22 total, 8 thin omitted)

### Community 0 - "Deploying Hermes Agent"
Cohesion: 0.07
Nodes (36): Deploying Hermes Agent, Architecture, Composio MCP Integration, Deployment (Clone/ADB/SSH), Edge Cases Covered, Error Recovery Patterns, Jira Integrated Menu, Learned Skills / Auto-Learn (+28 more)

### Community 1 - "MemoryStore"
Cohesion: 0.08
Nodes (8): MemoryStore, Connection, Row, No-op — remote backup removed., Add a skill. Upserts on normalized title match., LIKE-based token match on title + problem + tags. Excludes inactive., Search + increment injection_count. For injection pipeline., Return a fresh connection to the same DB (for SchedulerEngine).

### Community 2 - "android_bot.py"
Cohesion: 0.09
Nodes (31): _drain_outbox(), _get_updates_sync(), main(), _poll_loop(), _process_voice(), Path, Hermes Agent — Android/Termux entry point (headless Telegram bot). Reuses all…, Poll getUpdates, process voice inline, feed into enqueue_update. (+23 more)

### Community 3 - "SchedulerEngine"
Cohesion: 0.09
Nodes (14): Connection, Row, Load active jobs' next_run_at into the timer map (cold-boot path)., Wake at the earliest next_run_at and spawn due jobs promptly. The 30s poll…, Create and track a fire_job task, shared by poll loop and run_now. Returns True…, Given a daily job's anchor time, return next occurrence at same HH:MM., Lightweight in-process scheduler using SQLite persistence. Runs an async poll…, Execute one job: LLM call -> send result -> update DB. When manual=True… (+6 more)

### Community 4 - "HermesBridge"
Cohesion: 0.08
Nodes (11): HermesBridge, Temporarily switch to another configured provider after capacity exhaustion.…, Render a RetryableError/httpx error as the short user-facing message., Parse the LLM's expansion reply into a list of terms. Accepts a JSON object…, LLM query expansion: turn the message into better search terms. Reuses chat()…, Compute epoch for HH:MM today/tomorrow/next-weekday in local time., Convert 12-hour clock to 24-hour. ampm is 'am'/'pm' or None., Convert a matched time expression into interval_minutes or absolute_epoch. (+3 more)

### Community 5 - "._send_message"
Cohesion: 0.19
Nodes (11): _action_model_switch(), _action_schedule_list(), _action_schedule_pause_by_id(), _action_schedule_remove_by_id(), _action_schedule_resume_by_id(), _action_schedule_run_by_id(), _action_tts_model_switch(), Switch TTS model for this chat. Persists to memory_store. (+3 more)

### Community 6 - "_action_jira_subtasks"
Cohesion: 0.22
Nodes (10): _action_jira_open_tasks(), _action_jira_subtasks(), _call_composio(), _parse_jira_result(), _parse_workbench_issues(), Call a Composio tool (async, awaits directly in running loop)., Extract issues list from workbench stdout output., Parse issues from Composio workbench response. (+2 more)

### Community 7 - "TelegramBot"
Cohesion: 0.13
Nodes (18): _action_chat_summarize(), _action_memory_cleanup(), _action_memory_clear(), _action_memory_status(), _action_memory_view(), _action_schedule_add(), _action_skill_autolearn_toggle(), _action_skill_forget_inactive() (+10 more)

### Community 9 - "_action_jira_run"
Cohesion: 0.38
Nodes (3): _action_jira_run(), Fetch Jira issue description and run it as an LLM prompt., Send inline confirmation for a detected skill.

### Community 10 - "_action_jira_show"
Cohesion: 0.33
Nodes (6): _action_jira_show(), _adf_to_plaintext(), _parse_jira_single(), Parse single issue from JIRA_GET_ISSUE workbench response. Response shape:…, Convert Atlassian Document Format (ADF) JSON to plain text., Fetch and display a single Jira issue's description (read-only view).

### Community 12 - "._send_tts_async"
Cohesion: 0.33
Nodes (4): Split text at sentence boundaries, each chunk ≤ max_chars. Uses regex to split…, Send Opus audio as a voice message directly to Telegram API. Uses httpx…, Background task: synthesize TTS, send voice messages. Called via…, _split_tts_text()

### Community 13 - "tg_tts.py"
Cohesion: 0.33
Nodes (5): TTS helpers for Hermes Agent — synthesize speech via local router-0., Synthesize text to MP3 audio via router-0 TTS endpoint. Args: text: Text to…, Convert MP3 bytes to OggOpus bytes via ffmpeg (pipe). Same pattern as…, synthesize(), to_opus()

### Community 14 - "start_android.sh"
Cohesion: 0.40
Nodes (4): PATH, start_android.sh script, TEMP_DIR, WORK_DIR

## Knowledge Gaps
- **9 isolated node(s):** `setup_android.sh script`, `start_android.sh script`, `PATH`, `TEMP_DIR`, `WORK_DIR` (+4 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramBot` connect `TelegramBot` to `android_bot.py`, `._send_message`, `_action_jira_subtasks`, `_action_jira_run`, `_action_jira_show`, `_action_tts_toggle`, `._send_tts_async`, `._edit_message`, `._send_direct`, `.peek_outbox`?**
  _High betweenness centrality (0.269) - this node is a cross-community bridge._
- **Why does `HermesBridge` connect `HermesBridge` to `android_bot.py`?**
  _High betweenness centrality (0.204) - this node is a cross-community bridge._
- **Why does `SchedulerEngine` connect `SchedulerEngine` to `android_bot.py`?**
  _High betweenness centrality (0.182) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Deploying Hermes Agent` (e.g. with `README.md` and `Hermes Agent Bot 0`) actually correct?**
  _`Deploying Hermes Agent` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `setup_android.sh script`, `start_android.sh script`, `PATH` to the rest of the system?**
  _9 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Deploying Hermes Agent` be split into smaller, more focused modules?**
  _Cohesion score 0.07396870554765292 - nodes in this community are weakly interconnected._
- **Should `MemoryStore` be split into smaller, more focused modules?**
  _Cohesion score 0.08412698412698413 - nodes in this community are weakly interconnected._