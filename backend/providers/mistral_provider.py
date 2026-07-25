"""Real Mistral provider using the official chat-completions REST API."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from .base import Provider, ProviderResult, ProviderTimeoutError

log = logging.getLogger(__name__)

MISTRAL_CHAT_COMPLETIONS_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODEL = "mistral-small-latest"
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_RETRIES = 2

SYSTEM_FALLBACK = (
    "You are one participant in a multi-model AI consensus panel called AI Referee. "
    "Answer the user's question directly, precisely, and with your best reasoning. "
    "Keep the answer self-contained - the panel synthesises multiple answers afterwards."
)


class MistralProvider(Provider):
    """Mistral implementation with an isolated timeout and bounded retries."""

    id = "model-e"
    label = "Mistral"
    codename = DEFAULT_MODEL
    provider_name = "Mistral AI"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__()
        self.model = (
            model
            or os.environ.get("MISTRAL_MODEL", "").strip()
            or DEFAULT_MODEL
        )
        self.codename = self.model
        self.api_key = (api_key or os.environ.get("MISTRAL_API_KEY", "")).strip()
        self.timeout_seconds = _positive_float(
            timeout_seconds,
            os.environ.get("MISTRAL_TIMEOUT_SECONDS"),
            DEFAULT_TIMEOUT_SECONDS,
        )
        self.max_retries = _non_negative_int(
            max_retries,
            os.environ.get("MISTRAL_MAX_RETRIES"),
            DEFAULT_MAX_RETRIES,
        )
        self._transport = transport
        self.available = bool(self.api_key)

    async def generate(self, prompt: str, system: str = "") -> ProviderResult:
        if not self.available:
            raise RuntimeError("MISTRAL_API_KEY is missing - cannot call Mistral")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or SYSTEM_FALLBACK},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        start = time.perf_counter()

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout_seconds),
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        MISTRAL_CHAT_COMPLETIONS_URL,
                        headers=headers,
                        json=payload,
                    )

                if _is_transient(response.status_code):
                    if attempt < self.max_retries:
                        _log_retry(response.status_code, attempt, self.max_retries)
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue
                    raise RuntimeError(
                        "Mistral API remained unavailable after retries "
                        f"(HTTP {response.status_code})"
                    )

                if response.status_code in (401, 403):
                    raise RuntimeError(
                        "Mistral authentication failed - check MISTRAL_API_KEY"
                    )
                if response.is_error:
                    raise RuntimeError(
                        f"Mistral API request failed (HTTP {response.status_code})"
                    )

                data = response.json()
                return _provider_result(
                    data,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    fallback_model=self.model,
                )
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    _log_retry("timeout", attempt, self.max_retries)
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise ProviderTimeoutError(
                    f"Mistral exceeded the {self.timeout_seconds:g}s timeout"
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    _log_retry(type(exc).__name__, attempt, self.max_retries)
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise RuntimeError(
                    f"Mistral network request failed ({type(exc).__name__})"
                ) from exc

        raise RuntimeError("Mistral request did not complete")


def _provider_result(
    data: dict[str, Any],
    *,
    latency_ms: int,
    fallback_model: str,
) -> ProviderResult:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Mistral returned no response choices")
    message = (choices[0] or {}).get("message") or {}
    text = _message_text(message.get("content")).strip()
    usage = data.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(
        usage.get("total_tokens") or (input_tokens + output_tokens)
    )
    return ProviderResult(
        text=text,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        model_used=str(data.get("model") or fallback_model),
        is_mock=False,
        citation_metadata=[],
    )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _is_transient(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _log_retry(reason: object, attempt: int, max_retries: int) -> None:
    log.warning(
        "Mistral transient request failure (%s); retry %d/%d",
        reason,
        attempt + 1,
        max_retries,
    )


def _positive_float(
    explicit: float | None,
    configured: str | None,
    default: float,
) -> float:
    try:
        value = float(explicit if explicit is not None else configured or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _non_negative_int(
    explicit: int | None,
    configured: str | None,
    default: int,
) -> int:
    try:
        value = int(explicit if explicit is not None else configured or default)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default
