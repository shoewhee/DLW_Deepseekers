from __future__ import annotations

import math
from datetime import datetime
from typing import Any


DIFFICULTY_WEIGHT = {
    "basic": 1.0,
    "intermediate": 1.5,
    "advanced": 2.0,
}


def normalize(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def confidence_band(attempts_sample_size: int) -> str:
    if attempts_sample_size >= 10:
        return "very_reliable"
    if attempts_sample_size >= 5:
        return "somewhat_reliable"
    return "not_trusted"


def compute_time_factor(actual_seconds: int, expected_seconds: int | None, decay_lambda: float) -> float:
    expected = expected_seconds if expected_seconds and expected_seconds > 0 else 300
    overage = max(0.0, (actual_seconds - expected) / expected)
    return normalize(math.exp(-decay_lambda * overage))


def mcq_attempt_correctness(attempts: list[dict[str, Any]], alpha: float) -> float:
    if not attempts:
        return 0.0

    sorted_attempts = sorted(attempts, key=lambda item: item.get("attempt_no", 99))
    for attempt in sorted_attempts:
        if attempt.get("is_correct"):
            return 1.0 if attempt.get("attempt_no", 1) == 1 else alpha
    return 0.0


def open_ended_correctness(attempts: list[dict[str, Any]]) -> float:
    if not attempts:
        return 0.0
    rubric_score = attempts[-1].get("rubric_score")
    if rubric_score is None:
        return 0.0
    return normalize(float(rubric_score))


def derive_tries_to_correct(attempts: list[dict[str, Any]], max_attempts: int) -> int:
    for attempt in sorted(attempts, key=lambda item: item.get("attempt_no", 99)):
        if attempt.get("is_correct"):
            return int(attempt.get("attempt_no", 1))
    return 0 if len(attempts) >= max_attempts else max_attempts


def classify_error_pattern(
    *,
    expected_seconds: int | None,
    response_seconds: int,
    tries_to_correct: int,
) -> tuple[str, str]:
    expected = expected_seconds if expected_seconds and expected_seconds > 0 else 300
    speed_bucket = "fast" if response_seconds <= expected else "slow"

    if speed_bucket == "fast" and tries_to_correct == 1:
        return speed_bucket, "Well understood"
    if speed_bucket == "fast" and tries_to_correct == 2:
        return speed_bucket, "Likely careless on first attempt"
    if speed_bucket == "slow" and tries_to_correct == 1:
        return speed_bucket, "Correct but not fluent"
    if speed_bucket == "slow" and tries_to_correct == 2:
        return speed_bucket, "Poorly understood"
    if speed_bucket == "slow" and tries_to_correct == 0:
        return speed_bucket, "Low understanding, revisit fundamentals"
    if speed_bucket == "fast" and tries_to_correct == 0:
        return speed_bucket, "Reckless guessing likely"

    return speed_bucket, "Needs more evidence"


def calculate_subtopic_mastery(
    *,
    session_questions: list[dict[str, Any]],
    attempts_by_session_question: dict[str, list[dict[str, Any]]],
    previous_snapshot_at: datetime | None,
    now: datetime,
    second_attempt_discount: float,
    time_decay_lambda: float,
    confidence_k: float,
    forgetting_daily_decay: float,
) -> dict[str, float | str | int]:
    total_weight = 0.0
    weighted_accuracy_sum = 0.0
    weighted_mastery_sum = 0.0
    time_factors: list[float] = []
    attempts_sample_size = 0

    for session_question in session_questions:
        sq_id = session_question["id"]
        question = session_question["question"]
        question_attempts = attempts_by_session_question.get(sq_id, [])
        attempts_sample_size += len(question_attempts)

        difficulty = question.get("difficulty", "basic")
        weight = DIFFICULTY_WEIGHT.get(difficulty, 1.0)
        total_weight += weight

        question_format = question.get("format", "mcq")
        if question_format == "open_ended":
            attempt_adjusted = open_ended_correctness(question_attempts)
        else:
            attempt_adjusted = mcq_attempt_correctness(question_attempts, second_attempt_discount)

        total_response_seconds = sum(int(item.get("response_seconds", 0)) for item in question_attempts)
        time_factor = compute_time_factor(
            total_response_seconds,
            question.get("expected_seconds"),
            time_decay_lambda,
        )

        weighted_accuracy_sum += weight * attempt_adjusted
        weighted_mastery_sum += weight * attempt_adjusted * time_factor
        time_factors.append(time_factor)

    total_weight = max(total_weight, 1e-6)
    weighted_accuracy = normalize(weighted_accuracy_sum / total_weight)
    speed_score = normalize(sum(time_factors) / max(len(time_factors), 1))
    mastery_score = normalize(weighted_mastery_sum / total_weight)

    days_since_last_practice = 0
    if previous_snapshot_at is not None:
        delta = now - previous_snapshot_at
        days_since_last_practice = max(delta.days, 0)

    decay_factor = normalize(math.exp(-forgetting_daily_decay * days_since_last_practice))
    decayed_mastery = normalize((mastery_score * decay_factor) + ((1 - decay_factor) * 0.5))

    evidence_strength = float(attempts_sample_size)
    confidence_score = normalize(evidence_strength / (evidence_strength + confidence_k))
    adjusted_mastery = normalize((confidence_score * decayed_mastery) + ((1 - confidence_score) * 0.5))

    return {
        "attempts_sample_size": attempts_sample_size,
        "weighted_accuracy": weighted_accuracy,
        "speed_score": speed_score,
        "mastery_score": mastery_score,
        "confidence_score": confidence_score,
        "confidence_band": confidence_band(attempts_sample_size),
        "decay_factor": decay_factor,
        "adjusted_mastery": adjusted_mastery,
    }
