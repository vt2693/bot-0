"""Small deterministic retrieval benchmark for MemoryStore."""
from __future__ import annotations
import hashlib
import math
import re
from collections.abc import Iterable

BENCHMARK_FACTS = [
    {"key": "router-fact", "scope": "chat-a", "content": "Router-0 uses combo-medium as the default model."},
    {"key": "route-fact", "scope": "chat-a", "content": "The Telegram bot routes scheduled jobs through the local scheduler."},
    {"key": "other-user-route", "scope": "chat-b", "content": "The other user routes requests through a private scheduler."},
    {"key": "noise-fact", "scope": "chat-a", "content": "The deployment uses a local Android environment."},
]
BENCHMARK_CASES = [
    {"id": "exact-router", "query": "Router-0 combo-medium", "scope": "chat-a", "relevant": ["router-fact"]},
    {"id": "paraphrase-routing", "query": "How does the bot send scheduled tasks?", "scope": "chat-a", "relevant": ["route-fact"]},
    {"id": "scope-isolation", "query": "private scheduler routes", "scope": "chat-a", "relevant": ["route-fact"]},
]
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)

class DeterministicEmbedder:
    dimensions = 128
    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))

def lexical_retrieve(store, query: str, scope: str, limit: int = 5) -> list[dict]:
    terms = [term for term in _TOKEN_RE.findall(query) if len(term) > 2]
    rows, seen = [], set()
    for term in terms:
        for row in store.search(term, scope, limit):
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
    return rows[:limit]

def hybrid_retrieve(store, query: str, scope: str, limit: int, embedder: DeterministicEmbedder, top_k: int = 20) -> list[dict]:
    candidates = store.search("", scope, top_k)
    query_vector = embedder.embed(query)
    ranked = sorted(candidates, key=lambda row: _cosine(query_vector, embedder.embed(row["content"])), reverse=True)
    return ranked[:limit]

def _metrics(results: Iterable[dict], relevant_keys: set[str], k: int) -> dict:
    selected = list(results)[:k]
    hits = sum(row["metadata"].get("key") in relevant_keys for row in selected)
    return {"precision_at_k": hits / k if k else 0.0, "recall_at_k": hits / len(relevant_keys) if relevant_keys else 0.0}

def evaluate_retrievers(store, cases: list[dict], fact_ids: dict[str, int], embedder: DeterministicEmbedder, k: int = 3) -> dict:
    totals = {"lexical": [], "hybrid": []}
    for case in cases:
        relevant = set(case["relevant"])
        totals["lexical"].append(_metrics(lexical_retrieve(store, case["query"], case["scope"], k), relevant, k))
        totals["hybrid"].append(_metrics(hybrid_retrieve(store, case["query"], case["scope"], k, embedder, top_k=10), relevant, k))
    return {name: {metric: sum(item[metric] for item in values) / len(values) for metric in ("precision_at_k", "recall_at_k")} for name, values in totals.items()}
