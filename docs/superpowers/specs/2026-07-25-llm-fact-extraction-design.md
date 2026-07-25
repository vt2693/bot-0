# LLM-Based Fact Extraction — Design Spec

**Date:** 2026-07-25
**Status:** Draft
**Drivers:** Replace regex-based fact extraction with LLM extraction via inline tool call.

## Problem

Current `_extract_facts()` / `_scan_for_facts()` in `hermes_bridge.py` uses hardcoded regex patterns to detect facts from conversation:

- Explicit triggers: "remember", "save", "note", "don't forget"
- Implicit patterns: "my name is", "I like/enjoy/hate", "I work at/for", "I live in", "I am a", "my email/phone/address/website is"

This misses natural language facts that don't match these patterns, produces false positives when patterns match incidentally, and is difficult to extend.

## Solution

Replace regex extraction with an `extract_facts` **tool/function call** registered alongside composio tools on the main LLM call. The model decides when to call it based on the conversation — structured JSON output, same round trip when no facts are found.

**Latency note:** When `extract_facts` is called, the existing tool loop re-enters the LLM for a second round (tool result → final response). This adds ~200-500ms when facts are extracted. When the model produces a response without the tool call, there is zero additional latency (same as today).

## Architecture

### Before (current flow)

```
User message
  → MemoryStore.get_relevant() → inject [USER FACTS] into prompt
  → chat() → _call_llm() → LLM response
  → _extract_facts(message, response, scope)     ← regex scan (blocking)
      → _scan_for_facts(text, scope)              ← regex patterns
```

### After (new flow)

```
User message
  → MemoryStore.get_relevant() → inject [USER FACTS] into prompt
  → chat(enable_extraction=True) → _call_llm(... tools=[..., extract_facts])
      → LLM round 1: returns content + tool_call (extract_facts)  ← both in one response
      → tool result appended to messages
      → LLM round 2: returns final text response                  ← extra round-trip
      → _execute_tool("extract_facts", args, scope)
          → MemoryStore.add() each new fact
  → return response (from round 2 when facts extracted, round 1 otherwise)
```

## Changes

### 1. Tool Definition — `hermes_bridge.py`

Add `_build_extract_tool()` method returning the OpenAI tool schema. Called from a modified `_get_tools()` that accepts an `enable_extraction` flag (see Section 3 for why):

```python
def _get_tools(self, enable_extraction: bool = False) -> list[dict]:
    tools = []
    if self._composio and self._composio.status().get("ready"):
        tools.extend(self._composio.get_openai_tools())
    if enable_extraction and self.settings.MEMORY_AUTO_EXTRACT:
        tools.append(self._build_extract_tool())
    return tools
```

Tool schema:

| Property | Value |
|---|---|
| `name` | `extract_facts` |
| `description` | "Extract fact-worthy information about the user from the conversation. Call this whenever the user shares personal info, preferences, or facts worth remembering." |
| `parameters.properties.facts` | array of `{content: string, category: "bio"|"preference"|"fact"|"context"}` |
| `required` | `["facts"]` |

### 2. Tool Handler — `hermes_bridge.py`

```python
def _execute_tool(self, name: str, args: dict, scope: str = "global") -> str:
    if name == "extract_facts":
        return self._handle_extract_facts(args, scope)
    # Existing composio tool handling
    try:
        if self._composio:
            return json.dumps(self._composio.call_tool_sync(name, args), default=str)
    except Exception as e:
        return f"Tool {name} failed: {e}"
    return f"Unknown tool: {name}"

def _handle_extract_facts(self, args: dict, scope: str) -> str:
    if not self.memory_store:
        return json.dumps({"stored": 0, "error": "no memory store"})
    new_count = 0
    for fact in args.get("facts", []):
        content = fact.get("content", "").strip()[:1000]
        if not content:
            continue
        existing = self.memory_store.search(content, scope, 3)
        if any(e["content"].strip().lower() == content.lower() for e in existing):
            continue
        metadata = {"category": fact.get("category", "fact"), "source": "llm_extraction"}
        self.memory_store.add(content, scope, metadata)
        self._memory_stats["extractions"] += 1
        new_count += 1
    return json.dumps({"stored": new_count})
```

### 3. Scope Threading

Add `scope` and `enable_extraction` parameters through the call chain:

| Method | New Signature |
|---|---|
| `chat()` | `(message, history, memory_context, injected_skills, scope="global", enable_extraction=False)` |
| `_call_llm()` | `(message, history, memory_context, injected_skills, scope="global", enable_extraction=False)` |
| `_execute_tool()` | `(name, args, scope="global")` |

`chat_with_memory()` passes its `scope` var through and enables extraction:

```python
response = self.chat(message, history or [], mem_block, injected_skills, scope=scope, enable_extraction=True)
```

`_get_tools()` checks `enable_extraction` before registering the tool:

