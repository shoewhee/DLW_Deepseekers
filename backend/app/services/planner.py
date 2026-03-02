from __future__ import annotations

from datetime import date, datetime
from typing import Any


IMPORTANCE_WEIGHTS = {
    "low": 1.0,
    "medium": 1.35,
    "high": 1.7,
}


def _days_since(ts_value: str | None, now: datetime) -> int:
    if not ts_value:
        return 30
    try:
        dt = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
    except ValueError:
        return 30
    return max((now - dt).days, 0)


def _priority_score(
    *,
    importance_level: str,
    exam_weight: float,
    current_mastery: float,
    estimated_gain_per_hour: float,
    days_since_last_practice: int,
) -> float:
    importance_factor = IMPORTANCE_WEIGHTS.get(importance_level, 1.35)
    forgetting_boost = 1 + min(days_since_last_practice, 45) / 30
    return (
        importance_factor
        * max(exam_weight, 0.1)
        * max(1 - current_mastery, 0.05)
        * max(estimated_gain_per_hour, 0.01)
        * forgetting_boost
    )


def build_study_plan(
    *,
    exam_date: date,
    hours_available_total: float,
    subtopic_rows: list[dict[str, Any]],
    latest_mastery_by_subtopic: dict[str, float],
    improvement_models_by_subtopic: dict[str, dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    hours_to_allocate = max(1, int(round(hours_available_total)))

    state: dict[str, dict[str, Any]] = {}
    for row in subtopic_rows:
        subtopic_id = row["id"]
        model = improvement_models_by_subtopic.get(subtopic_id, {})
        state[subtopic_id] = {
            "subtopic_id": subtopic_id,
            "subtopic_title": row.get("title", "Untitled"),
            "main_topic_title": row.get("main_topic", {}).get("title", "Topic"),
            "importance": row.get("main_topic", {}).get("importance", "medium"),
            "exam_weight": float(row.get("exam_weight", 1.0)),
            "mastery": float(latest_mastery_by_subtopic.get(subtopic_id, 0.5)),
            "estimated_gain_per_hour": float(model.get("estimated_gain_per_hour", 0.08)),
            "last_practiced_at": model.get("last_practiced_at"),
            "hours": 0,
        }

    for _ in range(hours_to_allocate):
        if not state:
            break

        ranked = []
        for item in state.values():
            days = _days_since(item["last_practiced_at"], now)
            diminishing_gain = item["estimated_gain_per_hour"] * max(0.35, 1 - (item["hours"] * 0.1))
            priority = _priority_score(
                importance_level=item["importance"],
                exam_weight=item["exam_weight"],
                current_mastery=item["mastery"],
                estimated_gain_per_hour=diminishing_gain,
                days_since_last_practice=days,
            )
            ranked.append((priority, diminishing_gain, item))

        ranked.sort(key=lambda row: row[0], reverse=True)
        _, effective_gain, selected = ranked[0]

        selected["hours"] += 1
        selected["mastery"] = min(1.0, selected["mastery"] + effective_gain)

    recommendations = []
    for item in sorted(state.values(), key=lambda row: row["hours"], reverse=True):
        if item["hours"] == 0:
            continue
        recommendations.append(
            {
                "subtopic_id": item["subtopic_id"],
                "subtopic": item["subtopic_title"],
                "main_topic": item["main_topic_title"],
                "allocated_hours": item["hours"],
                "projected_mastery": round(item["mastery"], 4),
                "reason": (
                    "High impact because current mastery is low relative to exam importance "
                    "and expected gain per hour is strong."
                ),
            }
        )

    return {
        "exam_date": exam_date,
        "total_hours_planned": sum(item["allocated_hours"] for item in recommendations),
        "recommendations": recommendations,
    }
