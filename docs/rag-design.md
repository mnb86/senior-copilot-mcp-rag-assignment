# RAG design

## 1. Source documents

| doc_id | Type | Format | Scope |
| --- | --- | --- | --- |
| SOP-BFP-001 | operating_procedure | Markdown | Boiler feed pump alarm response, restart restrictions |
| SOP-DEA-002 | operating_procedure | Markdown | Deaerator level control, link to BFP low suction pressure |
| SOP-CMP-004 | operating_procedure | Markdown | Recycle gas compressor K-301 |
| MM-BFP-010 | maintenance_manual | Plain text | Bearings, lubrication, vibration diagnosis |
| MM-CW-006 | maintenance_manual | Markdown | Cooling water pump and cooling tower fan (SouthPlant) |
| TG-CMP-003 | troubleshooting_guide | HTML | Why compressor discharge pressure alarms recur |
| TG-MTR-005 | troubleshooting_guide | Markdown | Motor trips, related assets to inspect |
| SI-GEN-001 | safety_instruction | PDF (+ sidecar metadata) | Restart authorisation, never bypass interlocks |
| AP-ALM-001 | alarm_philosophy | Markdown | ISA-18.2-style priorities, floods, shelving, precedence of procedures |
| KB-VND-K301 | knowledge_article (**external**) | Markdown | Useful vendor content **plus a planted prompt injection** |

All documents are synthetic but follow the structure of real SOPs and manuals.
`scripts/build_sample_pdf.py` regenerates the PDF.

**Document metadata** is declared with each document (YAML front matter for Markdown, a `KEY: value` header for text,
`<meta>` tags for HTML, a `.meta.json` sidecar for the PDF). Example, from `SOP-BFP-001`:

```yaml
doc_id: SOP-BFP-001
title: Boiler Feed Pump Operation and Alarm Response Procedure
doc_type: operating_procedure
revision: "4.2"
effective_date: 2026-01-15
owner: NorthPlant Operations
site: NorthPlant
asset_types: [pump]
asset_ids: [AST-BFP-101, AST-BFP-102]
alarm_names: [Low Suction Pressure, Pump Trip, High Vibration, High Bearing Temperature, High Discharge Pressure, Seal Leak Detected]
```

## 2. Ingestion flow

```text
discover (rglob *.md|txt|html|pdf) → extract text + metadata → section split → chunk (900 chars, 150 overlap)
  → injection scan and redaction → BM25 statistics + LSA vectors → persist index + manifest
```

`python -m rag.ingestion --docs rag/documents --index rag/retrieval/.index [--embedder lsa|fastembed] [--force]`
(in Docker this is the one-shot `rag-ingest` service writing to the `rag-index` volume). The backend also
auto-ingests at start-up when the index is missing or stale.

## 3. Text extraction

| Format | Extractor | Metadata source |
| --- | --- | --- |
| `.md` | YAML front matter + `#`/`##` headings | front matter |
| `.txt` | `KEY: value` header block + numbered headings (`3.1 High bearing temperature`), hard wraps re-flowed | header block |
| `.html` | stdlib `HTMLParser`: `<h1-4>` headings, block tags, `<li>`; `<script>/<style>` dropped | `<meta name=…>` |
| `.pdf` | `pypdf` text + numbered headings | `<file>.pdf.meta.json` sidecar (any format can use a sidecar override) |

Files that can't be extracted are reported in the ingestion report and skipped, and the rest of the corpus is still
indexed. Duplicate `doc_id`s are rejected.

## 4. Chunking strategy

- **Structure first:** a chunk never spans two sections, so a procedure step list stays with its heading (for
  example `4. Pump Trip Response`).
- **Size:** at most 900 characters per chunk, packed from paragraphs; over-long paragraphs are split on sentence and
  list boundaries.
- **Overlap:** 150 characters of trailing context carried into the next chunk of the same section.
- **Contextual header:** the text that is embedded and indexed is `"{title}. {section}. {text}"`, which helps short
  sections match.
- **Stable ids:** `{doc_id}#{section-slug}[-n]`, e.g. `SOP-BFP-001#4-pump-trip-response`.

## 5. Chunk metadata

`chunk_id, doc_id, title, doc_type, section, ordinal, source_path, revision, effective_date, site, asset_types,
asset_ids, alarm_names, trust_level (controlled|external), injection_suspected, injection_patterns`.

