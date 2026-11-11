# Graph Report - bot-0  (2026-11-11)

## Corpus Check
- 16 files · ~22,063 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 3 file(s) not represented in the graph (top: (none) 2, .example 1)

## Summary
- 337 nodes · 658 edges · 24 communities (7 shown, 17 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 79 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5fbb22ef`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- For Workbench Composio
- The Provider Error
- _poll_loop
- Job Poll Jobs
- Add Search Connection
- android_bot.py
- Py Composiomcp Close
- Split Uses To
- pdf_doc.py
- Sh Path Script
- Hermes Agent Overview
- Sh Script
- Graphify Knowledge Graph
- Hermes Tokens Env
- Dispatch
- Requirements Txt
- TELEGRAM_PATHS

## God Nodes (most connected - your core abstractions)
1. `TelegramBot` - 66 edges
2. `HermesBridge` - 36 edges
3. `MemoryStore` - 33 edges
4. `SchedulerEngine` - 27 edges
5. `main()` - 26 edges
6. `ComposioMCP` - 12 edges
7. `_action_jira_run()` - 11 edges
8. `_action_jira_show()` - 10 edges
9. `_poll_loop()` - 10 edges
10. `_process_voice()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `_drain_outbox()` --uses--> `TelegramBot`  [INFERRED]
  android_bot.py → telegram_bot.py
- `_poll_loop()` --uses--> `TelegramBot`  [INFERRED]
  android_bot.py → telegram_bot.py
- `_process_voice()` --uses--> `TelegramBot`  [INFERRED]
  android_bot.py → telegram_bot.py
- `main()` --calls--> `SchedulerEngine`  [EXTRACTED]
  android_bot.py → scheduler.py
- `main()` --calls--> `TelegramBot`  [EXTRACTED]
  android_bot.py → telegram_bot.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Core Bot Components** — android_bot, docs_skills_deploying-hermes-agent_telegrambot, docs_skills_deploying-hermes-agent_hermesbridge, config, docs_skills_deploying-hermes-agent_memorystore, scheduler, composio_mcp [INFERRED 0.95]
- **Scheduler Subsystem** — scheduler, docs_skills_deploying-hermes-agent_schedulerengine, docs_skills_deploying-hermes-agent_event_driven_dispatch, docs_skills_deploying-hermes-agent_sqlite_store [INFERRED 0.95]
- **Voice Subsystem** — tg_voice, tg_tts, docs_skills_deploying-hermes-agent_router0, docs_skills_deploying-hermes-agent_tts_toggle [INFERRED 0.95]

## Communities (24 total, 17 thin omitted)

### Community 0 - "For Workbench Composio"
Cohesion: 0.07
Nodes (32): _action_chat_summarize(), _action_jira_run(), _action_jira_show(), _action_memory_cleanup(), _action_memory_clear(), _action_memory_status(), _action_memory_view(), _action_model_switch() (+24 more)

### Community 1 - "The Provider Error"
Cohesion: 0.06
Nodes (5): get_settings(), Settings, HermesBridge, _is_transient_llm_error(), RetryableError

### Community 2 - "_poll_loop"
Cohesion: 0.10
Nodes (11): _poll_loop(), _process_voice(), Router-0, TTS toggle, synthesize(), to_opus(), download_file(), multipart_transcribe() (+3 more)

### Community 5 - "android_bot.py"
Cohesion: 0.07
Nodes (22): _drain_outbox(), _get_updates_sync(), Auto-learn, ComposioMCP, getUpdates polling, HermesBridge, Inline keyboard menus, Learned skills (+14 more)

### Community 6 - "Py Composiomcp Close"
Cohesion: 0.10
Nodes (4): main(), ComposioMCP, COMPOSIO_REMOTE_WORKBENCH, HTTP JSON-RPC

### Community 8 - "pdf_doc.py"
Cohesion: 0.22
Nodes (4): PDF auto-analyze, extract_text_from_pdf_bytes(), is_pdf(), truncate()

### Community 9 - "Sh Path Script"
Cohesion: 0.40
Nodes (4): PATH, start_android.sh script, TEMP_DIR, WORK_DIR

## Knowledge Gaps
- **21 isolated node(s):** `PATH`, `TEMP_DIR`, `WORK_DIR`, `Hermes Agent Overview`, `Project Dependencies` (+16 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 125 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramBot` connect `For Workbench Composio` to `_poll_loop`, `android_bot.py`, `Py Composiomcp Close`, `Split Uses To`?**
  _High betweenness centrality (0.216) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `TelegramBot` (e.g. with `_drain_outbox()` and `_poll_loop()`) actually correct?**
  _`TelegramBot` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `PATH`, `TEMP_DIR`, `WORK_DIR` to the rest of the system?**
  _21 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `For Workbench Composio` be split into smaller, more focused modules?**
  _Cohesion score 0.06773211567732115 - nodes in this community are weakly interconnected._
- **Why does `HermesBridge` connect `The Provider Error` to `android_bot.py`, `Py Composiomcp Close`?**
  _High betweenness centrality (0.206) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `main()` (e.g. with `.close()` and `.initialize_async()`) actually correct?**
  _`main()` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Should `The Provider Error` be split into smaller, more focused modules?**
  _Cohesion score 0.062409288824383166 - nodes in this community are weakly interconnected._