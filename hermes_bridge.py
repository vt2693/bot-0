import json
import re
import time
import logging
from typing import Optional

import httpx

from config import Settings

logger = logging.getLogger(__name__)


class HermesBridge:
    def __init__(self, settings: Settings, composio=None):
        self.settings = settings
        self._composio = composio
        self._ready = False
        self._error = ""
        self._provider = settings.provider_name or "none"
        self._model = self._resolve_model()
        self.memory_store = None
        self.memory_enabled = settings.MEMORY_ENABLED
        self._memory_stats = {"injections": 0, "hits": 0, "misses": 0, "extractions": 0, "skill_detections": 0}
        self.broadcast_fn = None

    def _resolve_model(self) -> str:
        s = self.settings
        return {
            "opencode_zen": s.OPENCODE_ZEN_MODEL,
            "openrouter": s.OPENROUTER_MODEL,
            "router_0": s.ROUTER_0_MODEL,
        }.get(self._provider, "unknown")

    def _resolve_base_url(self) -> Optional[str]:
        s = self.settings
        return {"opencode_zen": s.OPENCODE_ZEN_BASE_URL, "openrouter": s.OPENROUTER_BASE_URL, "router_0": s.ROUTER_0_BASE_URL}.get(self._provider)

    def _resolve_api_key(self) -> Optional[str]:
        s = self.settings
        key = {"opencode_zen": s.OPENCODE_ZEN_API_KEY, "openrouter": s.OPENROUTER_API_KEY, "router_0": s.ROUTER_0_API_KEY}.get(self._provider)
        if not key and self._provider == "router_0":
            return ""
        return key

    @property
    def memory_stats(self) -> dict:
        return dict(self._memory_stats)

    def initialize(self) -> None:
        if self._provider == "none":
            self._error = "No LLM provider configured"
            return
        self._ready = True

    def available_providers(self) -> dict:
        s = self.settings
        pairs = [("opencode_zen", s.OPENCODE_ZEN_API_KEY, s.OPENCODE_ZEN_MODEL), ("openrouter", s.OPENROUTER_API_KEY, s.OPENROUTER_MODEL), ("router_0", s.ROUTER_0_API_KEY, s.ROUTER_0_MODEL)]
        return {k: f"{k} ({m})" for k, key, m in pairs if key}

    def switch_model(self, model: str) -> dict:
        if not model:
            return {"success": False, "error": "Model name empty"}
        self._model = model
        return {"success": True, "provider": self._provider, "model": self._model}

    def switch_provider(self, name: str) -> dict:
        if name not in self.available_providers():
            return {"success": False, "error": f"Unknown provider: {name}"}
        self._provider = name
        self._model = self._resolve_model()
        self._ready = True
        return {"success": True, "provider": self._provider, "model": self._model}

    def _build_messages(self, message: str, history: list,
                         memory_context: str | None = None,
                         injected_skills: list | None = None,
                         system_override: str | None = None) -> list[dict]:
        if system_override:
            return [{"role": "system", "content": system_override},
                    {"role": "user", "content": message}]
        sys = self.settings.SYSTEM_PROMPT
        if injected_skills:
            sys += "\n\n[SKILLS]\nRelevant procedures you know:\n"
            for s in injected_skills:
                sys += f'- "{s["title"]}": {s["problem"][:200]}\n'
                if s.get("failure_pattern"):
                    sys += f'  Failure pattern to avoid: {s["failure_pattern"][:200]}\n'
            sys += "\nAsk the user if they want the full procedure.\n"
        if memory_context:
            sys += "\n\n[USER FACTS]\n" + memory_context
        msgs = [{"role": "system", "content": sys}]
        for item in history[-100:]:
            if isinstance(item, dict):
                role = item.get("role") or "user"
                content = item.get("content") or ""
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                msgs.append({"role": "user", "content": str(item[0])})
                msgs.append({"role": "assistant", "content": str(item[1])})
                continue
            else:
                role = "user" if len(msgs) % 2 else "assistant"
                content = str(item)
            if content:
                msgs.append({"role": role, "content": content})
        msgs.append({"role": "user", "content": message})
        return msgs

    def _get_tools(self, enable_extraction: bool = False) -> list[dict]:
        tools = []
        if self._composio and self._composio.status().get("ready"):
            tools.extend(self._composio.get_openai_tools())
        if enable_extraction and self.settings.MEMORY_AUTO_EXTRACT:
            tools.append(self._build_extract_tool())
        return tools

    def _build_extract_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "extract_facts",
                "description": (
                    "Extract durable facts about the user useful across future "
                    "conversations (e.g. name, occupation, preferences, location, "
                    "skills). Avoid transient states."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "facts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "description": "The fact about the user, written as a clear statement"
                                    },
                                    "category": {
                                        "type": "string",
                                        "enum": ["bio", "preference", "fact", "context"],
                                        "description": "Type of fact"
                                    }
                                },
                                "required": ["content"]
                            }
                        }
                    },
                    "required": ["facts"]
                }
            }
        }

    def chat(self, message: str, history: list | None = None,
             memory_context: str | None = None,
             injected_skills: list | None = None,
             scope: str = "global",
             enable_extraction: bool = False,
             system_override: str | None = None,
             response_format: dict | None = None) -> str:
        if not self._ready:
            return "Hermes Agent is not configured. Add a provider API key."
        try:
            return self._call_llm(message, history or [], memory_context,
                                  injected_skills, scope=scope,
                                  enable_extraction=enable_extraction,
                                  system_override=system_override,
                                  response_format=response_format)
        except Exception as e:
            logger.exception("Chat failed")
            return f"Error: {e}"

    def _call_llm(self, message: str, history: list,
                  memory_context: str | None = None,
                  injected_skills: list | None = None,
                  scope: str = "global",
                  enable_extraction: bool = False,
                  system_override: str | None = None,
                  response_format: dict | None = None) -> str:
        messages = self._build_messages(message, history, memory_context, injected_skills, system_override=system_override)
        tools = [] if system_override else self._get_tools(enable_extraction=enable_extraction)
        body = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self.settings.MAX_TOKENS,
            "temperature": self.settings.TEMPERATURE,
            "stream": False,
        }
        if system_override:
            body["temperature"] = 0
            body["max_tokens"] = 200
        if response_format:
            body["response_format"] = response_format
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        api_key = self._resolve_api_key()
        base_url = self._resolve_base_url()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        url = (base_url.rstrip("/") if base_url else "") + "/chat/completions"

        max_rounds = self.settings.TOOL_LOOP_MAX_ROUNDS
        for round_i in range(max_rounds):
            last_err = None
            for attempt in range(3):
                try:
                    resp = httpx.post(url, json=body, headers=headers, timeout=self.settings.LLM_TIMEOUT)
                    resp.raise_for_status()
                    data = resp.json()
                    last_err = None
                    break
                except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.TimeoutException,
                        httpx.HTTPStatusError, json.JSONDecodeError) as e:
                    last_err = e
                    if attempt < 2:
                        import time as _time
                        _time.sleep(1.5 ** attempt)
                    continue
            if last_err:
                raise last_err
            choice = data["choices"][0]
            msg = choice["message"]
            content = msg.get("content") or ""
            calls = msg.get("tool_calls") or []
            if not calls:
                return content
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            for c in calls:
                name = c["function"]["name"]
                args = json.loads(c["function"]["arguments"] or "{}")
                result = self._execute_tool(name, args, scope=scope)
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": result[:12000]})
                if self.broadcast_fn:
                    try:
                        self.broadcast_fn(
                            f"🔧 [{round_i+1}] **{name}**\n"
                            f"Args: `{json.dumps(args, default=str)[:500]}`\n"
                            f"Result: `{result[:2000]}`"
                        )
                    except Exception:
                        pass
            body["messages"] = messages
        return f"Tool loop stopped after {max_rounds} rounds. The task may need more steps or the tools are failing. Try a simpler request."

    def _execute_tool(self, name: str, args: dict, scope: str = "global") -> str:
        if name == "extract_facts":
            return self._handle_extract_facts(args, scope)
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

    def _auto_learn_enabled(self, scope: str) -> bool:
        env_on = self.settings.AUTO_LEARN
        if not self.memory_store:
            return env_on
        try:
            flags = self.memory_store.search("auto_learn", scope, 20)
            exact = [f for f in flags if f["content"].strip().lower() in ("auto_learn=true", "auto_learn=false")]
            if exact:
                latest = max(exact, key=lambda f: f.get("id", 0))
                return latest["content"].strip().lower() == "auto_learn=true"
        except Exception:
            pass
        return env_on

    EXPAND_SYSTEM_PROMPT = (
        "You are a memory retrieval assistant. Rephrase the user's message into 3-6 "
        "standalone search terms — names, topics, synonyms, related words — that would "
        "match a stored fact in a keyword search engine. Return ONLY a JSON object "
        'with a single key "terms" whose value is an array of strings.'
    )

    @staticmethod
    def _normalize_expansion(out: str) -> list[str]:
        """Parse the LLM's expansion reply into a list of terms.

        Accepts a JSON object {"terms": [...]}, a bare JSON array, or
        prose/code-fenced wrappers. Falls back to [] on any parse failure so
        retrieval degrades to the raw keyword search.
        """
        if not out or not isinstance(out, str):
            return []
        s = out.strip()
        # Strip ```json ... ``` fences if the model emits them.
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
        try:
            data = json.loads(s)
        except Exception:
            return []
        if isinstance(data, list):
            terms = data
        elif isinstance(data, dict):
            terms = data.get("terms") or []
        else:
            return []
        return [str(t).strip() for t in terms if str(t).strip()][:10]

    def _expand_query(self, message: str) -> list[str]:
        """LLM query expansion: turn the message into better search terms.

        Reuses chat() with system_override + response_format, so it's isolated
        (no history/tools/skills/extraction) and cheap (temp 0, max_tokens 200).
        Every failure degrades to the raw keyword search (returns []).
        """
        if not (self.memory_enabled and self.memory_store):
            return []
        if len(message.strip()) < 3:
            return []
        try:
            out = self.chat(message, history=[], scope="global",
                            system_override=self.EXPAND_SYSTEM_PROMPT,
                            response_format={"type": "json_object"})
            return self._normalize_expansion(out)
        except Exception:
            logger.exception("Query expansion failed; falling back to keyword search")
            return []

    def chat_with_memory(self, message: str, history: list | None = None, scope: str = "global") -> str:
        mem_block = None
        injected_skills = None
        if self.memory_enabled and self.memory_store:
            self._memory_stats["injections"] += 1
            expanded = self._expand_query(message)
            mems = self.memory_store.get_relevant(message, scope, 100, extra_terms=expanded)
            if mems:
                self._memory_stats["hits"] += 1
                mem_block = "\n".join("- " + m["content"] for m in mems)
            else:
                self._memory_stats["misses"] += 1
            skills = self.memory_store.skill_inject(message, scope, 10)
            if skills:
                injected_skills = skills
        response = self.chat(message, history or [], mem_block, injected_skills,
                             scope=scope, enable_extraction=True)
        if injected_skills and re.search(r"skill|procedure|steps|here.?s how", response or "", re.I):
            for s in injected_skills:
                try:
                    self.memory_store.skill_record_usage(s["id"])
                except Exception:
                    pass
        if self._auto_learn_enabled(scope):
            skill = self._detect_skill(message, response, history or [])
            if skill:
                return json.dumps({"_skill_detected": skill, "response": response})
        return response

    def _detect_skill(self, message: str, response: str, history: list) -> dict | None:
        import re as _re
        if not self.memory_store:
            return None
        user_success = bool(_re.search(r"thanks|works|fixed|got it|solved|that did it|perfect", message, _re.I))
        hist_pairs = len([m for m in history if isinstance(m, dict) and m.get("role") == "user"])
        correction = hist_pairs >= 3 and bool(_re.search(r"(send|error|token|key|reset|reconfig|relay|timeout)", message, _re.I))
        explicit = bool(_re.search(r"(?:save|create|remember|note|learn|store)\s+(?:this|a|that|the)?\s*(?:skill|procedure|workflow|process|technique)?", message, _re.I))
        if not (user_success or correction or explicit):
            return None
        last_user = message[:800]
        last_asst = response[:800]
        if explicit:
            hist_ctx = []
            for item in (history or [])[-15:]:
                if isinstance(item, dict):
                    hist_ctx.append(f"{item['role']}: {item['content'][:300]}")
            extract_prompt = (
                "The user wants to save a reusable skill/procedure. "
                "Extract it from the conversation.\n\n"
                "--- Previous conversation ---\n"
                + "\n".join(hist_ctx[-10:]) +
                "\n--- Current message ---\n"
                f"User: {last_user}\n"
                "--- End ---\n\n"
                "Return ONLY valid JSON (no other text):\n"
                '{"skill": true, "title": "...", "problem": "...", "procedure": "...", "failure_pattern": "..."}'
            )
        else:
            extract_prompt = (
                "--- Exchange ---\n"
                f"User: {last_user}\n"
                f"Assistant: {last_asst}\n"
                "--- End ---\n\n"
                "Was a reusable workflow learned here? Apply the rubric:\n"
                "1. Was a specific multi-step procedure demonstrated?\n"
                "2. Was the outcome verified (user confirmed \"works\"/\"thanks\"/\"fixed\")?\n"
                "3. Is the procedure specific enough to teach someone else?\n\n"
                "If yes, return ONLY valid JSON (no other text):\n"
                '{"skill": true, "title": "...", "problem": "...", "procedure": "...", "failure_pattern": "..."}\n\n'
                'If no: {"skill": false}'
            )
        try:
            body = self.chat(extract_prompt, [])
            result = json.loads(body)
            if result.get("skill") and result.get("title") and result.get("procedure"):
                self._memory_stats.setdefault("skill_detections", 0)
                self._memory_stats["skill_detections"] += 1
                return result
        except (json.JSONDecodeError, Exception):
            pass
        return None

    # ──────────────────────────────────────────────
    # Deterministic schedule parsing (no LLM call)
    # ──────────────────────────────────────────────

    # Priority-ordered patterns for time expression extraction.
    # Each is (name, regex) — first match wins.
    _TIME_PATTERNS = [
        ("every_day_at", re.compile(
            r'(?:every\s+day|daily)\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?', re.I)),
        ("every_day_at_nomin", re.compile(
            r'(?:every\s+day|daily)\s+at\s+(\d{1,2})\s*(am|pm)\b', re.I)),
        ("at_time_with_daily_prefix", re.compile(
            r'(?:every\s+day|daily)\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', re.I)),
        ("every_weekday_at", re.compile(
            r'(?:every\s+weekdays?|weekdays?)\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?', re.I)),
        ("every_weekday_at_nomin", re.compile(
            r'(?:every\s+weekdays?|weekdays?)\s+at\s+(\d{1,2})\s*(am|pm)\b', re.I)),
        ("every_day_naked", re.compile(
            r'(?:every\s+day|\bdaily\b)(?!\s+at)', re.I)),
        ("every_n_min", re.compile(
            r'every\s+(\d+)\s*(?:min(?:ute)?s?)\b', re.I)),
        ("every_n_hour", re.compile(
            r'every\s+(\d+)\s*(?:hours?|hrs?)\b', re.I)),
        ("hourly", re.compile(
            r'\b(hourly|every\s+hour)\b', re.I)),
        ("in_n_min", re.compile(
            r'in\s+(\d+)\s*(?:min(?:ute)?s?)\b', re.I)),
        ("in_n_hour", re.compile(
            r'in\s+(\d+)\s*(?:hours?|hrs?)\b', re.I)),
        ("in_n_sec", re.compile(
            r'in\s+(\d+)\s*(?:sec(?:ond)?s?)\b', re.I)),
        ("tomorrow_at_time", re.compile(
            r'tomorrow\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?', re.I)),
        ("tomorrow_at_nomin", re.compile(
            r'tomorrow\s+at\s+(\d{1,2})\s*(am|pm)\b', re.I)),
        ("at_time", re.compile(
            r'at\s+(\d{1,2}):(\d{2})\s*(am|pm)?', re.I)),
        ("at_time_nomin", re.compile(
            r'at\s+(\d{1,2})\s*(am|pm)\b', re.I)),
        ("at_noon", re.compile(
            r'\bnoon\b', re.I)),
        ("at_midnight", re.compile(
            r'\bmidnight\b', re.I)),
        ("every_other_day", re.compile(
            r'every\s+other\s+day\b', re.I)),
        ("twice_a_day", re.compile(
            r'twice\s+a\s+day\b', re.I)),
    ]

    def _compute_epoch(self, hour: int, minute: int, *,
                       is_tomorrow: bool = False,
                       next_weekday: int | None = None) -> int:
        """Compute epoch for HH:MM today/tomorrow/next-weekday in local time."""
        lt = time.localtime()
        target = int(time.mktime((
            lt.tm_year, lt.tm_mon, lt.tm_mday,
            hour, minute, 0, 0, 0, -1
        )))
        now = int(time.time())
        if next_weekday is not None:
            days_ahead = next_weekday - lt.tm_wday
            if days_ahead <= 0 or (days_ahead == 0 and target <= now):
                days_ahead += 7
            target += days_ahead * 86400
        elif is_tomorrow:
            target += 86400
        elif target <= now:
            target += 86400
        return target

    def _normalize_hour(self, hour: int, ampm: str | None) -> int:
        """Convert 12-hour clock to 24-hour. ampm is 'am'/'pm' or None."""
        if ampm:
            a = ampm.strip().lower()
            if a == "pm" and hour < 12:
                return hour + 12
            if a == "am" and hour == 12:
                return 0
            return hour
        return hour  # 24-hour format already

    def _parse_time_expr(self, match_id: str, match: re.Match, text: str) -> dict | None:
        """Convert a matched time expression into interval_minutes or absolute_epoch."""
        # ── Interval patterns (no hour/minute groups) ──
        if match_id in ("every_day_naked",):
            return {"interval_minutes": 1440}

        if match_id in ("every_n_min", "in_n_min"):
            return {"interval_minutes": int(match.group(1))}

        if match_id in ("every_n_hour",):
            return {"interval_minutes": int(match.group(1)) * 60}

        if match_id in ("in_n_hour",):
            return {"interval_minutes": int(match.group(1)) * 60}

        if match_id in ("in_n_sec",):
            return {"interval_minutes": max(1, int(match.group(1)) // 60)}

        if match_id in ("hourly",):
            return {"interval_minutes": 60}

        if match_id in ("every_other_day",):
            return {"interval_minutes": 2880}

        if match_id in ("twice_a_day",):
            return {"interval_minutes": 720}

        # ── Absolute epoch with no time groups ──
        if match_id in ("at_noon",):
            return {"absolute_epoch": self._compute_epoch(12, 0)}

        if match_id in ("at_midnight",):
            return {"absolute_epoch": self._compute_epoch(0, 0)}

        # ── All remaining: extract hour[:min][ampm] ──
        if match_id in ("every_day_at_nomin", "every_weekday_at_nomin",
                        "tomorrow_at_nomin", "at_time_nomin"):
            hour = int(match.group(1))
            minute = 0
            ampm = match.group(2) if match.lastindex >= 2 else None
        elif match_id == "at_time_with_daily_prefix":
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.lastindex >= 2 and match.group(2) is not None else 0
            ampm = match.group(3) if match.lastindex >= 3 else None
        else:
            # patterns with colon: group(1)=hour, group(2)=minute, group(3)=ampm?
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.lastindex >= 2 and match.group(2) is not None else 0
            ampm = match.group(3) if match.lastindex >= 3 else None

        is_tomorrow = "tomorrow" in match_id
        is_weekday = "weekday" in match_id
        is_recurring = match_id.startswith("every_") or match_id.startswith("twice_")

        # Bare hours (no am/pm) treated as 24-hour clock
        if ampm is None:
            hour24 = hour
        else:
            hour24 = self._normalize_hour(hour, ampm)

        # Weekday logic: 0=Mon..4=Fri
        nw = None
        if is_weekday:
            lt = time.localtime()
            if lt.tm_wday < 5:
                nw = lt.tm_wday
            else:
                nw = 0  # next Monday

        epoch = self._compute_epoch(hour24, minute, is_tomorrow=is_tomorrow, next_weekday=nw)
        return {"absolute_epoch": epoch}

    def _parse_deterministic(self, text: str) -> dict | None:
        """Try to extract schedule from text using regex patterns.
        Returns {"interval_minutes": N, "prompt": S} or {"absolute_epoch": E, "prompt": S},
        or None if no pattern matches (caller falls back to LLM)."""
        t = text.strip()
        if not t:
            return None

        for name, pattern in self._TIME_PATTERNS:
            m = pattern.search(t)
            if not m:
                continue
            # Extract prompt by removing the matched portion
            prompt = (t[:m.start()] + t[m.end():]).strip()
            # Clean up: collapse whitespace, remove leading "to"/"me"/"a"/"the"
            prompt = re.sub(r'\s+', ' ', prompt).strip()
            prompt = re.sub(r'^(to |me |a |the )', '', prompt)
            # Remove trailing prepositions only when time was at end of text
            if m.end() >= len(t) - 3:
                prompt = re.sub(r'\s+(at|in|on|by|for)\s*$', '', prompt)
            if not prompt:
                # Use whole text minus matched expression as prompt
                raw = t[:m.start()] + t[m.end():]
                raw = re.sub(r'\s+', ' ', raw).strip()
                raw = re.sub(r'\s+(at|in|on|by|for|before|after)\s*$', '', raw)
                if not raw:
                    raw = t.replace(m.group(0), "").strip()
                    raw = re.sub(r'\s+', ' ', raw).strip()
                    raw = re.sub(r'\s+(at|in|on|by|for|before|after)\s*$', '', raw)
                if not raw:
                    return None  # LLM fallback
                prompt = raw

            # If prompt still contains remaining time-related words, it's complex → LLM fallback
            # e.g. "scan at 3pm on friday" — "at 3pm" matches, but "on friday" stays in prompt
            if re.search(r'\b(on|next|this|mon|tue|wed|thu|fri|sat|sun|'
                         r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
                         r'tomorrow|weekday|weekdays)\b', prompt, re.I):
                return None

            # Check for remaining time expressions (duplicate match)
            if re.search(r'\b(\d{1,2})\s*(am|pm)\b', prompt, re.I):
                return None

            parsed = self._parse_time_expr(name, m, text)
            if parsed is None:
                continue
            parsed["prompt"] = prompt
            return parsed

        return None

    def parse_schedule(self, text: str) -> dict:
        """Parse natural-language scheduling intent.
        Tries deterministic regex first, falls back to LLM.

        Returns {"interval_minutes": int, "prompt": str},
                {"absolute_epoch": float, "prompt": str},
                or {"error": str}.
        """
        # Try deterministic pre-processing first (no LLM call needed)
        result = self._parse_deterministic(text)
        if result and "prompt" in result and result["prompt"]:
            return result
        if result and "prompt" in result and not result["prompt"]:
            return {"error": "Describe what to do, e.g. '/schedule add check gmail every 15 minutes'"}

        now = time.time()
        date_str = time.strftime("%Y-%m-%d %A", time.localtime(now))

        system_override = (
            "Extract scheduling intent from the user's text.\n"
            f"Today is {date_str} (Unix epoch: {now:.0f}).\n\n"
            "Return ONLY valid JSON. Exactly one of these shapes:\n"
            '{"interval_minutes": <number>, "prompt": "<string>"}\n'
            '{"absolute_epoch": <unix_timestamp>, "prompt": "<string>"}\n'
            '{"error": "<reason>"}\n\n'
            "Rules:\n"
            '- "every N" (number only, e.g. every 15), "in N hours/minutes", "hourly", "daily" -> interval_minutes\n'
            '- "every day at <time>", "daily at <time>" -> absolute_epoch (fixed daily time; NOT interval_minutes)\n'
            '- "at <time>", "<time> tomorrow/on <day>" -> absolute_epoch (Unix seconds, compute as seconds since 1970-01-01 UTC)\n'
            '- prompt is the task description WITHOUT timing words\n'
            '- If no scheduling intent, return {"error": "..."}\n\n'
            "Examples:\n"
            '- "check gmail every 15 minutes" -> {"interval_minutes": 15, "prompt": "check gmail"}\n'
            '- "every 2 hours, summarize news" -> {"interval_minutes": 120, "prompt": "summarize news"}\n'
            '- "check gmail at 12:00 am tomorrow" -> {"absolute_epoch": <epoch>, "prompt": "check gmail"}\n'
            '- "scan at 3pm on friday" -> {"absolute_epoch": <epoch>, "prompt": "scan"}\n'
            '- "remind me in 30 minutes" -> {"interval_minutes": 30, "prompt": "remind me"}\n'
            '- "provide weather forecast every day at 6 am" -> {"absolute_epoch": <epoch>, "prompt": "provide weather forecast"}\n'
            '- "hello" -> {"error": "no scheduling intent found"}'
        )

        for attempt in range(3):
            body = self.chat(text, [], system_override=system_override)
            try:
                result = json.loads(body)
            except json.JSONDecodeError:
                if attempt < 2:
                    system_override += (
                        f"\n\nPrevious attempt returned invalid JSON: '{body[:200]}'. "
                        "Return ONLY valid JSON, no other text."
                    )
                    continue
                return {"error": "parse_schedule: failed to produce valid JSON after 3 attempts"}
            has_interval = "interval_minutes" in result
            has_epoch = "absolute_epoch" in result
            has_error = "error" in result
            if not (has_interval or has_epoch or has_error):
                if attempt < 2:
                    system_override += (
                        f"\n\nResponse missing required key. Got: {json.dumps(result)[:200]}. "
                        "Must have interval_minutes, absolute_epoch, or error."
                    )
                    continue
                return {"error": "parse_schedule: response missing required key"}
            if has_error:
                return result
            if has_interval:
                if not isinstance(result["interval_minutes"], (int, float)) or result["interval_minutes"] < 1:
                    if attempt < 2:
                        system_override += (
                            f"\n\ninterval_minutes must be >= 1. Got: {result['interval_minutes']}."
                        )
                        continue
                    return {"error": "parse_schedule: invalid interval"}
                return result
            if has_epoch:
                epoch = result["absolute_epoch"]
                if not isinstance(epoch, (int, float)):
                    if attempt < 2:
                        system_override += (
                            f"\n\nabsolute_epoch must be a number. Got: {epoch}. "
                            "Compute the next Unix timestamp as a number."
                        )
                        continue
                    return {"error": "parse_schedule: absolute_epoch must be a number"}
                if epoch < now - 86400:
                    if attempt < 2:
                        system_override += (
                            f"\n\nabsolute_epoch {epoch:.0f} is in the past (now={now:.0f}). "
                            "Compute the NEXT occurrence of the specified day/time."
                        )
                        continue
                    return {"error": f"parse_schedule: epoch {epoch:.0f} is in the past"}
                if epoch > now + 86400 * 365 * 5:
                    return {"error": "parse_schedule: epoch too far in the future"}
                return result
        return {"error": "parse_schedule: unexpected fallthrough"}

    def generate_minutes(self, transcript: str) -> str:
        prompt = "Summarize this voice memo into concise meeting minutes with key points, decisions, action items, and next steps.\n\nTranscript:\n" + transcript[:12000]
        return self.chat(prompt, [])

    def status(self) -> dict:
        return {"ready": self._ready, "error": self._error, "provider": self._provider, "model": self._model, "memory": self.memory_stats, "providers": self.available_providers()}
