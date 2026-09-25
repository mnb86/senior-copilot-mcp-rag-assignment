"""Copilot orchestration: NL request -> intent -> plan -> MCP + RAG execution -> grounded answer."""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from rag.ingestion.security import UNSAFE_ADVICE

from .composer import compose
from .config import Settings
from .domain import Answer, ChatRequest, InvestigationResponse, RetrievalInfo, TimeWindow, ToolCallRecord
from .executor import PlanExecutor, Retrieval
from .intent import classify, extract_entities
from .llm import LLMError, LLMProvider, guard_answer, refine_intent, validate_citations, write_answer
from .mcp_client import McpClientError, ToolSession, ToolSpec
from .planner import ConversationContext, Planner
from .reasoning import assess_recommendations, build_causes, build_citations, build_summary

UNSAFE_REQUEST_NOTICE = (
    "**Not supported: bypassing or disabling a trip, interlock, alarm or safety system.** Protections may only be "
    "overridden under your site's management-of-change and permit process with the responsible engineer. "
    "The investigation below is read-only evidence to help find and fix the underlying cause."
)

log = logging.getLogger("copilot.orchestrator")


class Gateway(Protocol):
    server_name: str

    def session(self) -> contextlib.AbstractAsyncContextManager[ToolSession]: ...


class ConversationStore:
    """In-memory, bounded conversation context store (swap for Redis in production)."""

    def __init__(self, max_conversations: int = 500) -> None:
        self._data: OrderedDict[str, tuple[ConversationContext, list[dict[str, Any]]]] = OrderedDict()
        self._max = max_conversations

    def get(self, cid: str) -> ConversationContext:
        if cid not in self._data:
            self._data[cid] = (ConversationContext(), [])
            while len(self._data) > self._max:
                self._data.popitem(last=False)
        self._data.move_to_end(cid)
        return self._data[cid][0]

    def history(self, cid: str) -> list[dict[str, Any]]:
        return self._data[cid][1] if cid in self._data else []

    def append(self, cid: str, turn: dict[str, Any]) -> None:
        self.get(cid)
        self._data[cid][1].append(turn)
        del self._data[cid][1][:-20]


class Copilot:
    def __init__(
        self,
        settings: Settings,
        gateway: Gateway | None,
        retrieval: Retrieval | None,
        llm: LLMProvider | None = None,
        store: ConversationStore | None = None,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.retrieval = retrieval
        self.llm = llm
        self.store = store or ConversationStore()
        self.planner = Planner(settings.default_lookback_days)

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        if self.settings.reference_time:
            v = self.settings.reference_time.replace("Z", "+00:00")
            return datetime.fromisoformat(v).astimezone(UTC)
        return datetime.now(UTC).replace(second=0, microsecond=0)

    def window(self, days: int | None) -> TimeWindow:
        d = days or self.settings.default_lookback_days
        end = self._now()
        start = end - timedelta(days=d)
        f = "%Y-%m-%dT%H:%M:%SZ"
        return TimeWindow(days=d, start_time=start.strftime(f), end_time=end.strftime(f), label=f"in the last {d} days")

    @contextlib.asynccontextmanager
    async def _session(
        self, needed: bool
    ) -> AsyncIterator[tuple[ToolSession | None, list[ToolSpec], dict[str, Any] | None, float]]:
        if not needed or self.gateway is None:
            reason = None if not needed else {"code": "MCP_NOT_CONFIGURED", "message": "No MCP server configured"}
            yield None, [], reason, 0.0
            return
        started = time.perf_counter()
        entered = False
        failure: dict[str, Any] | None = None
        try:
            async with self.gateway.session() as s:
                tools = await s.list_tools()
                entered = True
                yield s, tools, None, round((time.perf_counter() - started) * 1000, 1)
        except McpClientError as exc:
            if entered:  # errors raised by the caller's block propagate unchanged
                raise
            failure = exc.to_dict()
        if failure is not None:
            yield None, [], failure, round((time.perf_counter() - started) * 1000, 1)

    # ------------------------------------------------------------------ main entry
    async def handle(self, req: ChatRequest) -> InvestigationResponse:
        t0 = time.perf_counter()
        cid = req.conversation_id or uuid.uuid4().hex[:12]
        request_id, trace_id = uuid.uuid4().hex[:16], f"trace-{uuid.uuid4().hex[:16]}"
        ctx = self.store.get(cid)
        warnings: list[str] = []
        errors: list[str] = []
        timings: dict[str, float] = {}

        entities = extract_entities(req.message)
        intent = classify(req.message, entities, has_context=bool(ctx.asset or ctx.alarm))
        if self.llm is not None:
            t = time.perf_counter()
            intent = await refine_intent(
                self.llm, req.message, intent, json.dumps({"asset": ctx.asset, "alarm": ctx.alarm}, default=str)
            )
            timings["llm_intent_ms"] = round((time.perf_counter() - t) * 1000, 1)
        window = self.window(intent.entities.lookback_days)
        plan = self.planner.build(intent, req.message, ctx, window)
        warnings.extend(plan.notes)
        needs_mcp = any(s.kind == "mcp" for s in plan.steps)

        meta = {
            "trace_id": trace_id,
            "conversation_id": cid,
            "client_id": self.settings.mcp_client_id,
            "request_id": request_id,
        }
        records: list[ToolCallRecord] = []
        discovered: list[str] = []
        async with self._session(needs_mcp) as (session, tools, unavailable, discovery_ms):
            if needs_mcp:
                discovered = sorted(t.name for t in tools)
                records.append(
                    ToolCallRecord(
                        step_id="discover_tools",
                        kind="mcp",
                        server=getattr(self.gateway, "server_name", None),
                        tool="tools/list",
                        purpose="MCP tool discovery (names, descriptions, input/output schemas)",
                        status="ok" if session else "error",
                        wave=0,
                        duration_ms=discovery_ms,
                        trace_id=trace_id,
                        request={"jsonrpc": "2.0", "method": "tools/list"},
                        response={
                            "tools": [
                                {
                                    "name": t.name,
                                    "read_only": t.read_only,
                                    "required": t.input_schema.get("required", []),
                                }
                                for t in tools
                            ]
                        }
                        if session
                        else None,
                        error=unavailable,
                    )
                )
                if unavailable:
                    errors.append(
                        f"MCP server unavailable ({unavailable.get('code')}): {unavailable.get('message')}."
                        " Alarm data could not be retrieved; the answer is based on documents only."
                    )
            executor = PlanExecutor(session, self.retrieval, meta, set(discovered), unavailable)
            t = time.perf_counter()
            result = await executor.run(plan)
            timings["execution_ms"] = round((time.perf_counter() - t) * 1000, 1)
        records.extend(result.records)

        for rec in result.records:
            if rec.status == "error" and rec.kind == "mcp" and not unavailable:
                err = rec.error or {}
                extra = f" after {err.get('attempts')} attempt(s)" if err.get("attempts") else ""
                warnings.append(f"`{rec.tool}` ({rec.step_id}) failed{extra}: {err.get('code')} - {err.get('message')}")
            elif rec.status == "skipped" and not unavailable:
                err = rec.error or {}
                warnings.append(f"`{rec.tool}` ({rec.step_id}) skipped: {err.get('message')}")
            elif rec.status == "error" and rec.kind == "rag":
                warnings.append(f"Document retrieval failed: {(rec.error or {}).get('message')}")
            elif rec.retries and rec.status == "ok":
                warnings.append(f"`{rec.tool}` recovered after {rec.retries} retry(ies) (transient upstream error)")
        clarification = plan.needs_clarification
        if not clarification and "asset_id" in result.binding_errors and intent.name != "site_priority":
            clarification = (
                f"I could not resolve the asset: {result.binding_errors['asset_id']}. Please check the "
                "asset name or tag (e.g. 'Boiler Feed Pump 101', 'K-301')."
            )
        if clarification:
            skipped = [w for w in warnings if " skipped: " in w]
            warnings = [w for w in warnings if " skipped: " not in w]
            if skipped:
                warnings.append(
                    f"{len(skipped)} dependent tool call(s) skipped because the scope could not be resolved"
                )

        out = result.outputs
        retrieval = result.retrieval
        citations = build_citations(retrieval)
        panel = build_summary(intent, out, window, result.bindings)
        causes = build_causes(out, retrieval, result.bindings)
        recs = assess_recommendations(out, citations, retrieval)
        low_conf = bool(retrieval.low_confidence) if retrieval else True
        if retrieval and retrieval.quarantined:
            warnings.append(
                f"{len(retrieval.quarantined)} retrieved passage(s) were quarantined because they contain "
                f"embedded instructions (possible prompt injection): "
                + ", ".join(r.chunk.chunk_id for r in retrieval.quarantined)
            )

        markdown = compose(intent, panel, causes, recs, citations, low_conf, warnings, out, clarification)
        generator = "template"
        safety_flags: list[str] = []
        if self.llm is not None and not clarification:
            evidence = {
                "intent": intent.model_dump(),
                "window": window.model_dump(),
                "alarm_summary": panel.model_dump() if panel else None,
                "likely_causes": [c.model_dump() for c in causes],
                "recommendations": [r.model_dump() for r in recs],
                "warnings": warnings,
                "retrieval_low_confidence": low_conf,
            }
            try:
                text, llm_ms = await write_answer(self.llm, evidence, citations)
                timings["llm_answer_ms"] = llm_ms
                text, bad = validate_citations(text, citations)
                if bad:
                    warnings.append(f"Removed invalid citation markers from LLM output: {', '.join(bad)}")
                flags = guard_answer(text)
                if flags:
                    safety_flags.extend(flags)
                    warnings.append("LLM answer was replaced by the template answer: unsafe advice detected")
                elif text:
                    markdown, generator = text, f"llm:{self.llm.name}"
            except (LLMError, Exception) as exc:  # noqa: BLE001 - any provider failure degrades gracefully
                warnings.append(f"LLM unavailable ({type(exc).__name__}); used deterministic template answer")
        safety_flags.extend(guard_answer(markdown) if generator == "template" else [])
        if UNSAFE_ADVICE.search(req.message):
            # The request itself asks to defeat a protection: answer with the read-only evidence, but refuse that part.
            safety_flags.append("unsafe_request: bypass/disable of a protection was requested")
            markdown = UNSAFE_REQUEST_NOTICE + "\n\n" + markdown

        core_ok = sum(1 for r in result.records if r.kind == "mcp" and r.status == "ok")
        core_fail = sum(1 for r in result.records if r.kind == "mcp" and r.status != "ok")
        if clarification or (not core_ok and low_conf):
            confidence = "low"
        elif core_fail or low_conf or unavailable:
            confidence = "medium"
        else:
            confidence = "high"

        # ------------------------------------------------------------ context retention
        meta_asset = (out.get("asset_metadata") or {}).get("asset")
        if meta_asset:
            ctx.asset = {k: meta_asset.get(k) for k in ("asset_id", "asset_name", "asset_type", "site", "unit")}
            ctx.site = meta_asset.get("site")
        if panel and panel.primary_alarm:
            ctx.alarm = panel.primary_alarm.model_dump()
        elif out.get("alarm_detail"):
            ctx.alarm = out["alarm_detail"]["alarm"]
        if out.get("recommendations"):
            ctx.recommendations = out["recommendations"].get("recommendations", [])
        if intent.entities.site:
            ctx.site = intent.entities.site
        ctx.turns += 1

        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        response = InvestigationResponse(
            conversation_id=cid,
            request_id=request_id,
            trace_id=trace_id,
            intent=intent,
            plan=plan.steps,
            answer=Answer(
                markdown=markdown,
                confidence=confidence,
                grounded=bool(citations) or core_ok > 0,
                generator=generator,
                safety_flags=safety_flags,
            ),
            alarm_summary=panel,
            likely_causes=causes,
            recommendations=recs,
            citations=citations,
            retrieval=RetrievalInfo(
                query=retrieval.query,
                filters=retrieval.filters.model_dump(exclude_none=True),
                low_confidence=retrieval.low_confidence,
                top_confidence=retrieval.top_confidence,
                fallback_used=retrieval.fallback_used,
                results=[
                    {
                        "id": f"S{i}",
                        "chunk_id": r.chunk.chunk_id,
                        "score": r.score,
                        "confidence": r.confidence,
                        "bm25": r.bm25,
                        "dense": r.dense,
                        "boost": r.boost,
                    }
                    for i, r in enumerate(retrieval.results, start=1)
                ],
                quarantined=[
                    {"chunk_id": r.chunk.chunk_id, "patterns": r.chunk.injection_patterns, "doc_id": r.chunk.doc_id}
                    for r in retrieval.quarantined
                ],
            )
            if retrieval
            else None,
            tool_trace=records,
            discovered_tools=discovered,
            warnings=list(dict.fromkeys(warnings)),
            errors=errors,
            timings=timings,
        )
        self.store.append(
            cid,
            {
                "request_id": request_id,
                "message": req.message,
                "intent": intent.name,
                "answer": markdown,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        log.info(
            json.dumps(
                {
                    "event": "copilot_request",
                    "request_id": request_id,
                    "conversation_id": cid,
                    "trace_id": trace_id,
                    "intent": intent.name,
                    "confidence": confidence,
                    "generator": generator,
                    "tools": [
                        {
                            "mcp_server": r.server,
                            "tool": r.tool,
                            "status": r.status,
                            "duration_ms": r.duration_ms,
                            "retries": r.retries,
                            "api_status": (r.api_calls[-1].get("status") if r.api_calls else None),
                        }
                        for r in records
                        if r.kind == "mcp"
                    ],
                    "retrieval": {
                        "query": retrieval.query[:200] if retrieval else None,
                        "doc_ids": [c.chunk_id for c in citations],
                        "scores": [c.score for c in citations],
                    },
                    # null when no LLM is configured (deterministic template answer)
                    "llm_latency_ms": (
                        round(timings.get("llm_intent_ms", 0) + timings.get("llm_answer_ms", 0), 1)
                        if self.llm is not None
                        else None
                    ),
                    "timings": timings,
                }
            )
        )
        return response
