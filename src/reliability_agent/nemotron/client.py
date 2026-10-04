"""Thin Nebius Token Factory client (OpenAI-compatible API) with timeout and circuit breaker.

Docs: https://docs.tokenfactory.nebius.com/quickstart ,
      https://docs.tokenfactory.nebius.com/ai-models-inference/json
The model only *proposes*; this module never executes anything returned by the model.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class CircuitOpen(RuntimeError):
    pass


@dataclass
class ChatResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    model: str


class CircuitBreaker:
    def __init__(self, failures: int = 3, open_s: float = 60.0, clock=time.monotonic) -> None:
        self.threshold = failures
        self.open_s = open_s
        self.clock = clock
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if self.clock() - self.opened_at >= self.open_s:
            self.opened_at = None  # half-open: allow one trial
            self.failures = self.threshold - 1
            return False
        return True

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = self.clock()


def extract_json_text(text: str) -> str:
    """Strip reasoning traces / markdown fences and return the outermost JSON object."""
    t = _THINK.sub("", text or "").strip()
    t = _FENCE.sub("", t).strip()
    start, end = t.find("{"), t.rfind("}")
    return t[start : end + 1] if start != -1 and end > start else t


class TokenFactoryClient:
    def __init__(self, api_key: str, base_url: str, timeout_s: float = 20.0,
                 extra_body: dict[str, Any] | None = None, breaker: CircuitBreaker | None = None,
                 sdk_client: Any = None) -> None:
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.extra_body = extra_body or {}
        self.breaker = breaker or CircuitBreaker()
        self._json_schema_supported: dict[str, bool] = {}
        if sdk_client is not None:
            self._sdk = sdk_client
        else:
            from openai import OpenAI

            self._sdk = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s,
                               max_retries=0)

    def chat_json(self, model: str, messages: list[dict[str, str]], schema: dict[str, Any],
                  temperature: float = 0.1, max_tokens: int = 600) -> ChatResult:
        if self.breaker.is_open:
            raise CircuitOpen("Token Factory circuit open; using local fallback")
        use_schema = self._json_schema_supported.get(model, True)
        rf = ({"type": "json_schema", "json_schema": {"name": "plan", "schema": schema}}
              if use_schema else {"type": "json_object"})
        t0 = time.perf_counter()
        try:
            resp = self._sdk.chat.completions.create(
                model=model, messages=messages, temperature=temperature, max_tokens=max_tokens,
                response_format=rf, extra_body=self.extra_body or None,
            )
        except Exception as exc:
            if use_schema and "response_format" in str(exc).lower():
                self._json_schema_supported[model] = False  # fall back to JSON mode once
                return self.chat_json(model, messages, schema, temperature, max_tokens)
            self.breaker.failure()
            raise
        self.breaker.success()
        usage = getattr(resp, "usage", None)
        return ChatResult(
            text=resp.choices[0].message.content or "",
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
            model=getattr(resp, "model", model) or model,
        )
