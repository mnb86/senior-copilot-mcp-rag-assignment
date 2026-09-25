"""Plan executor: runs MCP tool calls and the RAG step in dependency waves, passing outputs forward.

* Independent steps in the same wave run concurrently.
* ``$var`` arguments are resolved through bindings/selectors once their source steps finished.
* Failures are isolated: a failed optional step never aborts the plan; steps whose inputs cannot be
  resolved are marked ``skipped`` with the reason (partial-failure handling).
"""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from rag.retrieval.models import RetrievalFilters, RetrievalResult

from .domain import PlanStep, ToolCallRecord
from .mcp_client import McpClientError, ToolSession
from .planner import SELECTORS, Binding, Plan, SelectorError, build_rag_request, vars_in

MAX_LIST_IN_TRACE = 25
FOREACH_CONCURRENCY = 4


class Retrieval(Protocol):
    def search_many(self, queries: list[str], filters: RetrievalFilters) -> RetrievalResult: ...


class BindingUnavailable(Exception):
    pass


@dataclass
class ExecutionResult:
    outputs: dict[str, Any] = field(default_factory=dict)
    records: list[ToolCallRecord] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)
    binding_errors: dict[str, str] = field(default_factory=dict)
    retrieval: RetrievalResult | None = None
    status: dict[str, str] = field(default_factory=dict)


def _trim(value: Any, depth: int = 0) -> Any:
    """Keep trace payloads readable in the GUI (full data stays in outputs)."""
    if isinstance(value, list):
        items = [_trim(v, depth + 1) for v in value[:MAX_LIST_IN_TRACE]]
        if len(value) > MAX_LIST_IN_TRACE:
            items.append(f"... {len(value) - MAX_LIST_IN_TRACE} more item(s) truncated in trace view")
        return items
    if isinstance(value, dict):
        return {k: _trim(v, depth + 1) for k, v in value.items() if not (depth == 0 and k == "trace")}
    return value


