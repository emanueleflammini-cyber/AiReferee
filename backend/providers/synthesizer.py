"""Validated Trusted Conclusion 2.0 synthesis.

The synthesizer receives only provider results selected by the comparison
engine. It returns a strict JSON contract, attempts one controlled repair when
the first response is invalid, and never substitutes demo or fallback text.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Iterable, Optional

from openai import AsyncOpenAI

from .base import estimate_cost
from .conclusion_schema import (
    TrustedConclusionV2,
    parse_structured_conclusion,
)
from .translator import LANG_NAMES

log = logging.getLogger(__name__)

SYNTH_MODEL = os.environ.get("SYNTH_MODEL", "gpt-5.4-mini").strip()


class SynthesisFailure(RuntimeError):
    """Safe, user-displayable Trusted Conclusion synthesis failure."""


class Synthesizer:
    """Produce a validated Trusted Conclusion 2.0."""

    def __init__(self) -> None:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.available = bool(key)
        self._client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=key) if key else None

    async def synthesize(
        self,
        prompt: str,
        answers: Iterable[dict],
        target_lang: str,
        audience: str = "professional",
        fmt: str = "paragraph",
    ) -> dict:
        """Return structured conclusion data plus usage metadata."""
        if not self._client:
            raise SynthesisFailure(
                "Trusted Conclusion is unavailable because the synthesis "
                "provider is not configured."
            )

        clean = [
            answer
            for answer in answers
            if (answer.get("text") or "").strip()
            and str(answer.get("provider_status") or "").upper() in ("LIVE", "MOCK")
        ]
        if not clean:
            raise SynthesisFailure(
                "Trusted Conclusion is unavailable because no provider "
                "returned usable evidence."
            )

        allowed_providers = sorted(
            {
                str(answer.get("provider_key") or answer.get("id") or "")
                .strip()
                .lower()
                for answer in clean
                if answer.get("provider_key") or answer.get("id")
            }
        )
        target_name = LANG_NAMES.get(target_lang, "English")
        panel_payload = [
            {
                "provider_key": answer.get("provider_key"),
                "provider_label": answer.get("label"),
                "provider_organization": answer.get("provider"),
                "provider_status": answer.get("provider_status"),
                "response": answer["text"].strip(),
            }
            for answer in clean
        ]

        schema = TrustedConclusionV2.model_json_schema()
        system = (
            "You are AI Referee's Consensus Engine. Produce a detailed, "
            "transparent Trusted Conclusion using only the supplied provider "
            "responses. Do not use outside knowledge as evidence.\n\n"
            "Return one JSON object that exactly matches the supplied schema. "
            "Do not return Markdown or prose outside the JSON.\n\n"
            f"Write every human-readable field entirely in {target_name}. "
            f"Audience: {audience}. Preferred final-answer format: {fmt}.\n\n"
            "Rules:\n"
            "- The final_answer must directly and fully answer the user.\n"
            "- Agreements require support from at least two supplied providers. "
            "With one provider, agreements must be empty.\n"
            "- Identify genuine disagreements; do not manufacture conflict.\n"
            "- supporting_models, originating_models and position.model may use "
            f"only these provider keys: {', '.join(allowed_providers)}.\n"
            "- FAILED providers are not evidence and are not supplied.\n"
            "- source_status=model_reasoning means reasoning found in a provider "
            "response; provider_citation_unverified means the provider itself "
            "mentioned a citation that AI Referee did not independently verify; "
            "no_source means no source was supplied.\n"
            "- Never claim independent verification.\n"
            "- Do not invent citations, publications, source names or URLs. "
            "Do not output any URL.\n"
            "- Confidence must be high, medium or low with a plain-language "
            "reason. Never use a numeric confidence or percentage.\n"
            "- State meaningful uncertainty when evidence is limited, especially "
            "when only one provider succeeded.\n"
            "- Avoid generic filler and repeated claims.\n"
            "- Empty optional sections must be empty arrays, not invented items."
        )
        user_message = json.dumps(
            {
                "user_question": prompt,
                "target_language": target_lang,
                "allowed_provider_keys": allowed_providers,
                "provider_responses": panel_payload,
                "required_json_schema": schema,
            },
            ensure_ascii=False,
        )

        start = time.perf_counter()
        total_input_tokens = 0
        total_output_tokens = 0
        repair_attempted = False

        raw, usage, model_used = await self._request_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ]
        )
        total_input_tokens += usage["input_tokens"]
        total_output_tokens += usage["output_tokens"]

        try:
            conclusion = parse_structured_conclusion(raw, allowed_providers)
        except Exception as first_error:  # One controlled repair is allowed.
            repair_attempted = True
            raw, usage, repair_model = await self._request_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "Repair the JSON so it exactly matches the provided "
                            "Trusted Conclusion schema. Do not add facts, sources "
                            "or URLs. Preserve the requested language. Return only "
                            "the repaired JSON object."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "allowed_provider_keys": allowed_providers,
                                "required_json_schema": schema,
                                "validation_error": (
                                    f"{type(first_error).__name__}: "
                                    f"{str(first_error)[:1500]}"
                                ),
                                "invalid_output": raw[:20000],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
            )
            total_input_tokens += usage["input_tokens"]
            total_output_tokens += usage["output_tokens"]
            model_used = repair_model or model_used
            try:
                conclusion = parse_structured_conclusion(raw, allowed_providers)
            except Exception as repair_error:
                log.warning(
                    "Trusted Conclusion validation failed after repair: %s",
                    type(repair_error).__name__,
                )
                raise SynthesisFailure(
                    "Trusted Conclusion could not be validated after one repair "
                    "attempt."
                ) from repair_error

        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "text": conclusion.final_answer,
            "structured_conclusion": conclusion.model_dump(),
            "schema_version": conclusion.schema_version,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "latency_ms": latency_ms,
            "cost_usd": estimate_cost(
                model_used,
                total_input_tokens,
                total_output_tokens,
            ),
            "model_used": model_used,
            "language": target_lang,
            "repair_attempted": repair_attempted,
        }

    async def _request_json(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[str, dict[str, int], str]:
        try:
            response = await self._client.chat.completions.create(
                model=SYNTH_MODEL,
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # Never expose raw provider errors or secrets.
            log.warning(
                "Trusted Conclusion provider request failed: %s",
                type(exc).__name__,
            )
            raise SynthesisFailure(
                "Trusted Conclusion synthesis provider is currently unavailable."
            ) from exc

        raw = (response.choices[0].message.content or "").strip()
        usage = response.usage
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        model_used = getattr(response, "model", SYNTH_MODEL) or SYNTH_MODEL
        return (
            raw,
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            model_used,
        )
