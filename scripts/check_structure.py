"""Check the repository against the folder structure required by the assignment guidelines (section 3).

    python scripts/check_structure.py

Reports missing required entries and any extra entries at the levels the guideline tree specifies. Extras that
are required by tooling (and documented in the README) are listed separately. Exits 1 if anything is missing or
if an unexpected extra appears.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

REQUIRED: dict[str, set[str]] = {
    ".": {
        "README.md",
        "docs",
        "apps",
        "mcp-servers",
        "rag",
        "connectors",
        "tests",
        "test-data",
        "scripts",
        ".github",
        ".env.example",
        ".gitignore",
        "Dockerfile",
        "docker-compose.yml",
        "Makefile",
        "LICENSE",
    },
    "docs": {
        "architecture.md",
        "architecture-diagram.png",
        "mcp-tool-catalog.md",
        "rag-design.md",
        "api-integration.md",
        "design-decisions.md",
        "known-limitations.md",
    },
    "apps": {"backend", "frontend"},
    "mcp-servers": {"alarm-management", "optional-secondary-server"},
    "rag": {"ingestion", "retrieval", "documents", "tests"},
    "tests": {"unit", "integration", "e2e"},
    ".github": {"workflows"},
    ".github/workflows": {"ci.yml"},
}

# Extras kept on purpose (documented in the README's repository-layout section).
ALLOWED_EXTRAS: dict[str, dict[str, str]] = {
    ".": {
        "pyproject.toml": "pytest/ruff/mypy only read it from the root",
        ".dockerignore": "Docker only reads it from the build-context root",
    },
    "tests": {"conftest.py": "pytest's shared-fixture file"},
    "docs": {
        name: "supporting deliverable"
        for name in (
            "architecture-diagram.svg",
            "coverage-summary.md",
            "demo-script.md",
            "pr-description.md",
            "pull_request_template.md",
            "screenshots",
            "security.md",
            "submission-message.md",
        )
    },
}


def repo_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607 - fixed git command
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [f for f in out if (ROOT / f).exists()]


def main() -> int:
    files = repo_files()
    ok = True
    for folder, want in REQUIRED.items():
        have = {
            PurePosixPath(f).parts[0] if folder == "." else PurePosixPath(f).relative_to(folder).parts[0]
            for f in files
            if folder == "." or f.startswith(folder + "/")
        }
        missing = sorted(want - have)
        allowed = ALLOWED_EXTRAS.get(folder, {})
        extra = sorted(have - want - set(allowed))
        kept = sorted((have - want) & set(allowed))
        status = "OK  " if not missing and not extra else "FAIL"
        ok &= status == "OK  "
        print(f"{status} {folder:18} missing={missing or '-'}  unexpected={extra or '-'}")
        for name in kept:
            print(f"     {'':18} kept: {name} ({allowed[name]})")
    print("\nStructure matches the required tree." if ok else "\nStructure does NOT match the required tree.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
