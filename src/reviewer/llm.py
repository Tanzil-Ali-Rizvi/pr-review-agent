"""Chat completions. By default through my llm-gateway project, embedded in-process (Groq gpt-oss-120b, retries,
fallback and cost tracking); `HTTPLLM` talks to any OpenAI-compatible endpoint; `ScriptedLLM` replays answers in tests.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass
class LLMReply:
    ok: bool
    text: str = ""
    model: str = ""
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    tokens: int = 0
    error: str = ""


class LLM(Protocol):
    name: str

    async def complete(self, system: str, user: str) -> LLMReply: ...


def _body(model: str, system: str, user: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 2500,
        "reasoning_effort": "medium",
        "response_format": {"type": "json_object"},
    }


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


class GatewayLLM:
    name = "Groq gpt-oss via llm-gateway"

    def __init__(self, route: str = "review", max_retry_after_s: float = 30):
        from llmgw.config import GatewayConfig
        from llmgw.gateway import Gateway

        cfg = GatewayConfig.model_validate(
            {
                "providers": {
                    "groq": {
                        "type": "openai",
                        "base_url": "https://api.groq.com/openai/v1",
                        "api_key_env": "GROQ_API_KEY",
                        "timeout_s": 90,
                        "models": {
                            "openai/gpt-oss-120b": {
                                "input_per_1m": 0.15,
                                "output_per_1m": 0.60,
                            },
                            "openai/gpt-oss-20b": {
                                "input_per_1m": 0.075,
                                "output_per_1m": 0.30,
                            },
                        },
                    }
                },
                "routes": {
                    "review": ["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-20b"],
                    "eval": ["groq/openai/gpt-oss-120b"],  # one model, no fallback: results stay attributable
                },
                "default_route": route,
                "database": ":memory:",
                "require_auth": False,
                "retry": {
                    "attempts_per_target": 4,
                    "backoff_s": 1.0,
                    "max_retry_after_s": max_retry_after_s,
                },
                "cache": {"enabled": False},
            }
        )
        self.route = route
        self.gw = Gateway(cfg)

    async def complete(self, system: str, user: str) -> LLMReply:
        from llmgw.gateway import GatewayError

        t0 = time.perf_counter()
        try:
            out = await self.gw.chat(_body(self.route, system, user), None)
        except GatewayError as e:
            return LLMReply(False, error=f"{e.status}: {e.message}"[:300], latency_ms=_ms(t0))
        body = out.body or {}
        msg = (body.get("choices") or [{}])[0].get("message", {}) or {}
        return LLMReply(
            True,
            msg.get("content") or "",
            out.headers.get("x-gateway-target", ""),
            float(out.headers.get("x-gateway-cost-usd", 0) or 0),
            _ms(t0),
            int((body.get("usage") or {}).get("total_tokens", 0)),
        )


class HTTPLLM:
    name = "OpenAI-compatible HTTP"

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    async def complete(self, system: str, user: str) -> LLMReply:
        t0 = time.perf_counter()
        body = _body(self.model, system, user)
        body.pop("reasoning_effort")
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(f"{self.base_url}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {self.api_key}"})  # fmt: skip
            r.raise_for_status()
        except httpx.HTTPError as e:
            return LLMReply(False, error=str(e)[:300], latency_ms=_ms(t0))
        data = r.json()
        return LLMReply(True, data["choices"][0]["message"].get("content") or "", self.model, latency_ms=_ms(t0),
                        tokens=int((data.get("usage") or {}).get("total_tokens", 0)))  # fmt: skip


class ScriptedLLM:
    """Replays fixed answers (str or dict) in order; records every prompt it was sent."""

    name = "scripted"

    def __init__(self, script: list[Any]):
        self.script = list(script)
        self.seen: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> LLMReply:
        self.seen.append((system, user))
        if not self.script:
            return LLMReply(False, error="script exhausted")
        step = self.script.pop(0)
        return LLMReply(True, step if isinstance(step, str) else json.dumps(step), "scripted")


def parse_json(text: str) -> dict[str, Any] | None:
    """The first JSON object in a reply (models sometimes wrap it in prose or a code fence)."""
    text = (text or "").strip()
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def from_env(route: str = "review") -> LLM | None:
    if os.getenv("LLM_BASE_URL"):
        return HTTPLLM(
            os.environ["LLM_BASE_URL"],
            os.getenv("LLM_API_KEY", ""),
            os.getenv("LLM_MODEL", "gpt-4o-mini"),
        )
    if os.getenv("GROQ_API_KEY"):
        return GatewayLLM(route)
    return None
