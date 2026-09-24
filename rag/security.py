"""Prompt-injection defences for retrieved content.

Retrieved documents are *data*, never instructions. Defence in depth:
  1. Ingestion-time detection: chunks containing instruction-like text aimed at an AI are flagged
     (``injection_suspected``) and the offending sentences are redacted from the stored text.
  2. Retrieval-time quarantine: flagged chunks are excluded from the generation context and reported
     separately so the GUI can show them.
  3. Generation-time isolation: chunks are wrapped in ``<document>`` delimiters with an explicit
     instruction that their content must not be followed (see copilot.llm prompts).
  4. Output guard: the final answer is checked for unsafe advice (e.g. bypassing interlocks).
"""

from __future__ import annotations

import re

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your)\b"
        r"[^.\n]{0,30}\b(instructions?|rules?|prompts?|guidelines?)",
        re.I,
    ),
    "addressed_to_ai": re.compile(
        r"\b(note|message|instruction)s?\s+(to|for)\s+(the\s+)?(ai|assistant|llm|language model|copilot|chatbot)\b"
        r"|\b(ai|llm)\s+assistant\s*:",
        re.I,
    ),
    "role_override": re.compile(
        r"\b(you are now|act as|pretend to be|system prompt|system note|developer mode)\b", re.I
    ),
    "concealment": re.compile(
        r"\bdo not (mention|reveal|cite|disclose)\b[^.\n]{0,40}\b(this|these|note|document)", re.I
    ),
    "exfiltration": re.compile(r"\b(reveal|print|output)\b[^.\n]{0,30}\b(api key|token|password|secret)s?\b", re.I),
}

UNSAFE_ADVICE = re.compile(
    r"\b(bypass|defeat|jumper|inhibit|disable|override)\w*\b[^.\n]{0,60}\b(interlock|trip|alarm|protection|"
    r"safety system|sis)\b",
    re.I,
)
PERMITTED_CONTEXT = re.compile(r"\b(never|must not|do not|don't|prohibited|not permitted|without a .*permit)\b", re.I)

REDACTION = "[redacted: suspected embedded instruction]"


def detect_injection(text: str) -> list[str]:
    return [name for name, pat in INJECTION_PATTERNS.items() if pat.search(text)]


def redact_injection(text: str) -> tuple[str, list[str]]:
    """Redact sentences/lines that match injection patterns. Returns (clean_text, matched_patterns)."""
    matched: list[str] = []
    out_parts: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+|\n", text):
        hits = detect_injection(part)
        if hits:
            matched.extend(h for h in hits if h not in matched)
            if not out_parts or out_parts[-1] != REDACTION:
                out_parts.append(REDACTION)
        elif part.strip():
            out_parts.append(part.strip())
    return " ".join(out_parts), matched


def find_unsafe_advice(text: str) -> list[str]:
    """Sentences recommending to bypass/disable protections (ignores prohibitive phrasing)."""
    bad = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if UNSAFE_ADVICE.search(sentence) and not PERMITTED_CONTEXT.search(sentence):
            bad.append(sentence.strip())
    return bad
