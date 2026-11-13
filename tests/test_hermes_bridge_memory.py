import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hermes_bridge import HermesBridge
from memory_store import MemoryStore


class PromptCaptureBridge(HermesBridge):
    def __init__(self, settings):
        super().__init__(settings)
        self.messages = None

    def _call_llm(self, message, history, memory_context=None, injected_skills=None,
                  scope="global", enable_extraction=False, system_override=None,
                  response_format=None, preference_context=None, **kwargs):
        self.messages = self._build_messages(
            message,
            history,
            memory_context,
            injected_skills,
            system_override=system_override,
            preference_context=preference_context,
        )
        return "captured response"


class DeterministicBridge(HermesBridge):
    def __init__(self, settings):
        super().__init__(settings)
        self.chat_calls = []
        self.expansion_calls = []

    def _expand_query(self, message):
        self.expansion_calls.append(message)
        return []

    def _auto_learn_enabled(self, scope):
        return False

    def chat(
        self,
        message,
        history=None,
        memory_context=None,
        injected_skills=None,
        scope="global",
        enable_extraction=False,
        system_override=None,
        response_format=None,
        preference_context=None,
    ):
        self.chat_calls.append(
            {
                "message": message,
                "history": history,
                "memory_context": memory_context,
                "injected_skills": injected_skills,
                "scope": scope,
                "enable_extraction": enable_extraction,
                "system_override": system_override,
                "preference_context": preference_context,
            }
        )
        return "deterministic response"


def make_settings():
    return SimpleNamespace(
        provider_name="router_0",
        ROUTER_0_MODEL="test-model",
        OPENROUTER_MODEL="test-model",
        OPENCODE_ZEN_MODEL="test-model",
        MEMORY_ENABLED=True,
        MEMORY_AUTO_EXTRACT=False,
        AUTO_LEARN=False,
        SYSTEM_PROMPT="test prompt",
    )


class HermesBridgeMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(str(Path(self.temp.name) / "memory.db"))
        self.bridge = DeterministicBridge(make_settings())
        self.bridge.memory_store = self.store
        self.addCleanup(self.store.close)

    def test_non_simple_memory_chat_is_offline_and_deterministic(self):
        self.store.add("Shared deployment policy", scope="global")
        self.store.add("User 101 deployment note", scope="user:101")
        self.store.add("User 202 deployment note", scope="user:202")

        result = self.bridge.chat_with_memory(
            "Explain the deployment policy and deployment note",
            history=[{"role": "user", "content": "Earlier context"}],
            scope="user:101",
        )

        self.assertEqual(result, "deterministic response")
        self.assertEqual(
            self.bridge.chat_calls[0]["memory_context"].splitlines(),
            ["- User 101 deployment note", "- Shared deployment policy"],
        )
        self.assertNotIn("User 202 deployment note", self.bridge.chat_calls[0]["memory_context"])
        self.assertEqual(self.bridge.expansion_calls, ["Explain the deployment policy and deployment note"])
        self.assertEqual(len(self.bridge.chat_calls), 1)
        self.assertEqual(self.bridge.chat_calls[0]["scope"], "user:101")
        self.assertTrue(self.bridge.chat_calls[0]["enable_extraction"])

    def test_local_fact_wins_over_same_global_fact(self):
        self.store.add("Shared deployment policy", scope="global")
        self.store.add("Shared deployment policy", scope="user:101")
        self.store.add("Local deployment exception", scope="user:101")

        self.bridge.chat_with_memory(
            "Explain the shared deployment policy and local deployment exception",
            scope="user:101",
        )

        lines = self.bridge.chat_calls[0]["memory_context"].splitlines()
        self.assertEqual(lines.count("- Shared deployment policy"), 1)
        self.assertIn("- Local deployment exception", lines)

    def test_global_preferences_fallback_and_preference_isolation(self):
        for scope, key, value, content in (
            ("global", "response_style", "detailed", "Global style"),
            ("global", "language", "English", "Global language"),
            ("user:202", "format", "JSON", "User 202 format"),
        ):
            self.store.add(
                content,
                scope=scope,
                metadata={
                    "category": "preference",
                    "preference_key": key,
                    "preference_value": value,
                    "explicit": True,
                },
            )
        self.store.add(
            "User 101 style",
            scope="user:101",
            metadata={
                "category": "preference",
                "preference_key": "response_style",
                "preference_value": "concise",
                "explicit": True,
            },
        )

        self.bridge.chat_with_memory("Explain deployment preferences", scope="user:101")
        preference_context = self.bridge.chat_calls[0]["preference_context"]

        self.assertIn("- response_style: concise", preference_context)
        self.assertIn("- language: English", preference_context)
        self.assertNotIn("- response_style: detailed", preference_context)
        self.assertNotIn("User 202 format", preference_context)

        self.bridge.chat_calls.clear()
        self.bridge.chat_with_memory("Explain deployment preferences", scope="user:202")
        preference_context = self.bridge.chat_calls[0]["preference_context"]
        self.assertIn("- response_style: detailed", preference_context)
        self.assertIn("- language: English", preference_context)
        self.assertIn("- format: JSON", preference_context)

    def test_global_preferences_and_local_precedence_are_injected(self):
        self.store.add(
            "Use concise replies",
            scope="global",
            metadata={
                "category": "preference",
                "preference_key": "response_style",
                "preference_value": "detailed",
                "explicit": True,
            },
        )
        self.store.add(
            "Use concise replies locally",
            scope="user:101",
            metadata={
                "category": "preference",
                "preference_key": "response_style",
                "preference_value": "concise",
                "explicit": True,
            },
        )

        self.bridge.chat_with_memory(
            "Explain the deployment preference policy",
            scope="user:101",
        )

        self.assertEqual(
            self.bridge.chat_calls[0]["preference_context"],
            "- response_style: concise",
        )

    def test_global_and_local_skills_are_injected_with_precedence_and_inactive_excluded(self):
        local_id = self.store.skill_add(
            "Deployment procedure",
            "deployment policy",
            "local steps",
            scope="user:101",
        )["id"]
        global_duplicate_id = self.store.global_skill_add(
            "Deployment procedure",
            "deployment policy",
            "global steps",
        )["id"]
        global_id = self.store.global_skill_add(
            "Shared deployment procedure",
            "deployment policy",
            "global steps",
        )["id"]
        inactive_global_id = self.store.global_skill_add(
            "Inactive global deployment procedure",
            "deployment policy",
            "inactive steps",
        )["id"]
        inactive_local_id = self.store.skill_add(
            "Inactive local deployment procedure",
            "deployment policy",
            "inactive local steps",
            scope="user:101",
        )["id"]
        self.assertTrue(self.store.global_skill_set_status(inactive_global_id, "inactive"))
        self.assertTrue(self.store.skill_update(inactive_local_id, "user:101", status="inactive"))

        self.bridge.chat_with_memory(
            "Explain the deployment policy procedure",
            scope="user:101",
        )

        skills = self.bridge.chat_calls[0]["injected_skills"]
        self.assertEqual({skill["id"] for skill in skills}, {local_id, global_id})
        self.assertNotIn(global_duplicate_id, {skill["id"] for skill in skills})
        self.assertNotIn(inactive_global_id, {skill["id"] for skill in skills})
        self.assertNotIn(inactive_local_id, {skill["id"] for skill in skills})
        self.assertEqual(
            next(skill for skill in skills if skill["title"] == "Deployment procedure")["procedure"],
            "local steps",
        )

    def test_local_memory_isolation_excludes_other_user_data(self):
        self.store.add("User 101 private deployment fact", scope="user:101")
        self.store.add("User 202 private deployment fact", scope="user:202")
        local_id = self.store.skill_add(
            "Private deployment procedure",
            "deployment policy",
            "local steps",
            scope="user:101",
        )["id"]
        other_id = self.store.skill_add(
            "Other private deployment procedure",
            "deployment policy",
            "private steps",
            scope="user:202",
        )["id"]
        self.store.add(
            "User 101 format",
            scope="user:101",
            metadata={
                "category": "preference",
                "preference_key": "format",
                "preference_value": "markdown",
                "explicit": True,
            },
        )
        self.store.add(
            "User 202 format",
            scope="user:202",
            metadata={
                "category": "preference",
                "preference_key": "format",
                "preference_value": "JSON",
                "explicit": True,
            },
        )

        self.bridge.chat_with_memory(
            "Explain the private deployment policy",
            scope="user:101",
        )

        call = self.bridge.chat_calls[0]
        self.assertIn("User 101 private deployment fact", call["memory_context"] or "")
        self.assertNotIn("User 202 private deployment fact", call["memory_context"] or "")
        self.assertEqual({skill["id"] for skill in call["injected_skills"]}, {local_id})
        self.assertNotIn(other_id, {skill["id"] for skill in call["injected_skills"]})
        self.assertIn("- format: markdown", call["preference_context"])
        self.assertNotIn("- format: JSON", call["preference_context"])

    def test_real_chat_builds_prompt_with_all_injected_context(self):
        bridge = PromptCaptureBridge(make_settings())
        bridge.memory_store = self.store
        bridge.memory_enabled = True
        bridge._ready = True
        bridge._expand_query = lambda message: []
        bridge._auto_learn_enabled = lambda scope: False
        self.store.add("Prompt fact", scope="global")
        skill_id = self.store.global_skill_add(
            "Prompt skill", "prompt deployment", "prompt steps"
        )["id"]

        result = bridge.chat_with_memory("Explain prompt deployment", scope="user:101")

        self.assertEqual(result, "captured response")
        system = bridge.messages[0]["content"]
        self.assertIn("[SKILLS]", system)
        self.assertIn('"Prompt skill"', system)
        self.assertIn("[USER FACTS]", system)
        self.assertIn("Prompt fact", system)
        self.assertIn("test prompt", system)
        self.assertEqual(bridge.messages[-1], {"role": "user", "content": "Explain prompt deployment"})

    def test_extraction_rejects_global_and_invalid_scopes(self):
        args = {"facts": [{"content": "Must not become global", "category": "fact"}]}

        for scope in ("global", "", None, "user:not-an-id"):
            result = self.bridge._handle_extract_facts(args, scope=scope)
            self.assertEqual(result, '{"stored": 0, "error": "invalid extraction scope"}')

        self.assertEqual(self.store.search("Must not become global", "global"), [])

    def test_extraction_exact_duplicate_ignores_ranked_search_limit(self):
        content = "Exact duplicate deployment fact"
        self.store.add(content, scope="user:101")
        for index in range(5):
            self.store.add(
                f"Exact duplicate deployment fact variant {index}",
                scope="user:101",
            )

        result = self.bridge._handle_extract_facts(
            {"facts": [{"content": content, "category": "fact"}]},
            scope="user:101",
        )

        self.assertEqual(result, '{"stored": 0}')
        self.assertEqual(len(self.store.search(content, "user:101", 20)), 6)
        self.assertEqual(
            sum(row["content"] == content for row in self.store.search("", "user:101", 20)),
            1,
        )

    def test_extraction_writes_facts_only_to_requested_user_scope(self):
        args = {
            "facts": [
                {"content": "User 101 prefers concise replies", "category": "fact"},
            ],
        }

        first = self.bridge._handle_extract_facts(args, scope="user:101")
        second = self.bridge._handle_extract_facts(args, scope="user:101")

        self.assertEqual(first, '{"stored": 1}')
        self.assertEqual(second, '{"stored": 0}')
        self.assertEqual(len(self.store.search("User 101 prefers", "user:101")), 1)
        self.assertEqual(self.store.search("User 101 prefers", "global"), [])
        self.assertEqual(self.store.search("User 101 prefers", "user:202"), [])

    def test_extraction_writes_preferences_only_to_requested_group_scope(self):
        args = {
            "facts": [
                {
                    "content": "Group prefers concise replies",
                    "category": "preference",
                    "preference_key": "response_style",
                    "preference_value": "concise",
                    "explicit": True,
                },
            ],
        }

        result = self.bridge._handle_extract_facts(args, scope="chat:-202")

        self.assertEqual(result, '{"stored": 1}')
        self.assertEqual(
            self.store.get_preferences("chat:-202"),
            [
                {
                    "preference_key": "response_style",
                    "preference_value": "concise",
                    "content": "Group prefers concise replies",
                }
            ],
        )
        self.assertEqual(self.store.get_preferences("global"), [])
        self.assertEqual(self.store.get_preferences("user:101"), [])

    def test_preference_extraction_replaces_only_local_value(self):
        self.store.add(
            "Global prefers detailed replies",
            scope="global",
            metadata={
                "category": "preference",
                "preference_key": "response_style",
                "preference_value": "detailed",
                "explicit": True,
            },
        )
        self.store.add(
            "User prefers concise replies",
            scope="user:101",
            metadata={
                "category": "preference",
                "preference_key": "response_style",
                "preference_value": "concise",
                "explicit": True,
            },
        )

        result = self.bridge._handle_extract_facts(
            {
                "facts": [
                    {
                        "content": "User now prefers structured replies",
                        "category": "preference",
                        "preference_key": "response_style",
                        "preference_value": "structured",
                        "explicit": True,
                    },
                ],
            },
            scope="user:101",
        )

        self.assertEqual(result, '{"stored": 1}')
        self.assertEqual(
            self.store.get_preferences("user:101"),
            [
                {
                    "preference_key": "response_style",
                    "preference_value": "structured",
                    "content": "User now prefers structured replies",
                }
            ],
        )
        self.assertEqual(
            self.store.get_preferences("global"),
            [
                {
                    "preference_key": "response_style",
                    "preference_value": "detailed",
                    "content": "Global prefers detailed replies",
                }
            ],
        )

    def test_simple_chat_uses_fast_path_without_memory_search(self):
        self.store.add("Shared deployment policy", scope="global")

        result = self.bridge.chat_with_memory("Hello", scope="user:101")

        self.assertEqual(result, "deterministic response")
        self.assertEqual(self.bridge.expansion_calls, [])
        self.assertEqual(self.bridge.chat_calls[0]["memory_context"], None)
        self.assertEqual(self.bridge.chat_calls[0]["injected_skills"], None)
        self.assertFalse(self.bridge.chat_calls[0]["enable_extraction"])


if __name__ == "__main__":
    unittest.main()