## 6. Embedding model, vector index and hybrid search

**Hybrid sparse + dense, no external services.**

- **BM25** (k1 = 1.4, b = 0.75) over stemmed tokens with a domain stop-list; also yields *query-term coverage*.
- **LSA dense vectors:** TF-IDF of unigrams and bigrams projected by truncated SVD (up to 96 dimensions), cosine
  similarity. It is local, deterministic and needs only numpy, while capturing co-occurrence semantics such as
  "cavitation" ≈ "low suction pressure". `EMBEDDING_PROVIDER=fastembed` swaps in ONNX sentence embeddings
  (BAAI/bge-small-en-v1.5) behind the same `Embedder` protocol.
- **Index:** file-based (`chunks.jsonl`, `bm25.json`, `vectors.npy`, LSA model, `manifest.json`). At this corpus size
  a vector database adds operational cost without benefit; the `RetrievalIndex` / `HybridRetriever` seam is where
  Qdrant or pgvector would plug in.

## 7. Ranking

`score = 0.5 · BM25/max(BM25) + 0.5 · max(0, cosine) + boost`

| Boost | Value | When |
| --- | --- | --- |
| asset match | +0.10 | chunk `asset_ids` ∩ investigated asset + related assets |
| alarm match | +0.08 | chunk `alarm_names` ∩ focus / correlated alarm names |
| section about the alarm | +0.15 | the section heading contains the alarm name (e.g. "3. Low Suction Pressure Alarm") |
| external source | −0.10 | `trust_level = external` |

**Multi-query fusion** (`RetrievalService.search_many`): the plan's RAG step sends the primary query (focus alarm +
asset + intent hint), the user's message, correlated-cause queries and one **verification query per API
recommendation**. Results are fused by best score per chunk (derived queries weighted 0.9), and the top hit of every
confident verification query is guaranteed a place, so the recommendation check always sees the relevant procedure
passage.

## 8. Retrieval filters

- **Hard filters:** `doc_types` (e.g. procedure lookups use operating procedures, safety instructions and
  troubleshooting guides), `site` (`ALL` matches everything), `asset_types` (`all` matches everything).
- **Soft filters (boosts):** `asset_ids`, `alarm_names`.
- All filters are derived from **MCP data** (asset type, site, related assets, focus and correlated alarms), not from
  free text.
- **Fallback:** if the hard filters produce nothing or only low-confidence results, the search is repeated with only
  the soft filters and `fallback_used = true` is reported.

## 9. Citation construction

Retrieved chunks are numbered `S1..Sn` in rank order. Each citation carries `doc_id, title, section, revision,
doc_type, source_path, chunk_id, score, confidence, snippet (≤ 420 chars), trust_level`. The answer uses `[S#]`
markers; with an LLM, markers that don't exist are stripped and reported (`validate_citations`). In the GUI,
clicking a marker opens the Evidence tab and scrolls to the passage.

Example citation (acceptance scenario):

```json
{
  "id": "S1",
  "chunk_id": "SOP-BFP-001#3-low-suction-pressure-alarm-bfp-pt-001-",
  "doc_id": "SOP-BFP-001",
  "title": "Boiler Feed Pump Operation and Alarm Response Procedure",
  "section": "3. Low Suction Pressure Alarm (BFP PT-001.LO)",
  "doc_type": "operating_procedure",
  "revision": "4.2",
  "source_path": "operating-procedures/SOP-BFP-001-boiler-feed-pump-alarm-response.md",
  "score": 1.0805,
  "confidence": 0.908,
  "snippet": "Low suction pressure indicates a risk of cavitation. The most common causes, in order of frequency, are: low Deaerator 101 level, a partially blocked suction strainer, ...",
  "trust_level": "controlled"
}
```

Example retrieved chunks with score components (`bm25` raw, `dense` cosine, `boost`):