```python
def _get_tools(self, enable_extraction: bool = False) -> list[dict]:
    tools = []
    if self._composio and self._composio.status().get("ready"):
        tools.extend(self._composio.get_openai_tools())
    if enable_extraction and self.settings.MEMORY_AUTO_EXTRACT:
        tools.append(self._build_extract_tool())
    return tools
```

**Why `enable_extraction` instead of relying on scope default?** Internal callers — `_detect_skill` (line 318), `parse_schedule` (line 358), `generate_minutes` (line 365) — call `self.chat()` with internal prompts that include user message snippets. If `extract_facts` is registered, the model may extract facts from those internal prompt stubs, producing noisy/confabulated facts. `enable_extraction=False` (default) suppresses the tool for all internal callers; only `chat_with_memory` sets it to `True`.

Threading `scope` into `_execute_tool`:

```python
def _execute_tool(self, name: str, args: dict, scope: str = "global") -> str:
```

The `_call_llm` tool loop passes `scope` on every dispatch (line ~169):

```python
# Before:
result = self._execute_tool(name, args)

# After:
result = self._execute_tool(name, args, scope=scope)
```

And `_call_llm` gets `scope` from its own new parameter, threaded via `_get_tools`:

```python
# In _call_llm:
tools = self._get_tools(enable_extraction=enable_extraction)
```

The full updated `_call_llm` signature and tool-injection point:

```python
def _call_llm(self, message: str, history: list, memory_context=None,
              injected_skills=None, scope="global", enable_extraction=False) -> str:
    messages = self._build_messages(message, history, memory_context, injected_skills)
    tools = self._get_tools(enable_extraction=enable_extraction)
    ...
    # tool loop unchanged except the one line above
```

### 4. Remove Regex Path

Delete methods and their body (reference by method name, not line number — lines drift):

| Method | Lines (approx) |
|---|---|
| `_extract_facts()` | ~191-199 |
| `_scan_for_facts()` | ~201-224 |

The call at line ~262 (`self._extract_facts(message, response, scope)`) is also removed — no replacement needed; extraction happens inline in the tool loop now.

The `chat_with_memory` call to `self.chat()` changes to pass the new params:

```python
# Before:
response = self.chat(message, history or [], mem_block, injected_skills)
# After:
response = self.chat(message, history or [], mem_block, injected_skills,
                     scope=scope, enable_extraction=True)
```

All other `self.chat()` callers (lines 318, 358, 365) remain unchanged — they omit the new keyword args, so both default to `scope="global"` and `enable_extraction=False`.

### 5. Internal State Facts (unchanged)

`telegram_bot.py` writes `tts_enabled=true`, `tts_model=<name>`, `auto_learn=true/false` directly via `memory_store.add()` — these continue working as before and are not affected by the regex removal.

### 6. Memory stats

`self._memory_stats["extractions"]` incremented per new fact in `_handle_extract_facts` — same metric, same double-check usage in Telegram UI.

## Dedup Strategy

1. **Prompt level**: The LLM already sees existing `[USER FACTS]` in context + tool description says "only extract genuinely new information" — prevents most self-repeats.
2. **Handler level**: Exact-match check (`content.lower()`) against existing facts in scope before insert — backstop for any duplicates the model produces.

## Fallback Behavior

- If the LLM skips calling the tool on a message with extractable facts → fact is silently missed. Acceptable — not every message defines a fact. Can add a system prompt nudge ("When the user shares information about themselves, call `extract_facts`") if adoption is too low in practice.
- `MEMORY_AUTO_EXTRACT=false` disables tool registration entirely → no extraction.

## Files Modified

| File | Changes |
|---|---|
| `hermes_bridge.py` | `_get_tools()` gets `enable_extraction` param. `_build_extract_tool()`, `_handle_extract_facts()` added. `_execute_tool()` dispatch updated. `scope` and `enable_extraction` params added to `chat()`, `_call_llm()`. `scope` param added to `_execute_tool()`. `_extract_facts()`, `_scan_for_facts()` removed. |
| (none else) | No config, memory_store, or telegram_bot changes needed. |

## Verification

1. Send "my name is John" → check `memory.db` for stored fact `"User: John"` (or whatever the LLM extracts)
2. Send "I like pizza" → same chat → one new fact stored, no duplicate of existing exact-match fact
3. `MEMORY_AUTO_EXTRACT=false` → no `extract_facts` tool registered → no extraction
4. Existing TTS state and auto_learn flags continue to write correctly
5. Internal callers (`parse_schedule`, `generate_minutes`) don't trigger extraction — confirm by checking no new facts appear after scheduling a task
6. When composio is NOT ready, `tools=[extract_facts_schema]` with `tool_choice="auto"` still works — single tool registered, bot responds normally
7. When composio IS ready, `extract_facts` is second tool in list — both registered, model picks correctly
