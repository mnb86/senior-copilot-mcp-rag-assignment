"""RAG ingestion: extraction (md/txt/html/pdf), metadata, chunking, idempotency, injection flagging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag.ingestion import ingest
from rag.ingestion.chunker import chunk_document, split_text
from rag.ingestion.extractors import ExtractionError, extract

DOCS = Path(__file__).resolve().parents[1] / "documents"


def test_markdown_front_matter_and_sections():
    doc = extract(DOCS / "operating-procedures/SOP-BFP-001-boiler-feed-pump-alarm-response.md", DOCS)
    assert doc.doc_id == "SOP-BFP-001" and doc.doc_type == "operating_procedure"
    assert doc.metadata["revision"] == "4.2" and "AST-BFP-101" in doc.metadata["asset_ids"]
    headings = [s.heading for s in doc.sections]
    assert "4. Pump Trip Response" in headings and "3. Low Suction Pressure Alarm (BFP PT-001.LO)" in headings
    assert doc.source_path.startswith("operating-procedures/")


def test_text_header_block_and_numbered_headings():
    doc = extract(DOCS / "maintenance-manuals/MM-BFP-010-bfp-bearings-lubrication-vibration.txt", DOCS)
    assert doc.doc_id == "MM-BFP-010" and doc.metadata["asset_types"] == ["pump", "lube_oil_system"]
    assert any(s.heading == "3.1 High bearing temperature" for s in doc.sections)


def test_html_meta_headings_and_script_removal():
    doc = extract(DOCS / "troubleshooting-guides/TG-CMP-003-compressor-discharge-pressure.html", DOCS)
    assert doc.doc_id == "TG-CMP-003" and doc.doc_type == "troubleshooting_guide"
    text = " ".join(s.text for s in doc.sections)
    assert "scripts are ignored" not in text and "anti-surge" in text.lower()
    assert any(s.heading.startswith("2. Why Discharge Pressure") for s in doc.sections)


def test_pdf_text_extraction_with_sidecar_metadata():
    doc = extract(DOCS / "safety-instructions/SI-GEN-001-rotating-equipment-restart.pdf", DOCS)
    assert doc.doc_id == "SI-GEN-001" and doc.doc_type == "safety_instruction"
    assert any("Restart Authorisation" in s.heading for s in doc.sections)
    assert "prohibited" in " ".join(s.text for s in doc.sections)


def test_unsupported_and_empty_documents_are_rejected(tmp_path):
    (tmp_path / "x.docx").write_bytes(b"PK")
    with pytest.raises(ExtractionError):
        extract(tmp_path / "x.docx")
    (tmp_path / "empty.md").write_text("---\ndoc_id: E\n---\n")
    with pytest.raises(ExtractionError):
        extract(tmp_path / "empty.md")


def test_chunking_respects_size_and_overlap():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(10))
    chunks = split_text(text, max_chars=400, overlap_chars=80)
    assert len(chunks) > 3 and all(len(c) <= 400 for c in chunks)
    assert any(" ... " in c for c in chunks[1:])  # overlap carried into following chunks
    with pytest.raises(ValueError):
        split_text("x", max_chars=10, overlap_chars=10)


def test_chunk_metadata_is_captured():
    doc = extract(DOCS / "operating-procedures/SOP-BFP-001-boiler-feed-pump-alarm-response.md", DOCS)
    chunks = chunk_document(doc)
    c = next(c for c in chunks if c.section == "4. Pump Trip Response")
    assert c.chunk_id == "SOP-BFP-001#4-pump-trip-response"
    assert c.revision == "4.2" and c.site == "NorthPlant" and "Pump Trip" in c.alarm_names
    assert c.embedding_text().startswith("Boiler Feed Pump Operation")


def test_ingest_builds_index_flags_injection_and_is_idempotent(tmp_path):
    out = tmp_path / "idx"
    first = ingest(DOCS, out, force=True)
    assert first.documents == 10 and first.chunks > 40 and not first.errors
    assert first.flagged_chunks == ["KB-VND-K301#3-note-for-automated-assistants"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["embedder"] == "lsa" and manifest["chunk_count"] == first.chunks
    stored = [json.loads(line) for line in (out / "chunks.jsonl").read_text().splitlines()]
    flagged = next(c for c in stored if c["injection_suspected"])
    assert "ignore all previous instructions" not in flagged["text"].lower() and "[redacted" in flagged["text"]
    second = ingest(DOCS, out)
    assert second.skipped_unchanged


def test_ingest_detects_changes_and_reports_bad_files(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text(
        "---\ndoc_id: A-1\ntitle: Alpha\ndoc_type: operating_procedure\n---\n# Alpha\n\n## 1. Step\n\nCheck the pump.\n"
    )
    (docs / "bad.html").write_text("<html><body></body></html>")
    r1 = ingest(docs, tmp_path / "i")
    assert r1.documents == 1 and r1.errors and "bad.html" in r1.errors[0]
    (docs / "a.md").write_text((docs / "a.md").read_text() + "\n## 2. More\n\nVerify the valve.\n")
    r2 = ingest(docs, tmp_path / "i")
    assert not r2.skipped_unchanged and r2.chunks == 2
