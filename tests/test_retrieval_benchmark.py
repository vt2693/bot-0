import unittest

from memory_store import MemoryStore
from retrieval_benchmark import (
    BENCHMARK_CASES,
    BENCHMARK_FACTS,
    DeterministicEmbedder,
    evaluate_retrievers,
    hybrid_retrieve,
    lexical_retrieve,
)


class RetrievalBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(":memory:")
        self.fact_ids = {}
        for fact in BENCHMARK_FACTS:
            self.fact_ids[fact["key"]] = self.store.add(
                fact["content"], fact["scope"], {"key": fact["key"]}
            )
        self.embedder = DeterministicEmbedder()

    def tearDown(self):
        self.store._conn.close()

    def test_lexical_baseline_uses_real_scoped_memory_search(self):
        case = next(c for c in BENCHMARK_CASES if c["id"] == "exact-router")
        result = lexical_retrieve(self.store, case["query"], case["scope"], 3)
        self.assertIn(self.fact_ids["router-fact"], [row["id"] for row in result])

    def test_get_relevant_searches_first_ten_words(self):
        queried = []
        original_search = self.store.search

        def record_search(term, scope="global", limit=5):
            queried.append(term)
            return original_search(term, scope, limit)

        self.store.search = record_search
        query = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november"

        self.store.get_relevant(query, scope="chat-a", limit=1)

        self.assertEqual(queried, query.split()[:10])

    def test_deterministic_hybrid_ranks_semantic_fixture_match(self):
        case = next(c for c in BENCHMARK_CASES if c["id"] == "paraphrase-routing")
        results = hybrid_retrieve(
            self.store, case["query"], case["scope"], 3, self.embedder, top_k=6
        )
        self.assertEqual(results[0]["metadata"]["key"], "route-fact")

    def test_hybrid_never_returns_facts_from_another_scope(self):
        case = next(c for c in BENCHMARK_CASES if c["id"] == "scope-isolation")
        results = hybrid_retrieve(
            self.store, case["query"], case["scope"], 10, self.embedder, top_k=10
        )
        self.assertTrue(all(row["scope"] == case["scope"] for row in results))
        self.assertNotIn(self.fact_ids["other-user-route"], [row["id"] for row in results])

    def test_benchmark_reports_precision_and_recall_at_k(self):
        report = evaluate_retrievers(
            self.store, BENCHMARK_CASES, self.fact_ids, self.embedder, k=3
        )
        self.assertEqual(set(report), {"lexical", "hybrid"})
        for method in report.values():
            self.assertIn("precision_at_k", method)
            self.assertIn("recall_at_k", method)
            self.assertTrue(0 <= method["precision_at_k"] <= 1)
            self.assertTrue(0 <= method["recall_at_k"] <= 1)


if __name__ == "__main__":
    unittest.main()
