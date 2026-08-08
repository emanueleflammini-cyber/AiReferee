"""Early synthesis orchestration — quorum + grace window + late-arriving
background providers (Early Synthesis Patch 2).

Pure asyncio orchestration, deliberately decoupled from server.py/MongoDB:
this module knows nothing about queries, persistence, or FastAPI. It reads
only ProviderPolicy / QuorumPolicy (providers/policy.py, Patch 1) and the
PROVIDER_STATUS_* constants (providers/base.py, Patch 1). server.py's
compare_query is the only caller today, and owns everything specific to a
request (query_id, persistence, the HTTP response, and its own logging for
what happens to a late-arriving result).

Algorithm: start every provider as an `asyncio.Task`, then drain
completions with `asyncio.wait(..., return_when=FIRST_COMPLETED)` in a
loop — never `asyncio.gather()`, which cannot hand back control before
every task is finished. The moment the configured quorum is satisfied, a
grace window opens; once it expires (or every remaining task finishes
first, whichever happens sooner), the loop stops WAITING but never CANCELS
anything still running. Those tasks keep executing on the event loop; each
is guaranteed to have its result (or, defensively, its exception) consumed
by a done-callback that also drops this module's own anti-garbage-
collection reference (see `_BACKGROUND_TASKS` and the asyncio docs for
`create_task`: "Save a reference to the result of this function, to avoid
a task disappearing mid-execution").

If quorum is never satisfied, the loop behaves exactly like the previous
`asyncio.gather()` call: it waits for every provider to finish (bounded
only by each provider's own existing timeout, unchanged), and returns with
`late_tasks` empty — this is what keeps the "no quorum" and "3 fast
providers" paths byte-for-byte equivalent to the prior behaviour.

Observability (perf/request-timeline-observability, purely additive): every
log line now carries `query_id` (via the optional `correlation_id`
parameter — never threaded into Provider.timed_generate/generate, whose
shared signatures are untouched), plus `early_synthesis_disagreement_gate_result`
(similarity score / threshold / pass-fail, never response text),
`early_synthesis_time_to_first_provider_ms`, `early_synthesis_provider_
execution_started`, and `grace_window_actual_ms`. None of this changes the
quorum/grace/disagreement decision logic itself — same comparisons, same
thresholds, same control flow, only new log statements alongside them.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from .base import PROVIDER_STATUS_LIVE, Provider, ProviderResult
from .policy import ProviderPolicy, QuorumPolicy, get_provider_policy

log = logging.getLogger(__name__)

# Strong references to background ("late-arriving") tasks and their
# persistence follow-ups, so neither is ever garbage-collected once the
# main compare_query await loop below stops tracking them. Each entry is
# removed by its own done-callback as soon as it completes — this set never
# grows unbounded across requests.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


@dataclass
class QuorumRunResult:
    """Outcome of run_providers_with_quorum for one compare_query call."""

    # provider_id -> finalized ProviderResult (LIVE/FAILED/MOCK) for every
    # provider that completed before the cutoff (quorum + grace window —
    # or, if quorum was never reached, every provider, exactly like the
    # previous asyncio.gather behaviour).
    finalized: dict[str, ProviderResult]
    # provider_id -> asyncio.Task still running when the cutoff happened.
    # Empty in the common "quorum never reached" / "everyone finished
    # within the grace window" cases — those behave exactly as before.
    late_tasks: dict[str, "asyncio.Task[ProviderResult]"]
    # True iff a quorum was reached and the caller is proceeding without
    # every provider (i.e. late_tasks is non-empty).
    early_synthesis: bool
    quorum_reached_at_ms: Optional[int]
    grace_window_seconds: float
    # fix/early-synthesis-disagreement-bounded-wait: milliseconds actually
    # spent in the bounded disagreement wait (raw quorum satisfied, gate
    # failed, waiting for a still-pending provider). 0 whenever that wait
    # never started (gate passed immediately, raw quorum never reached, or
    # no similarity_fn supplied). Purely observational — never read back
    # into any decision.
    disagreement_wait_actual_ms: int = 0


async def run_providers_with_quorum(
    providers: list[Provider],
    prompt: str,
    system: str,
    quorum_policy: QuorumPolicy,
    provider_policy_lookup: Callable[[str], ProviderPolicy] = get_provider_policy,
    similarity_fn: Optional[Callable[[str, str], float]] = None,
    on_late_complete: Optional[Callable[[str, ProviderResult], Awaitable[None]]] = None,
    correlation_id: Optional[str] = None,
) -> QuorumRunResult:
    """Run every provider in parallel; stop waiting once quorum + grace allow it.

    `similarity_fn(text_a, text_b) -> float in [0, 1]` is the injected
    disagreement heuristic. server.py supplies `lambda a, b: jaccard(tokens_of(a),
    tokens_of(b))` — the exact functions Smart Reuse already uses — so this
    module never imports server.py (avoiding a circular import) and never
    duplicates that logic. If `None`, the disagreement gate is skipped
    entirely (treated as "always agreeing enough").

    `on_late_complete(provider_id, result)` is an async callable invoked,
    as its own tracked background task, the moment a late task finishes —
    after this module's own bookkeeping (log + anti-GC cleanup) has already
    run. Any exception it raises is logged and swallowed, so a persistence
    failure in the caller can never leave this module's own housekeeping
    incomplete. Never called for providers that finished before the cutoff
    (those are in `finalized`, no callback fires for them).

    `correlation_id` (observability-only — see the perf/request-timeline-
    observability patch report): server.py passes its `query_id` so every
    log line below can be correlated to one compare_query call, without
    threading query_id through Provider.timed_generate/generate — those
    shared adapter signatures are untouched. Purely additive: logging only,
    no effect on quorum/grace/disagreement decisions.
    """
    cid = correlation_id or "unknown"
    if not providers:
        return QuorumRunResult(
            finalized={},
            late_tasks={},
            early_synthesis=False,
            quorum_reached_at_ms=None,
            grace_window_seconds=quorum_policy.grace_window_seconds,
        )

    started_at = time.perf_counter()
    tasks: dict[asyncio.Task, str] = {
        asyncio.create_task(provider.timed_generate(prompt, system)): provider.id
        for provider in providers
    }
    log.info(
        "early_synthesis_provider_execution_started query_id=%s provider_ids=%s "
        "provider_count=%d",
        cid, sorted(tasks.values()), len(tasks),
    )

    pending: set[asyncio.Task] = set(tasks.keys())
    finalized: dict[str, ProviderResult] = {}
    quorum_deadline: Optional[float] = None
    quorum_reached_at_ms: Optional[int] = None
    grace_window_started_at: Optional[float] = None
    first_provider_logged = False
    raw_quorum_logged = False
    # fix/early-synthesis-disagreement-bounded-wait: separate, bounded
    # deadline for "raw quorum satisfied but the disagreement gate failed"
    # — distinct from quorum_deadline (the grace window after a full
    # SEMANTIC quorum, i.e. raw quorum AND gate passed). The two are never
    # both active at once: reaching semantic quorum always clears this one
    # first. See _raw_quorum_satisfied / _disagreement_gate_result below
    # for the raw-vs-semantic distinction itself.
    disagreement_deadline: Optional[float] = None
    disagreement_wait_started_at: Optional[float] = None
    disagreement_wait_actual_ms = 0
    last_gate_score: Optional[float] = None
    last_gate_live_ids: Optional[tuple[str, str]] = None

    while pending:
        wait_timeout: Optional[float] = None
        active_deadline = quorum_deadline if quorum_deadline is not None else disagreement_deadline
        if active_deadline is not None:
            wait_timeout = max(0.0, active_deadline - time.perf_counter())

        done, pending = await asyncio.wait(
            pending, timeout=wait_timeout, return_when=asyncio.FIRST_COMPLETED,
        )

        for task in done:
            provider_id = tasks[task]
            try:
                result = task.result()
            except Exception as exc:  # noqa: BLE001 — defence in depth; timed_generate never raises today.
                log.exception(
                    "early_synthesis_provider_task_unexpected_exception "
                    "query_id=%s provider_id=%s",
                    cid, provider_id,
                )
                result = ProviderResult(text="", provider_status="FAILED", error=str(exc)[:200])
            # A finished task (LIVE or FAILED) is removed from `pending`
            # right here, by asyncio.wait itself, before this loop body
            # runs — a FAILED provider can therefore never be mistaken for
            # "still pending" anywhere below (item 2's requirement).
            finalized[provider_id] = result
            if not first_provider_logged:
                first_provider_logged = True
                log.info(
                    "early_synthesis_time_to_first_provider_ms query_id=%s "
                    "provider_id=%s time_to_first_provider_ms=%d",
                    cid, provider_id, int((time.perf_counter() - started_at) * 1000),
                )
            log.info(
                "early_synthesis_provider_finalized query_id=%s provider_id=%s "
                "status=%s duration_ms=%d before_quorum=%s",
                cid, provider_id, result.provider_status, result.latency_ms,
                quorum_deadline is None,
            )

        if quorum_deadline is None:
            raw_ok = _raw_quorum_satisfied(finalized, provider_policy_lookup, quorum_policy)
            if raw_ok and not raw_quorum_logged:
                raw_quorum_logged = True
                log.info(
                    "early_synthesis_raw_quorum_reached query_id=%s elapsed_ms=%d "
                    "live_count=%d",
                    cid, int((time.perf_counter() - started_at) * 1000),
                    len(_live_quorum_eligible_ids(finalized, provider_policy_lookup)),
                )

            if raw_ok:
                gate_passed, gate_score, gate_live_ids = _disagreement_gate_result(
                    finalized, provider_policy_lookup, quorum_policy, similarity_fn, cid,
                )
                if gate_score is not None:
                    last_gate_score = gate_score
                    last_gate_live_ids = gate_live_ids

                if gate_passed:
                    # SEMANTIC quorum reached (raw quorum + gate passed, or
                    # the gate does not apply — e.g. 3+ LIVE already).
                    if disagreement_deadline is not None:
                        disagreement_wait_actual_ms = int(
                            (time.perf_counter() - disagreement_wait_started_at) * 1000
                        )
                        log.info(
                            "early_synthesis_disagreement_wait_completed query_id=%s "
                            "reason=third_provider_arrived wait_actual_ms=%d",
                            cid, disagreement_wait_actual_ms,
                        )
                        disagreement_deadline = None
                    quorum_reached_at_ms = int((time.perf_counter() - started_at) * 1000)
                    live_count = sum(
                        1 for r in finalized.values() if r.provider_status == PROVIDER_STATUS_LIVE
                    )
                    log.info(
                        "early_synthesis_quorum_reached query_id=%s elapsed_ms=%d live_count=%d",
                        cid, quorum_reached_at_ms, live_count,
                    )
                    if quorum_policy.grace_window_seconds > 0:
                        grace_window_started_at = time.perf_counter()
                        log.info(
                            "early_synthesis_grace_window_started query_id=%s "
                            "grace_window_seconds=%g",
                            cid, quorum_policy.grace_window_seconds,
                        )
                    quorum_deadline = time.perf_counter() + quorum_policy.grace_window_seconds
                elif pending:
                    # Raw quorum met, gate failed, and at least one provider
                    # is still pending: give it a bounded chance (item 1/2)
                    # to arrive and help resolve the disagreement.
                    if disagreement_deadline is None:
                        disagreement_wait_started_at = time.perf_counter()
                        disagreement_deadline = (
                            disagreement_wait_started_at
                            + quorum_policy.disagreement_wait_seconds
                        )
                        log.info(
                            "early_synthesis_disagreement_wait_started query_id=%s "
                            "wait_seconds=%g live_count=%d pending_count=%d",
                            cid, quorum_policy.disagreement_wait_seconds,
                            len(_live_quorum_eligible_ids(finalized, provider_policy_lookup)),
                            len(pending),
                        )
                else:
                    # Raw quorum met, gate failed, and nothing is left
                    # pending (it just finished FAILED) — fast path (item
                    # 5): there is no one left who could still resolve the
                    # disagreement, so proceed immediately instead of
                    # waiting out the rest of any bounded window.
                    if disagreement_deadline is not None:
                        disagreement_wait_actual_ms = int(
                            (time.perf_counter() - disagreement_wait_started_at) * 1000
                        )
                        log.info(
                            "early_synthesis_disagreement_wait_completed query_id=%s "
                            "reason=pending_provider_failed wait_actual_ms=%d",
                            cid, disagreement_wait_actual_ms,
                        )
                        disagreement_deadline = None
                    _log_disagreement_forced_proceed(
                        cid, finalized, provider_policy_lookup, quorum_policy,
                        last_gate_score, last_gate_live_ids,
                    )
                    break

        if quorum_deadline is not None and time.perf_counter() >= quorum_deadline:
            break

        if disagreement_deadline is not None and time.perf_counter() >= disagreement_deadline:
            disagreement_wait_actual_ms = int(
                (time.perf_counter() - disagreement_wait_started_at) * 1000
            )
            log.info(
                "early_synthesis_disagreement_wait_completed query_id=%s "
                "reason=deadline_expired wait_actual_ms=%d",
                cid, disagreement_wait_actual_ms,
            )
            disagreement_deadline = None
            _log_disagreement_forced_proceed(
                cid, finalized, provider_policy_lookup, quorum_policy,
                last_gate_score, last_gate_live_ids,
            )
            break

    early_synthesis = bool(pending)
    if quorum_reached_at_ms is not None:
        grace_window_actual_ms = (
            int((time.perf_counter() - grace_window_started_at) * 1000)
            if grace_window_started_at is not None
            else 0
        )
        log.info(
            "early_synthesis_grace_window_ended query_id=%s pending_providers=%s "
            "early_synthesis=%s grace_window_actual_ms=%d",
            cid, sorted(tasks[t] for t in pending), early_synthesis, grace_window_actual_ms,
        )

    late_tasks: dict[str, asyncio.Task] = {}
    for task in pending:
        provider_id = tasks[task]
        late_tasks[provider_id] = task
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(
            lambda t, pid=provider_id: _handle_late_completion(pid, t, on_late_complete, cid)
        )

    return QuorumRunResult(
        finalized=finalized,
        late_tasks=late_tasks,
        early_synthesis=early_synthesis,
        quorum_reached_at_ms=quorum_reached_at_ms,
        grace_window_seconds=quorum_policy.grace_window_seconds,
        disagreement_wait_actual_ms=disagreement_wait_actual_ms,
    )


def _live_quorum_eligible_ids(
    finalized: dict[str, ProviderResult],
    provider_policy_lookup: Callable[[str], ProviderPolicy],
) -> list[str]:
    return [
        provider_id
        for provider_id, result in finalized.items()
        if result.provider_status == PROVIDER_STATUS_LIVE
        and provider_policy_lookup(provider_id).eligible_for_quorum
    ]


def _raw_quorum_satisfied(
    finalized: dict[str, ProviderResult],
    provider_policy_lookup: Callable[[str], ProviderPolicy],
    quorum_policy: QuorumPolicy,
) -> bool:
    """RAW quorum: minimum_live_responses (+ core provider, if required).

    Deliberately excludes the disagreement gate — see
    _disagreement_gate_result. SEMANTIC quorum (the concept the rest of
    this module cared about before this patch) = raw quorum AND the gate
    passing.
    """
    live_ids = _live_quorum_eligible_ids(finalized, provider_policy_lookup)
    if len(live_ids) < quorum_policy.minimum_live_responses:
        return False
    if quorum_policy.require_core_provider and not any(
        provider_policy_lookup(provider_id).core_provider for provider_id in live_ids
    ):
        return False
    return True


def _disagreement_gate_result(
    finalized: dict[str, ProviderResult],
    provider_policy_lookup: Callable[[str], ProviderPolicy],
    quorum_policy: QuorumPolicy,
    similarity_fn: Optional[Callable[[str, str], float]],
    correlation_id: str,
) -> tuple[bool, Optional[float], Optional[tuple[str, str]]]:
    """Evaluate the conservative disagreement gate. Returns (passed, score,
    live_id_pair); score/live_id_pair are None whenever the gate was not
    actually evaluated (treated as passed in that case).

    Conservative disagreement gate (Patch 2 scope, unchanged by this
    patch): only evaluated when exactly two LIVE responses are the basis
    for the decision — matching "i due primi LIVE" from the original
    design brief. A general N-way disagreement gate is deferred (see
    module docstring). In particular: once a third provider is LIVE,
    len(live_ids) != 2 and the gate is skipped entirely (treated as
    passed) — this is what lets all three be used once the third arrives,
    without re-applying or extending any wait (item 6).
    """
    live_ids = _live_quorum_eligible_ids(finalized, provider_policy_lookup)
    if (
        similarity_fn is None
        or len(live_ids) != 2
        or quorum_policy.disagreement_threshold <= 0.0
    ):
        return True, None, None
    text_a = finalized[live_ids[0]].text
    text_b = finalized[live_ids[1]].text
    score = similarity_fn(text_a, text_b)
    gate_passed = score >= quorum_policy.disagreement_threshold
    pair = tuple(sorted([live_ids[0], live_ids[1]]))
    # Numeric score/threshold/ids only — never the response text itself.
    log.info(
        "early_synthesis_disagreement_gate_result query_id=%s "
        "provider_ids=%s similarity_score=%.4f threshold=%.4f gate_passed=%s",
        correlation_id, list(pair), score,
        quorum_policy.disagreement_threshold, gate_passed,
    )
    return gate_passed, score, pair


def _log_disagreement_forced_proceed(
    correlation_id: str,
    finalized: dict[str, ProviderResult],
    provider_policy_lookup: Callable[[str], ProviderPolicy],
    quorum_policy: QuorumPolicy,
    score: Optional[float],
    live_ids: Optional[tuple[str, str]],
) -> None:
    """Log that early synthesis is proceeding on raw quorum alone, with the
    disagreement gate still failed — never invalidates or relabels the
    LIVE responses involved; the Synthesizer receives both and may
    represent their disagreement explicitly (item 3). Numeric score/
    threshold/ids only, same safety contract as the gate-result log line.
    """
    live_provider_ids = sorted(_live_quorum_eligible_ids(finalized, provider_policy_lookup))
    log.info(
        "early_synthesis_disagreement_forced_proceed query_id=%s "
        "live_provider_ids=%s similarity_score=%s threshold=%.4f",
        correlation_id, live_provider_ids,
        f"{score:.4f}" if score is not None else "unavailable",
        quorum_policy.disagreement_threshold,
    )


def _handle_late_completion(
    provider_id: str,
    task: asyncio.Task,
    on_late_complete: Optional[Callable[[str, ProviderResult], Awaitable[None]]],
    correlation_id: str,
) -> None:
    """Done-callback for a late provider task — always sync (asyncio contract).

    Unconditionally consumes the task's result/exception and drops the
    anti-GC reference, regardless of whether `on_late_complete` is set or
    what it does — this module's own housekeeping never depends on the
    caller's callback succeeding.
    """
    _BACKGROUND_TASKS.discard(task)
    try:
        result = task.result()
    except Exception:  # noqa: BLE001 — defence in depth; timed_generate never raises today.
        log.exception(
            "early_synthesis_late_provider_unexpected_exception "
            "query_id=%s provider_id=%s",
            correlation_id, provider_id,
        )
        return

    log.info(
        "early_synthesis_late_provider_completed query_id=%s provider_id=%s "
        "status=%s total_duration_ms=%d",
        correlation_id, provider_id, result.provider_status, result.latency_ms,
    )

    if on_late_complete is None:
        return

    follow_up = asyncio.create_task(_run_late_complete_callback(provider_id, result, on_late_complete, correlation_id))
    _BACKGROUND_TASKS.add(follow_up)
    follow_up.add_done_callback(_BACKGROUND_TASKS.discard)


async def _run_late_complete_callback(
    provider_id: str,
    result: ProviderResult,
    on_late_complete: Callable[[str, ProviderResult], Awaitable[None]],
    correlation_id: str,
) -> None:
    try:
        await on_late_complete(provider_id, result)
    except Exception:  # noqa: BLE001
        log.exception(
            "early_synthesis_late_complete_callback_failed query_id=%s provider_id=%s",
            correlation_id, provider_id,
        )
