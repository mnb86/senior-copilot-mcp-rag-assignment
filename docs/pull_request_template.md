## Summary

## Scope
- [ ] MCP server / tools
- [ ] MCP client / orchestration
- [ ] RAG ingestion / retrieval
- [ ] GUI
- [ ] Packaging / CI / docs

## Architecture changes

## MCP tools added / changed

## RAG workflow changes

## Screenshots

## Test evidence
<!-- paste `make test` / coverage summary -->

## Design decisions

## Known limitations

## Review checklist
- [ ] Copilot calls the Alarm API only through the MCP server
- [ ] New tools have typed input/output schemas, validation, error mapping and tests
- [ ] Answers carry citations and an MCP trace
- [ ] No secrets committed; `.env.example` updated
- [ ] `make lint typecheck test` pass
- [ ] Docs updated (tool catalog / RAG design / architecture)
