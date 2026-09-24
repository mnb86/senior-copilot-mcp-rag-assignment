"""Dependency-free line-coverage report (fallback when `coverage`/`pytest-cov` are unavailable).

Usage: python scripts/coverage_lite.py [pytest args...]
Writes docs/coverage-summary.md. CI uses pytest-cov (see .github/workflows/ci.yml) for the canonical report.
"""

from __future__ import annotations

import sys
import threading
from collections import defaultdict
from pathlib import Path
from types import CodeType

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = [
    "apps/backend/copilot",
    "apps/alarm-api-simulator/alarm_simulator",
    "mcp-servers/alarm-management/alarm_mcp",
    "connectors",
    "rag/ingestion",
    "rag/retrieval",
    "rag/models.py",
    "rag/security.py",
]
SOURCES = sorted(
    {
        p.resolve()
        for pkg in PACKAGES
        for p in ([ROOT / pkg] if pkg.endswith(".py") else (ROOT / pkg).rglob("*.py"))
        if p.name != "__main__.py"
    }
)
TRACKED = {str(p) for p in SOURCES}
hits: dict[str, set[int]] = defaultdict(set)


def _tracer(frame, event, arg):  # type: ignore[no-untyped-def]
    fn = frame.f_code.co_filename
    if fn not in TRACKED:
        return None
    if event in ("call", "line"):
        hits[fn].add(frame.f_lineno)
    return _tracer


def executable_lines(path: Path) -> set[int]:
    code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
    lines: set[int] = set()
    stack: list[CodeType] = [code]
    while stack:
        c = stack.pop()
        lines.update(ln for _, _, ln in c.co_lines() if ln is not None)
        stack.extend(k for k in c.co_consts if isinstance(k, CodeType))
    return {ln for ln in lines if ln > 0}


def main() -> int:
    import pytest

    sys.settrace(_tracer)
    threading.settrace(_tracer)
    rc = pytest.main(["-q", "-p", "no:cacheprovider", *sys.argv[1:]])
    sys.settrace(None)
    threading.settrace(None)  # type: ignore[arg-type]
    rows, tot_exec, tot_hit = [], 0, 0
    for p in SOURCES:
        ex = executable_lines(p)
        hit = hits.get(str(p), set()) & ex
        tot_exec += len(ex)
        tot_hit += len(hit)
        rows.append((str(p.relative_to(ROOT)), len(ex), len(hit)))
    out = [
        "# Coverage summary",
        "",
        "Line coverage measured with `scripts/coverage_lite.py` (sys.settrace over the full pytest suite). "
        "CI additionally publishes the canonical `pytest-cov` report as a build artifact.",
        "",
        f"**Total: {100 * tot_hit / max(1, tot_exec):.1f}%** ({tot_hit}/{tot_exec} executable lines)",
        "",
        "| File | Lines | Covered | % |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, ex, hit in rows:
        out.append(f"| `{name}` | {ex} | {hit} | {100 * hit / max(1, ex):.0f}% |")
    (ROOT / "docs" / "coverage-summary.md").write_text("\n".join(out) + "\n")
    print("\n".join(out[4:5]))
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
