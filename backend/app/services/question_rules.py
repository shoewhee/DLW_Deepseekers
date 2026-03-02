from __future__ import annotations

import re
from typing import Iterable


def difficulty_weight(difficulty: str) -> float:
    if difficulty == "intermediate":
        return 1.5
    if difficulty == "advanced":
        return 2.0
    return 1.0


def estimate_expected_seconds(*, difficulty: str, format_type: str, intent: str) -> int:
    difficulty_base = {
        "basic": 70,
        "intermediate": 115,
        "advanced": 165,
    }
    format_multiplier = {
        "mcq": 1.0,
        "open_ended": 1.8,
    }
    intent_multiplier = {
        "concept": 1.0,
        "application": 1.2,
    }

    base = difficulty_base.get(difficulty, 110)
    fmt = format_multiplier.get(format_type, 1.0)
    intent_mul = intent_multiplier.get(intent, 1.0)

    seconds = int(round(base * fmt * intent_mul))
    return max(45, min(900, seconds))


def normalize_answer(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    cleaned = re.sub(r"[^a-z0-9 .,+\-*/^()=]", "", cleaned)
    return cleaned


def keyword_coverage(submitted: str, reference: str) -> float:
    submitted_tokens = {token for token in normalize_answer(submitted).split(" ") if len(token) >= 3}
    reference_tokens = {token for token in normalize_answer(reference).split(" ") if len(token) >= 3}
    if not reference_tokens:
        return 0.0
    overlap = len(submitted_tokens.intersection(reference_tokens))
    return overlap / len(reference_tokens)


def grade_open_ended(submitted: str | None, reference: str | None) -> tuple[bool, float]:
    submitted_clean = normalize_answer(submitted)
    reference_clean = normalize_answer(reference)

    if not reference_clean:
        return False, 0.0
    if submitted_clean == reference_clean:
        return True, 1.0

    coverage = keyword_coverage(submitted_clean, reference_clean)
    if coverage >= 0.8:
        return True, min(1.0, 0.75 + ((coverage - 0.8) * 1.25))
    if coverage >= 0.5:
        return False, 0.5 + ((coverage - 0.5) * 0.5)
    return False, coverage * 0.8


def normalize_options(options: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in options:
        value = str(item).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped
