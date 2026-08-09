"""Retry + provider-failover tests for HermesBridge._call_llm."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hermes_bridge  # noqa: E402
from hermes_bridge import HermesBridge, _is_transient_llm_error  # noqa: E402


def make_settings(**overrides):
    defaults = dict(
        provider_name="router_0",
        TOOL_LOOP_MAX_ROUNDS=10,
        LLM_TIMEOUT=30,
        MAX_TOKENS=1024,
        TEMPERATURE=0.7,
        OPENCODE_ZEN_BASE_URL="https://zen.example",
        OPENROUTER_BASE_URL="https://router.example",
        ROUTER_0_BASE_URL="https://nvidia.example",
        OPENCODE_ZEN_API_KEY="zen-key",
        OPENROUTER_API_KEY="or-key",
        ROUTER_0_API_KEY="nvidia-key",
        OPENCODE_ZEN_MODEL="zen/model",
        OPENROUTER_MODEL="or/model",
        ROUTER_0_MODEL="nv/model",
        MEMORY_ENABLED=False,
        SYSTEM_PROMPT="You are a test bot.",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise hermes_bridge.httpx.HTTPStatusError(
                f"status {self.status_code}", request=None, response=self
            )

    def json(self):
        return self._payload


RESOURCE_EXHAUSTED = {
    "error": {
        "type": "server_error",
        "message": (
            "Error from provider (Console): Upstream request failed: [502] "
            "Upstream error from Nvidia: ResourceExhausted: "
            "Worker local total request limit reached (33/32)"
        ),
    }
}

AUTH_ERR = {"error": {"type": "authentication_error", "message": "invalid api key"}}


class LlmRetryTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings()
        self.bridge = HermesBridge(self.settings)
        self.bridge.initialize()

    def test_capacity_exhausted_after_all_retries_raises_friendly(self):
        # No fallback key for other providers -> no failover, raises after retries.
        self.bridge.settings = make_settings(
            OPENROUTER_API_KEY="", OPENCODE_ZEN_API_KEY=""
        )
        with mock.patch("hermes_bridge.httpx.post") as post, \
                mock.patch("hermes_bridge.time.sleep"):
            post.side_effect = [FakeResp(RESOURCE_EXHAUSTED)] * 4
            with self.assertRaises(RuntimeError) as cm:
                self.bridge.chat("hello", [])
        self.assertIn("ResourceExhausted", str(cm.exception))
        # 4 attempts for capacity class (1 initial + 3 retries)
        self.assertEqual(post.call_count, 4)

    def test_hard_auth_error_fails_fast_no_retry(self):
        with mock.patch("hermes_bridge.httpx.post") as post:
            post.side_effect = [FakeResp(AUTH_ERR)]
            with self.assertRaises(RuntimeError) as cm:
                self.bridge.chat("hello", [])
        self.assertIn("invalid api key", str(cm.exception))
        self.assertEqual(post.call_count, 1)

    def test_failover_uses_another_provider_on_exhaustion(self):
        # router_0 exhausts; openrouter key exists -> failover to openrouter, success.
        with mock.patch("hermes_bridge.httpx.post") as post, \
                mock.patch("hermes_bridge.time.sleep"):
            post.side_effect = [FakeResp(RESOURCE_EXHAUSTED)] * 4 + [
                FakeResp({"choices": [{"message": {"content": "fallback ok", "tool_calls": None}}]})
            ]
            out = self.bridge.chat("hello", [])
        self.assertEqual(out, "fallback ok")
        urls = [str(c.args[0]) for c in post.call_args_list]
        self.assertIn("https://router.example/chat/completions", urls)
        # provider restored after failover
        self.assertEqual(self.bridge._provider, "router_0")

    def test_provider_200_with_completions_returns_choices(self):
        with mock.patch("hermes_bridge.httpx.post") as post:
            post.return_value = FakeResp(
                {"choices": [{"message": {"content": "plain", "tool_calls": None}}]}
            )
            out = self.bridge.chat("hi", [])
        self.assertEqual(out, "plain")

    def test_transient_body_retried_then_success(self):
        # server_error body counts as retryable; eventual success returns content.
        with mock.patch("hermes_bridge.httpx.post") as post, \
                mock.patch("hermes_bridge.time.sleep"):
            post.side_effect = [
                FakeResp(RESOURCE_EXHAUSTED),
                FakeResp(RESOURCE_EXHAUSTED),
                FakeResp({"choices": [{"message": {"content": "ok now", "tool_calls": None}}]}),
            ]
            out = self.bridge.chat("hi", [])
        self.assertEqual(out, "ok now")
        self.assertEqual(post.call_count, 3)

    def test_is_transient_matcher(self):
        self.assertTrue(_is_transient_llm_error(RESOURCE_EXHAUSTED))
        self.assertTrue(_is_transient_llm_error({"error": {"type": "server_error"}}))
        self.assertFalse(_is_transient_llm_error(AUTH_ERR))
        self.assertFalse(_is_transient_llm_error({"error": {"message": "invalid model"}}))


if __name__ == "__main__":
    unittest.main()