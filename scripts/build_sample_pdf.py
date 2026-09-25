"""Generate the sample safety-instruction PDF used to exercise PDF text extraction.

Run: python scripts/build_sample_pdf.py  (requires reportlab; the generated PDF is committed).
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUT = (
    Path(__file__).resolve().parents[1] / "rag/documents/safety-instructions/SI-GEN-001-rotating-equipment-restart.pdf"
)

META = {
    "doc_id": "SI-GEN-001",
    "title": "Safety Instruction - Rotating Equipment Isolation and Restart Authorisation",
    "doc_type": "safety_instruction",
    "revision": "6.1",
    "effective_date": "2025-10-01",
    "owner": "Corporate HSE",
    "site": "ALL",
    "asset_types": ["pump", "compressor", "motor", "fan"],
    "asset_ids": [],
    "alarm_names": ["Pump Trip", "Motor Trip", "High Vibration", "Surge Detected"],
}

SECTIONS = [
    (
        "1 Purpose",
        "This safety instruction defines the minimum requirements before rotating equipment "
        "(pumps, compressors, fans and motors) is restarted after a protective trip, and before any field "
        "inspection of equipment that may start automatically.",
    ),
    (
        "2 Restart Authorisation After a Trip",
        "A restart after a protective trip requires: (a) the first-out "
        "cause recorded in the shift log; (b) the initiating condition corrected and verified; (c) shift "
        "supervisor authorisation. Resetting a trip and restarting immediately without identifying the cause "
        "is prohibited. Protective trips and interlocks must never be bypassed to keep equipment running "
        "unless a bypass permit has been approved under the management of change procedure.",
    ),
    (
        "3 Field Inspection of Standby Equipment",
        "Standby equipment can start automatically. Before any hands-on "
        "inspection of a standby pump or motor, apply lock-out/tag-out at the motor control center and verify "
        "zero energy. Visual inspection from a safe distance does not require isolation.",
    ),
    (
        "4 Vibration and Bearing Temperature Trips",
        "Equipment that tripped on high vibration or high bearing "
        "temperature must not be restarted until reliability engineering has reviewed the vibration spectrum "
        "or the bearing condition.",
    ),
    (
        "5 Personal Protective Equipment",
        "Hearing protection, safety glasses and gloves are required within "
        "the boiler feed pump and compressor enclosures. Hot surfaces above 60 degC must be treated as a burn "
        "hazard.",
    ),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, title=META["title"], author=META["owner"], subject=META["doc_id"])
    story = [Paragraph(META["title"], styles["Title"]), Spacer(1, 12)]
    for head, text in SECTIONS:
        story += [Paragraph(head, styles["Heading2"]), Paragraph(text, styles["BodyText"]), Spacer(1, 8)]
    doc.build(story)
    OUT.with_suffix(".pdf.meta.json").write_text(json.dumps(META, indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
