import tempfile
import unittest
from pathlib import Path

from memory_store import MemoryStore


class MemoryStoreCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(str(Path(self._tmp.name) / "memory.db"))

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_fact_search_is_scoped_by_chat_scope(self):
        self.store.add("User A secret fact", scope="101")
        self.store.add("User B fact", scope="202")

        self.assertEqual(
            [row["content"] for row in self.store.search("secret", "101")],
            ["User A secret fact"],
        )
        self.assertEqual(self.store.search("secret", "202"), [])

    def test_status_is_scoped_to_requested_scope(self):
        self.store.add("User A visible fact", scope="101")
        self.store.add("User B visible fact", scope="202")

        status = self.store.status(scope="101")

        self.assertEqual(status["fact_count"], 1)
        self.assertEqual(
            {row["content"] for row in status["top_facts"]},
            {"User A visible fact"},
        )

    def test_skill_id_operations_require_owner_scope(self):
        saved = self.store.skill_add(
            "Private procedure",
            "User A problem",
            "User A procedure",
            scope="101",
        )
        skill_id = saved["id"]

        self.assertEqual(self.store.skill_search("private", "202"), [])
        self.assertIsNone(self.store.skill_get(skill_id, scope="202"))
        self.assertFalse(self.store.skill_update(skill_id, scope="202", procedure="stolen"))
        self.assertFalse(self.store.skill_remove(skill_id, scope="202"))
        self.assertEqual(self.store.skill_get(skill_id, scope="101")["scope"], "101")

    def test_same_skill_title_isolated_across_scopes(self):
        first = self.store.skill_add(
            "Same title",
            "User A problem",
            "User A procedure",
            scope="101",
        )
        second = self.store.skill_add(
            "Same title",
            "User B problem",
            "User B procedure",
            scope="202",
        )

        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(self.store.skill_get(first["id"], scope="101")["scope"], "101")
        self.assertEqual(self.store.skill_get(second["id"], scope="202")["scope"], "202")

    def test_clear_only_deletes_requested_scope(self):
        self.store.add("User A fact", scope="101")
        self.store.add("User B fact", scope="202")

        self.store.clear(scope="101")

        self.assertEqual(self.store.search("fact", "101"), [])
        self.assertEqual(
            [row["content"] for row in self.store.search("fact", "202")],
            ["User B fact"],
        )

    def test_global_facts_and_skills_are_explicitly_visible(self):
        self.store.add("Shared policy", scope="global")
        self.store.add("Private note", scope="user:1")
        self.store.skill_add("Shared procedure", "shared problem", "shared steps", scope="global")
        self.store.skill_add("Local procedure", "shared problem", "local steps", scope="user:1")

        facts = self.store.get_relevant("shared", "user:1", include_global=True)
        skills = self.store.skill_inject("shared", "user:1", include_global=True)

        self.assertEqual({row["scope"] for row in facts}, {"global"})
        self.assertEqual({row["scope"] for row in skills}, {"global", "user:1"})
        self.assertEqual(self.store.search("private", "user:2", include_global=True), [])

    def test_global_crud_is_scope_locked(self):
        fact_id = self.store.global_fact_add("Shared fact")
        self.assertTrue(self.store.global_fact_delete(fact_id))
        self.assertFalse(self.store.global_fact_delete(fact_id))
        skill_id = self.store.global_skill_add("Shared skill", "problem", "procedure")["id"]
        self.assertTrue(self.store.global_skill_set_status(skill_id, "active"))
        self.assertEqual(self.store.global_skill_list()[0]["status"], "active")
        self.assertTrue(self.store.global_skill_delete(skill_id))
        self.assertFalse(self.store.global_skill_set_status(skill_id, "inactive"))

    def test_cleanup_only_deletes_low_trust_facts_in_requested_scope(self):
        self.store.add("User A low trust", scope="101")
        self.store.add("User B low trust", scope="202")
        self.store._conn.execute("UPDATE facts SET trust_score=0.1")
        self.store._conn.commit()

        self.store.cleanup_low_trust(scope="101")

        self.assertEqual(self.store.search("low trust", "101"), [])
        self.assertEqual(
            [row["content"] for row in self.store.search("low trust", "202")],
            ["User B low trust"],
        )


if __name__ == "__main__":
    unittest.main()
