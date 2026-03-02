from datetime import datetime, timezone

from app.services.mastery import calculate_subtopic_mastery, classify_error_pattern
from app.services.planner import build_study_plan


def test_mastery_calculation_returns_confidence_adjusted_score():
    session_questions = [
        {
            "id": "sq1",
            "question": {
                "difficulty": "basic",
                "format": "mcq",
                "expected_seconds": 120,
            },
        },
        {
            "id": "sq2",
            "question": {
                "difficulty": "advanced",
                "format": "open_ended",
                "expected_seconds": 300,
            },
        },
    ]
    attempts_by_sq = {
        "sq1": [
            {"attempt_no": 1, "is_correct": False, "response_seconds": 70},
            {"attempt_no": 2, "is_correct": True, "response_seconds": 85},
        ],
        "sq2": [
            {
                "attempt_no": 1,
                "is_correct": True,
                "rubric_score": 0.8,
                "response_seconds": 290,
            }
        ],
    }

    result = calculate_subtopic_mastery(
        session_questions=session_questions,
        attempts_by_session_question=attempts_by_sq,
        previous_snapshot_at=None,
        now=datetime.now(timezone.utc),
        second_attempt_discount=0.6,
        time_decay_lambda=0.7,
        confidence_k=6,
        forgetting_daily_decay=0.015,
    )

    assert 0 <= result["mastery_score"] <= 1
    assert 0 <= result["adjusted_mastery"] <= 1
    assert result["attempts_sample_size"] == 3


def test_error_pattern_classifier():
    speed, label = classify_error_pattern(
        expected_seconds=100,
        response_seconds=120,
        tries_to_correct=0,
    )

    assert speed == "slow"
    assert "Low understanding" in label


def test_planner_allocates_hours_to_neediest_subtopics():
    plan = build_study_plan(
        exam_date=datetime(2026, 4, 1).date(),
        hours_available_total=6,
        subtopic_rows=[
            {
                "id": "st1",
                "title": "Limits",
                "exam_weight": 1.5,
                "main_topic": {"title": "Calculus", "importance": "high"},
            },
            {
                "id": "st2",
                "title": "Vectors",
                "exam_weight": 1.0,
                "main_topic": {"title": "Linear Algebra", "importance": "medium"},
            },
        ],
        latest_mastery_by_subtopic={"st1": 0.25, "st2": 0.7},
        improvement_models_by_subtopic={
            "st1": {"estimated_gain_per_hour": 0.1},
            "st2": {"estimated_gain_per_hour": 0.06},
        },
        now=datetime.now(timezone.utc),
    )

    assert plan["total_hours_planned"] == 6
    assert plan["recommendations"][0]["subtopic"] == "Limits"
