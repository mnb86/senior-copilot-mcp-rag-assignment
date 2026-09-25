# Coverage summary

Line coverage from `pytest-cov` over the full Python suite (146 tests), the same measurement CI publishes as the
`coverage-report` artifact. Regenerate with `make coverage` (or `python -m pytest --cov`, then
`python -m coverage report --format=markdown`).

**Total: 94%** (3894/4125 statements covered, 231 missed)

| Name                                                                   |    Stmts |     Miss |   Cover |   Missing |
|----------------------------------------------------------------------- | -------: | -------: | ------: | --------: |
| apps/backend/alarm\_simulator/\_\_init\_\_.py                       |        1 |        0 |    100% |           |
| apps/backend/alarm\_simulator/analytics.py                          |      295 |       16 |     95% |39, 48, 137, 157-163, 249, 251, 341-342, 700, 847, 857 |
| apps/backend/alarm\_simulator/app.py                                |      258 |       29 |     89% |59-68, 77-82, 134, 138, 174-175, 202-203, 223, 241, 247, 251-252, 265, 353 |
| apps/backend/alarm\_simulator/catalog.py                            |       47 |        0 |    100% |           |
| apps/backend/alarm\_simulator/schemas.py                            |       62 |        0 |    100% |           |
| apps/backend/alarm\_simulator/store.py                              |      165 |        4 |     98% |82, 94, 123, 256 |
| apps/backend/copilot/\_\_init\_\_.py                                |        1 |        0 |    100% |           |
| apps/backend/copilot/api.py                                         |      105 |       20 |     81% |43, 67-68, 98, 102-103, 119-121, 129-135, 141-144 |
| apps/backend/copilot/composer.py                                    |      120 |       19 |     84% |129-148, 152-157, 200, 223 |
| apps/backend/copilot/config.py                                      |       31 |        1 |     97% |        47 |
| apps/backend/copilot/domain.py                                      |      138 |        0 |    100% |           |
| apps/backend/copilot/executor.py                                    |      197 |       19 |     90% |76, 98, 138-140, 228-232, 266-269, 274-278 |
| apps/backend/copilot/intent.py                                      |       95 |        3 |     97% |121, 123, 230 |
| apps/backend/copilot/llm.py                                         |       88 |        5 |     94% |64, 97, 109, 112-113 |
| apps/backend/copilot/mcp\_client.py                                 |      157 |       21 |     87% |24-25, 82-83, 134, 149-150, 159-163, 169-170, 209, 212, 214-217, 225 |
| apps/backend/copilot/orchestrator.py                                |      189 |        7 |     96% |53, 87, 114, 200, 256-257, 281 |
| apps/backend/copilot/planner.py                                     |      250 |       26 |     90% |68, 78, 97, 112, 114, 120-127, 135, 143, 154, 198, 224, 268-271, 434, 520-542, 560, 562, 653 |
| apps/backend/copilot/reasoning.py                                   |      187 |        6 |     97% |93, 167-168, 227, 229, 263 |
| apps/backend/copilot/retrieval\_service.py                          |       64 |        4 |     94% |     53-56 |
| connectors/\_\_init\_\_.py                                            |        3 |        0 |    100% |           |
| connectors/alarm\_api\_client.py                                      |      195 |       12 |     94% |116-117, 120, 146, 149, 156-157, 227-242, 322, 406 |
| connectors/alarm\_api\_errors.py                                      |       49 |        3 |     94% |33, 91, 94 |
| mcp-servers/alarm-management/alarm\_mcp/\_\_init\_\_.py             |        1 |        0 |    100% |           |
| mcp-servers/alarm-management/alarm\_mcp/app.py                      |       47 |        0 |    100% |           |
| mcp-servers/alarm-management/alarm\_mcp/config.py                   |       20 |        0 |    100% |           |
| mcp-servers/alarm-management/alarm\_mcp/models.py                   |      200 |        0 |    100% |           |
| mcp-servers/alarm-management/alarm\_mcp/server.py                   |      220 |        7 |     97% |20-21, 116, 124, 126, 130, 334 |
| mcp-servers/optional-secondary-server/document\_mcp/\_\_init\_\_.py |        1 |        0 |    100% |           |
| mcp-servers/optional-secondary-server/document\_mcp/app.py          |       44 |        0 |    100% |           |
| mcp-servers/optional-secondary-server/document\_mcp/config.py       |       16 |        0 |    100% |           |
| mcp-servers/optional-secondary-server/document\_mcp/models.py       |       63 |        0 |    100% |           |
| mcp-servers/optional-secondary-server/document\_mcp/server.py       |      104 |        3 |     97% |61, 86, 173 |
| rag/ingestion/\_\_init\_\_.py                                        |        2 |        0 |    100% |           |
| rag/ingestion/chunker.py                                             |       54 |        8 |     85% |29, 33, 44-48, 58 |
| rag/ingestion/extractors.py                                          |      194 |        2 |     99% |  111, 114 |
| rag/ingestion/pipeline.py                                            |       81 |        7 |     91% |37, 70, 84-85, 99-100, 105 |
| rag/ingestion/security.py                                            |       26 |        0 |    100% |           |
| rag/retrieval/\_\_init\_\_.py                                        |        3 |        0 |    100% |           |
| rag/retrieval/bm25.py                                                |       59 |        1 |     98% |        46 |
| rag/retrieval/embeddings.py                                          |       75 |        6 |     92% |127-129, 135-137 |
| rag/retrieval/index.py                                               |       49 |        1 |     98% |        67 |
| rag/retrieval/models.py                                              |       57 |        0 |    100% |           |
| rag/retrieval/retriever.py                                           |       91 |        1 |     99% |        98 |
| rag/retrieval/text.py                                                |       21 |        0 |    100% |           |
| **TOTAL**                                                              | **4125** |  **231** | **94%** |           |
