"""Run the simulator: ``python -m alarm_simulator``."""

from __future__ import annotations

import logging
import os

import uvicorn

from .app import create_app


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
    uvicorn.run(
        create_app(),
        host=os.getenv("SIM_HOST", "0.0.0.0"),
        port=int(os.getenv("SIM_PORT", "8000")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
