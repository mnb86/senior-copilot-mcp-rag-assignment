"""Run the Document Knowledge MCP server.

python -m document_mcp                      # streamable HTTP on DOCS_MCP_HOST:DOCS_MCP_PORT (default 0.0.0.0:9100/mcp)
python -m document_mcp --transport stdio    # stdio (for desktop MCP clients / inspector)
"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .app import create_asgi_app
from .config import DocServerSettings
from .server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Document Knowledge MCP server")
    parser.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    args = parser.parse_args()
    settings = DocServerSettings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    if args.transport == "stdio":
        create_server(settings).run("stdio")
        return
    uvicorn.run(create_asgi_app(settings), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
