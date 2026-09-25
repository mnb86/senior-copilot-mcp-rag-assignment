"""Run the Alarm Management MCP server.

python -m alarm_mcp                      # streamable HTTP on MCP_HOST:MCP_PORT (default 0.0.0.0:9000/mcp)
python -m alarm_mcp --transport stdio    # stdio (for desktop MCP clients / inspector)
"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .app import create_asgi_app
from .config import ServerSettings
from .server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Alarm Management MCP server")
    parser.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    args = parser.parse_args()
    settings = ServerSettings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.transport == "stdio":
        create_server(settings).run("stdio")
        return
    uvicorn.run(create_asgi_app(settings), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