| Rank | chunk_id | score | confidence | bm25 | dense | boost |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | SOP-BFP-001#3-low-suction-pressure-alarm-bfp-pt-001- | 1.081 | 0.91 | 9.43 | 0.74 | 0.33 |
| S2 | SOP-BFP-001#5-high-bearing-temperature-alarm-tt-010- | 1.054 | 0.89 | 18.52 | 0.68 | 0.33 |
| S3 | SOP-DEA-002#1-purpose | 0.982 | 0.46 | 11.54 | 0.60 | 0.18 |
| S4 | SOP-BFP-001#7-recurring-alarms | 0.954 | 0.79 | 14.53 | 0.61 | 0.18 |
| … | SOP-BFP-001#4-pump-trip-response (guaranteed by a verification query) | | | | | |

Example recommendation verdict produced from these citations:

```json
{
  "action": "Reset the pump trip and restart the pump immediately to restore feedwater flow",
  "source": "api", "status": "conflict",
  "explanation": "Conflicts with documented restriction: \"...restart the pump after a low suction pressure trip until deaerator level has been restored\". The approved procedure takes precedence.",
  "citations": ["S8"]
}
```

## 10. Low-confidence and no-result handling

- `confidence = 0.5 · query-term coverage + 0.5 · cosine (+ boost/2)`, clipped to [0, 1]. This is an absolute
  measure, unlike the relative ranking score.
- Candidates with no lexical match **and** cosine < 0.15 are dropped. An empty result or a top confidence below
  `RAG_LOW_CONFIDENCE_THRESHOLD` (0.30) sets `low_confidence`.
- The answer then states that no procedure passage closely matches, sets confidence to at most medium, and gives no
  document-derived steps. For example, "chocolate cake recipe" returns zero results.

## 11. Prompt-injection protections

1. **Ingestion:** pattern detectors (`ignore_instructions`, `addressed_to_ai`, `role_override`, `concealment`,
   `exfiltration`) flag chunks and **redact** the offending sentences from the stored text.
2. **Retrieval:** flagged chunks are **quarantined**: never returned as results or citations, but listed with their
   matched patterns in the response and the GUI.
3. **Trust levels:** `external` documents are down-weighted and may not confirm or overrule an API recommendation in
   the consistency check.
4. **Generation isolation:** with an LLM, passages are wrapped in `<document id=… trust=…>` delimiters, and the system
   prompt declares their content untrusted data that must never be followed.
5. **Output guard:** any answer that recommends bypassing, disabling or overriding interlocks, trips, alarms or safety
   systems (prohibitive phrasing like "must never be bypassed" is allowed) is replaced by the template answer and
   flagged.
6. **Unsafe requests:** a user message asking how to bypass or disable a trip, interlock, alarm or safety system gets
   a refusal at the top of the answer and an `unsafe_request` safety flag; the read-only evidence is still returned.
7. **Secondary MCP server:** `document-knowledge` applies the same rules. `search_documents` lists quarantined passages
   separately, and `get_document_section` refuses them with a `QUARANTINED` error.

The vendor bulletin KB-VND-K301 demonstrates this. Its useful maintenance sections are retrievable, while its
"note for automated assistants" is quarantined (see `docs/screenshots/08-prompt-injection-quarantine.png`).

## 12. Index refresh

- Ingestion computes a **corpus hash** (paths, content hashes, sidecars, chunking parameters). Unchanged corpus →
  no-op; changed → full rebuild (atomic per file, fast for this corpus).
- Refresh options: re-run `make ingest` / the `rag-ingest` container, restart the backend (auto-ingest), or call
  `POST /api/rag/reindex` with `X-Admin-Token: $COPILOT_ADMIN_TOKEN`, which rebuilds and hot-swaps the retriever.
- `manifest.json` records `created_at`, embedder, per-document hash, revision and chunk counts for auditability.

## 13. Tests

`rag/tests/test_rag_ingestion.py` and `rag/tests/test_rag_retrieval.py` cover extraction for all four formats,
metadata, chunk size and overlap, idempotency and change detection, injection flagging and redaction, relevance for
representative queries, hard filters, boosts, fallback, no-result/low-confidence, quarantine, citation correctness
and multi-query fusion. `test-data/retrieval_eval.json` is the relevance regression set: `test_retrieval_eval_set` runs
every query in it and requires the expected chunk to rank first (and the off-topic query to be low confidence).

The same index is also served by the secondary MCP server (`mcp-servers/optional-secondary-server`, tools
`search_documents`, `get_document_section`, `list_documents`), tested in `tests/integration/test_document_mcp_server.py`.
