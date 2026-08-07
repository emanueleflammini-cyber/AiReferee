"""Offline diagnostics tests for failed Synthesizer attempts."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.base import estimate_cost  # noqa: E402
from providers.synthesizer import SynthesisFailure, Synthesizer  # noqa: E402


def _valid_conclusion(**overrides):
    payload = {
        "schema_version": "2.0",
        "final_answer": "A validated combined answer.",
        "agreements": [],
        "disagreements": [],
        "strongest_evidence": [],
        "remaining_uncertainties": [],
        "unsupported_claims": [],
        "confidence": {
            "level": "medium",
            "reason": "Evidence is limited to the current provider panel.",
            "factors": {
                "model_agreement": "low",
                "evidence_quality": "medium",
                "uncertainty": "medium",
            },
        },
        "what_could_change_the_verdict": [],
    }
    payload.update(overrides)
    return payload


def _invalid_conclusion():
    return _valid_conclusion(
        final_answer="SECRET_OUTPUT https://private.example/path",
        confidence={
            "level": "SECRET_INVALID_LEVEL",
            "reason": "SECRET_PROVIDER_RESPONSE",
            "factors": {
                "model_agreement": "low",
                "evidence_quality": "medium",
                "uncertainty": "medium",
            },
        },
    )


def _answer():
    return {
        "id": "model-a",
        "provider_key": "openai",
        "provider_response_id": "response-openai",
        "label": "ChatGPT",
        "provider": "OpenAI",
        "provider_status": "LIVE",
        "text": "SECRET_PROVIDER_RESPONSE",
    }


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        spec = next(self.responses)
        await asyncio.sleep(spec.get("delay", 0))
        choice = SimpleNamespace(
            message=SimpleNamespace(content=spec["output"])
        )
        if "finish_reason" in spec:
            choice.finish_reason = spec["finish_reason"]
        response = SimpleNamespace(
            choices=[choice],
            usage=(
                SimpleNamespace(
                    prompt_tokens=spec.get("input_tokens", 0),
                    completion_tokens=spec.get("output_tokens", 0),
                    total_tokens=spec.get("total_tokens"),
                )
                if spec.get("with_usage", True)
                else None
            ),
            model=spec.get("model", "gpt-5.4-mini"),
        )
        if "request_id" in spec:
            response._request_id = spec["request_id"]
        return response


def _synthesizer(responses):
    synth = Synthesizer.__new__(Synthesizer)
    completions = FakeCompletions(responses)
    synth.available = True
    synth._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return synth, completions


def _run(synth, *, query_id="diagnostics-query"):
    return asyncio.run(
        synth.synthesize(
            "SECRET_USER_PROMPT",
            [_answer()],
            "en",
            correlation_id=query_id,
        )
    )


def test_validation_error_logging_is_structured_bounded_and_private(caplog):
    synth, _ = _synthesizer(
        [
            {"output": json.dumps(_invalid_conclusion())},
            {"output": json.dumps(_valid_conclusion())},
        ]
    )

    with caplog.at_level(logging.INFO):
        _run(synth, query_id="validation-1")

    event = next(
        line for line in caplog.text.splitlines()
        if "synthesis_validation_error" in line
    )
    assert "query_id=validation-1" in event
    assert "stage=initial" in event
    assert "error_count=1" in event
    assert '"location":"confidence.level"' in event
    assert '"type":"literal_error"' in event
    assert '"code":"pydantic.literal_error"' in event
    for forbidden in (
        "SECRET_USER_PROMPT",
        "SECRET_PROVIDER_RESPONSE",
        "SECRET_OUTPUT",
        "SECRET_INVALID_LEVEL",
        "private.example",
        "https://",
        "sk-test-secret",
    ):
        assert forbidden not in caplog.text


def test_validation_error_log_caps_items_and_redacts_unknown_field_names(caplog):
    invalid = _valid_conclusion()
    for index in range(25):
        invalid[f"SECRET_FIELD_{index}"] = "SECRET_VALUE"
    synth, _ = _synthesizer(
        [
            {"output": json.dumps(invalid)},
            {"output": json.dumps(_valid_conclusion())},
        ]
    )

    with caplog.at_level(logging.INFO):
        _run(synth, query_id="validation-cap")

    event = next(
        line for line in caplog.text.splitlines()
        if "synthesis_validation_error" in line
    )
    assert "error_count=25" in event
    assert event.count('"location"') == 20
    assert "<unknown_field>" in event
    assert "SECRET_FIELD_" not in caplog.text
    assert "SECRET_VALUE" not in caplog.text


def test_initial_invalid_repair_valid_accumulates_usage_cost_and_metadata(caplog):
    synth, completions = _synthesizer(
        [
            {
                "output": json.dumps(_invalid_conclusion()),
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "request_id": "req_initial",
                "finish_reason": "stop",
            },
            {
                "output": json.dumps(_valid_conclusion()),
                "input_tokens": 140,
                "output_tokens": 30,
                "total_tokens": 170,
                "request_id": "req_repair",
                "finish_reason": "stop",
            },
        ]
    )

    with caplog.at_level(logging.INFO):
        result = _run(synth)

    assert completions.calls == 2
    assert result["repair_attempted"] is True
    assert result["input_tokens"] == 240
    assert result["output_tokens"] == 50
    assert result["total_tokens"] == 290
    assert result["cost_usd"] == pytest.approx(
        estimate_cost("gpt-5.4-mini", 100, 20)
        + estimate_cost("gpt-5.4-mini", 140, 30)
    )
    assert [item["stage"] for item in result["attempt_metadata"]] == [
        "initial",
        "repair",
    ]
    assert result["attempt_metadata"][0]["request_id"] == "req_initial"
    assert result["attempt_metadata"][1]["finish_reason"] == "stop"
    assert "stage=initial request_id=req_initial finish_reason=stop" in caplog.text
    assert "stage=repair request_id=req_repair finish_reason=stop" in caplog.text


def test_two_validation_errors_preserve_failed_attempt_telemetry(caplog):
    specs = [
        {
            "output": json.dumps(_invalid_conclusion()),
            "input_tokens": 101,
            "output_tokens": 21,
            "total_tokens": 122,
            "delay": 0.002,
        },
        {
            "output": json.dumps(_invalid_conclusion()),
            "input_tokens": 151,
            "output_tokens": 31,
            "total_tokens": 182,
            "delay": 0.002,
        },
    ]
    synth, completions = _synthesizer(specs)

    with caplog.at_level(logging.INFO), pytest.raises(SynthesisFailure) as raised:
        _run(synth, query_id="failed-1")

    telemetry = raised.value.telemetry
    assert completions.calls == 2
    assert telemetry["model_used"] == "gpt-5.4-mini"
    assert telemetry["input_tokens"] == 252
    assert telemetry["output_tokens"] == 52
    assert telemetry["total_tokens"] == 304
    assert telemetry["latency_ms"] > 0
    assert telemetry["cost_usd"] > 0
    assert telemetry["repair_attempted"] is True
    assert len(telemetry["attempts"]) == 2
    assert "stage=initial" in caplog.text
    assert "stage=repair" in caplog.text
    assert "synthesis_failed_attempt_totals query_id=failed-1" in caplog.text
    assert "failed_synthesis_total_ms=" in caplog.text
    assert "synthesis_salvage_completed query_id=failed-1 stage=initial status=FAILED" in caplog.text
    assert "synthesis_salvage_completed query_id=failed-1 stage=repair status=FAILED" in caplog.text


def test_salvage_success_event_and_behavior_are_unchanged(caplog):
    invalid_claim_bundle = {
        "trusted_conclusion": _valid_conclusion(),
        "claim_analysis": {"SECRET_UNKNOWN_FIELD": "SECRET_VALUE"},
    }
    synth, _ = _synthesizer(
        [
            {"output": json.dumps(invalid_claim_bundle)},
            {"output": json.dumps(invalid_claim_bundle)},
        ]
    )

    with caplog.at_level(logging.INFO):
        result = _run(synth, query_id="salvage-1")

    assert result["text"] == "A validated combined answer."
    assert result["repair_attempted"] is True
    assert result["claim_analysis_status"] == "FAILED"
    assert "synthesis_salvage_completed query_id=salvage-1 stage=initial status=SUCCESS" in caplog.text
    assert "synthesis_salvage_completed query_id=salvage-1 stage=repair status=SUCCESS" in caplog.text
    assert "SECRET_UNKNOWN_FIELD" not in caplog.text
    assert "SECRET_VALUE" not in caplog.text


@pytest.mark.parametrize("metadata_present", [True, False])
def test_openai_metadata_is_optional_and_never_reads_content(
    metadata_present,
    caplog,
):
    spec = {
        "output": json.dumps(_valid_conclusion()),
        "input_tokens": 3,
        "output_tokens": 4,
        "total_tokens": 7,
    }
    if metadata_present:
        spec.update(request_id="req_metadata", finish_reason="length")
    else:
        spec["with_usage"] = False
    synth, _ = _synthesizer([spec])

    with caplog.at_level(logging.INFO):
        result = _run(synth, query_id="metadata-1")

    if metadata_present:
        assert result["total_tokens"] == 7
        assert "request_id=req_metadata" in caplog.text
        assert "finish_reason=length" in caplog.text
    else:
        assert result["total_tokens"] == 0
        assert "request_id=unavailable" in caplog.text
        assert "finish_reason=unavailable" in caplog.text
    assert "A validated combined answer." not in caplog.text


def test_prompt_dimension_logs_are_numeric_only(caplog):
    synth, _ = _synthesizer(
        [
            {"output": json.dumps(_invalid_conclusion())},
            {"output": json.dumps(_valid_conclusion())},
        ]
    )

    with caplog.at_level(logging.INFO):
        _run(synth, query_id="dimensions-1")

    initial = next(
        line for line in caplog.text.splitlines()
        if "synthesis_prompt_dimensions" in line and "stage=initial" in line
    )
    repair = next(
        line for line in caplog.text.splitlines()
        if "synthesis_prompt_dimensions" in line and "stage=repair" in line
    )
    for key in (
        "system_prompt_chars",
        "schema_chars",
        "panel_payload_chars",
        "request_prompt_chars",
    ):
        assert key in initial
    for key in (
        "schema_chars",
        "panel_payload_chars",
        "invalid_output_chars",
        "repair_prompt_chars",
    ):
        assert key in repair
    assert "SECRET_USER_PROMPT" not in caplog.text
    assert "SECRET_PROVIDER_RESPONSE" not in caplog.text
