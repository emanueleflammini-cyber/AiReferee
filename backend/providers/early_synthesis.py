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

    while pending:
        wait_timeout: Optional[float] = None
        if quorum_deadline is not None:
            wait_timeout = max(0.0, quorum_deadline - time.perf_counter())

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

        if quorum_deadline is None and _quorum_satisfied(
            finalized, provider_policy_lookup, quorum_policy, similarity_fn, cid,
        ):
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

        if quorum_deadline is not None and time.perf_counter() >= quorum_deadline:
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
    )


def _quorum_satisfied(
    finalized: dict[str, ProviderResult],
    provider_policy_lookup: Callable[[str], ProviderPolicy],
    quorum_policy: QuorumPolicy,
    similarity_fn: Optional[Callable[[str, str], float]],
    correlation_id: str,
) -> bool:
    live_ids = [
        provider_id
        for provider_id, result in finalized.items()
        if result.provider_status == PROVIDER_STATUS_LIVE
        and provider_policy_lookup(provider_id).eligible_for_quorum
    ]
    if len(live_ids) < quorum_policy.minimum_live_responses:
        return False
    if quorum_policy.require_core_provider and not any(
        provider_policy_lookup(provider_id).core_provider for provider_id in live_ids
    ):
        return False
    # Conservative disagreement gate (Patch 2 scope): only evaluated when
    # exactly two LIVE responses are the basis for the decision — matching
    # "i due primi LIVE" from the design brief. A general N-way disagreement
    # gate is deferred to Patch 3 (see module docstring / patch report).
    # Unchanged by this observability patch: same threshold comparison,
    # same similarity_fn contract — only a log line was added below.
    if (
        similarity_fn is not None
        and len(live_ids) == 2
        and quorum_policy.disagreement_threshold > 0.0
    ):
        text_a = finalized[live_ids[0]].text
        text_b = finalized[live_ids[1]].text
        score = similarity_fn(text_a, text_b)
        gate_passed = score >= quorum_policy.disagreement_threshold
        # Numeric score/threshold/ids only — never the response text itself.
        log.info(
            "early_synthesis_disagreement_gate_result query_id=%s "
            "provider_ids=%s similarity_score=%.4f threshold=%.4f gate_passed=%s",
            correlation_id, sorted([live_ids[0], live_ids[1]]), score,
            quorum_policy.disagreement_threshold, gate_passed,
        )
        if not gate_passed:
            return False
    return True


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
