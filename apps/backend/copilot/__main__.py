"""Run the copilot backend: ``python -m copilot``."""

from __future__ import annotations

import logging

import uvicorn

from .api import create_app
from .config import get_settings


def main() -> None:
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run(create_app(s), host=s.host, port=s.port, log_level="warning")


if __name__ == "__main__":
    main()
