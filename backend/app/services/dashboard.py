from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any


def summarize_dashboard(
    *,
    attempts: list[dict[str, Any]],
    session_questions: list[dict[str, Any]],
    latest_snapshots: list[dict[str, Any]],
    sessions_completed_last_14d: int,
    now: datetime,
) -> dict[str, Any]:
    start_of_day = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)

    today_time_spent_seconds = 0
    recent_total = 0
    recent_correct = 0

    for attempt in attempts:
        answered_at = attempt.get("answered_at")
        if answered_at:
            try:
                answered_dt = datetime.fromisoformat(answered_at.replace("Z", "+00:00"))
            except ValueError:
                answered_dt = now
        else:
            answered_dt = now

        if answered_dt >= start_of_day:
            today_time_spent_seconds += int(attempt.get("response_seconds", 0))

        recent_total += 1
        if attempt.get("is_correct"):
            recent_correct += 1

    attempts_by_session_question: dict[str, int] = defaultdict(int)
    for attempt in attempts:
        attempts_by_session_question[str(attempt.get("session_question_id"))] += 1

    repeated_attempt_questions = sum(1 for cnt in attempts_by_session_question.values() if cnt > 1)

    session_question_lookup = {str(row["id"]): row for row in session_questions}
    mistakes = Counter()
    for attempt in attempts:
        sq = session_question_lookup.get(str(attempt.get("session_question_id")))
        if not sq:
            continue

        question = sq.get("question", {})
        difficulty = question.get("difficulty", "unknown")
        intent = question.get("intent", "unknown")

        is_correct = bool(attempt.get("is_correct"))

        if not is_correct:
            mistakes[(difficulty, intent)] += 1

    top_mistake_patterns = [
        {
            "difficulty": difficulty,
            "intent": intent,
            "wrong_attempts": count,
        }
        for (difficulty, intent), count in mistakes.most_common(5)
    ]

    average_confidence = 0.0
    low_confidence_subtopics = 0
    if latest_snapshots:
        confidence_values = [float(snapshot.get("confidence_score", 0)) for snapshot in latest_snapshots]
        average_confidence = sum(confidence_values) / len(confidence_values)
        low_confidence_subtopics = sum(1 for score in confidence_values if score < 0.45)

    recent_accuracy = (recent_correct / recent_total) if recent_total else 0.0

    return {
        "today_time_spent_seconds": today_time_spent_seconds,
        "repeated_attempt_questions": repeated_attempt_questions,
        "recent_accuracy": recent_accuracy,
        "average_confidence": average_confidence,
        "low_confidence_subtopics": low_confidence_subtopics,
        "sessions_completed_last_14d": sessions_completed_last_14d,
        "top_mistake_patterns": top_mistake_patterns,
    }