class PlanExecutor:
    def __init__(
        self,
        session: ToolSession | None,
        retrieval: Retrieval | None,
        trace_meta: dict[str, Any],
        available_tools: set[str] | None,
        unavailable_reason: dict[str, Any] | None = None,
    ) -> None:
        self.session = session
        self.retrieval = retrieval
        self.meta = trace_meta
        self.available = available_tools or set()
        self.unavailable_reason = unavailable_reason

    # ------------------------------------------------------------------ dependencies
    def _binding_steps(self, plan: Plan, name: str, seen: set[str] | None = None) -> set[str]:
        seen = seen or set()
        if name in seen or name not in plan.bindings:
            return set()
        seen.add(name)
        bnd = plan.bindings[name]
        deps = set(bnd.depends_on) | ({bnd.step} if bnd.step else set())
        for v in vars_in(bnd.params):
            deps |= self._binding_steps(plan, v, seen)
        return deps

    def _deps(self, plan: Plan, step: PlanStep) -> set[str]:
        deps = set(step.depends_on)
        for v in vars_in(step.args) | vars_in(step.foreach or {}):
            deps |= self._binding_steps(plan, v)
        return deps - {step.id}

    # ------------------------------------------------------------------ bindings
    def _resolve_binding(self, plan: Plan, res: ExecutionResult, name: str) -> Any:
        if name in res.bindings:
            return res.bindings[name]
        if name in res.binding_errors:
            raise BindingUnavailable(res.binding_errors[name])
        bnd: Binding | None = plan.bindings.get(name)
        if bnd is None:
            raise BindingUnavailable(f"unknown binding '{name}'")
        try:
            if bnd.step and res.status.get(bnd.step) != "ok" and not bnd.tolerant:
                raise BindingUnavailable(f"'{name}' needs step '{bnd.step}', which {res.status.get(bnd.step)}")
            params = self._substitute(plan, res, bnd.params)
            if bnd.selector == "literal":
                value = params["value"]
            elif bnd.selector == "rag_request":
                value = build_rag_request(res.outputs, params)
            else:
                value = SELECTORS[bnd.selector](res.outputs, bnd.step or "", params)
        except SelectorError as exc:
            res.binding_errors[name] = str(exc)
            raise BindingUnavailable(str(exc)) from exc
        except BindingUnavailable as exc:
            res.binding_errors[name] = str(exc)
            raise
        res.bindings[name] = value
        return value

    def _substitute(self, plan: Plan, res: ExecutionResult, value: Any, item: Any = None) -> Any:
        if isinstance(value, dict):
            if "$var" in value:
                return self._resolve_binding(plan, res, value["$var"])
            if value.get("$item"):
                return item
            return {k: self._substitute(plan, res, v, item) for k, v in value.items()}
        if isinstance(value, list):
            return [self._substitute(plan, res, v, item) for v in value]
        return value

    # ------------------------------------------------------------------ execution
    async def run(self, plan: Plan) -> ExecutionResult:
        res = ExecutionResult()
        pending = {s.id: s for s in plan.steps}
        deps = {s.id: self._deps(plan, s) for s in plan.steps}
        wave = 0
        while pending:
            ready = [s for sid, s in pending.items() if deps[sid] <= set(res.status)]
            if not ready:  # dependency cycle / unknown dependency
                for s in pending.values():
                    self._skip(res, s, wave, "UNRESOLVED_DEPENDENCY", "step dependencies could not be satisfied")
                break
            wave += 1
            await asyncio.gather(*(self._run_step(plan, res, s, wave) for s in ready))
            for s in ready:
                pending.pop(s.id, None)
        order = {s.id: i for i, s in enumerate(plan.steps)}
        res.records.sort(key=lambda r: (r.wave, order.get(r.step_id, 0), r.iteration or 0))
        return res

    def _skip(self, res: ExecutionResult, step: PlanStep, wave: int, code: str, message: str) -> None:
        res.status[step.id] = "skipped"
        res.records.append(
            ToolCallRecord(
                step_id=step.id,
                kind=step.kind,
                tool=step.tool,
                purpose=step.purpose,
                status="skipped",
                wave=wave,
                arguments={},
                error={"code": code, "message": message},
                server="alarm-management" if step.kind == "mcp" else "rag",
            )
        )

    async def _run_step(self, plan: Plan, res: ExecutionResult, step: PlanStep, wave: int) -> None:
        try:
            args = self._substitute(plan, res, step.args)
            items = self._substitute(plan, res, step.foreach) if step.foreach else None
        except BindingUnavailable as exc:
            self._skip(res, step, wave, "DEPENDENCY_UNAVAILABLE", str(exc))
            return
        if step.kind == "rag":
            await self._run_rag(res, step, wave, args)
            return
        if self.session is None:
            reason = self.unavailable_reason or {"code": "MCP_UNAVAILABLE", "message": "MCP server not connected"}
            self._skip(res, step, wave, reason.get("code", "MCP_UNAVAILABLE"), reason.get("message", ""))
            return
        if step.tool not in self.available:
            self._skip(res, step, wave, "TOOL_NOT_FOUND", f"Tool '{step.tool}' was not found during MCP tool discovery")
            return
        if items is not None:
            sem = asyncio.Semaphore(FOREACH_CONCURRENCY)

            async def one(i: int, it: Any) -> Any:
                async with sem:
                    a = self._substitute(plan, res, step.args, item=it)
                    return await self._call(res, step, wave, a, iteration=i)

            outs = await asyncio.gather(*(one(i, it) for i, it in enumerate(items)))
            ok = [o for o in outs if o is not None]
            res.outputs[step.id] = ok
            res.status[step.id] = "ok" if ok else "error"
            return
        out = await self._call(res, step, wave, args)
        if out is not None:
            res.outputs[step.id] = out
            res.status[step.id] = "ok"
        else:
            res.status[step.id] = "error"

    async def _call(
        self, res: ExecutionResult, step: PlanStep, wave: int, args: dict[str, Any], iteration: int | None = None
    ) -> Any:
        assert self.session is not None
        meta = {**self.meta, "step_id": step.id}
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": step.tool, "arguments": args, "_meta": meta},
        }
        rec = ToolCallRecord(
            step_id=step.id,
            kind="mcp",
            server=self.session.server_name,
            tool=step.tool,
            purpose=step.purpose,
            status="ok",
            wave=wave,
            arguments=args,
            request=request,
            trace_id=meta.get("trace_id"),
            iteration=iteration,
        )
        started = time.perf_counter()
        try:
            outcome = await self.session.call_tool(step.tool, args, meta)
        except McpClientError as exc:
            rec.status, rec.error = "error", exc.to_dict()
            rec.duration_ms = round((time.perf_counter() - started) * 1000, 1)
            res.records.append(rec)
            return None
        rec.duration_ms = outcome.duration_ms
        if not outcome.ok:
            rec.status, rec.error = "error", outcome.error
            details = (outcome.error or {}).get("details") or {}
            attempts = details.get("http_attempts") if isinstance(details, dict) else None
            if attempts:
                rec.api_calls = attempts
                rec.retries = max(0, len(attempts) - 1)
            rec.response = {"isError": True, "error": outcome.error}
            res.records.append(rec)
            return None
        data = outcome.data or {}
        trace = data.get("trace") or {}
        rec.api_calls = trace.get("api_calls", [])
        rec.retries = int(trace.get("retries", 0))
        rec.response = {"structuredContent": _trim(data), "output_schema_valid": outcome.output_schema_valid}
        res.records.append(rec)
        return data

    async def _run_rag(self, res: ExecutionResult, step: PlanStep, wave: int, args: dict[str, Any]) -> None:
        request = copy.deepcopy(args.get("request") or {})
        rec = ToolCallRecord(
            step_id=step.id,
            kind="rag",
            server="rag",
            tool=step.tool,
            purpose=step.purpose,
            status="ok",
            wave=wave,
            arguments=request,
            request=request,
        )
        if self.retrieval is None:
            rec.status, rec.error = "error", {"code": "RETRIEVAL_UNAVAILABLE", "message": "Index not loaded"}
            res.records.append(rec)
            res.status[step.id] = "error"
            return
        started = time.perf_counter()
        try:
            filters = RetrievalFilters(**(request.get("filters") or {}))
            result = await asyncio.to_thread(self.retrieval.search_many, request.get("queries") or [], filters)
        except Exception as exc:  # noqa: BLE001 - retrieval must never break the investigation
            rec.status, rec.error = "error", {"code": "RETRIEVAL_FAILED", "message": str(exc)[:300]}
            res.records.append(rec)
            res.status[step.id] = "error"
            return
        rec.duration_ms = round((time.perf_counter() - started) * 1000, 1)
        rec.response = {
            "low_confidence": result.low_confidence,
            "top_confidence": result.top_confidence,
            "fallback_used": result.fallback_used,
            "results": [
                {"chunk_id": r.chunk.chunk_id, "score": r.score, "confidence": r.confidence} for r in result.results
            ],
            "quarantined": [r.chunk.chunk_id for r in result.quarantined],
        }
        res.records.append(rec)
        res.retrieval = result
        res.outputs[step.id] = result
        res.status[step.id] = "ok"
