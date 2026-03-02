from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from ..db import get_connection
from ..schemas import DashboardResponse, DashboardTrendsResponse, MistakePatternsResponse
from ..services.dashboard import summarize_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _safe_iso_to_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return datetime.now(timezone.utc).date().isoformat()


def _difficulty_label(value: str | None) -> str:
    difficulty = (value or "unknown").strip().lower()
    mapping = {
        "basic": "Basic",
        "intermediate": "Intermediate",
        "advanced": "Advanced",
    }
    return mapping.get(difficulty, "Unknown")


def _question_type_label(format_value: str | None, intent_value: str | None) -> str:
    format_lookup = {"mcq": "MCQ", "open_ended": "Open-ended"}
    intent_lookup = {"concept": "Concept", "application": "Application"}
    format_label = format_lookup.get((format_value or "").strip().lower(), "Other")
    intent_label = intent_lookup.get((intent_value or "").strip().lower(), "Other")
    return f"{format_label} · {intent_label}"


@router.get("/summary", response_model=DashboardResponse)
def get_dashboard_summary(user_id: str):
    conn = get_connection()
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

        session_rows = conn.execute(
            """
            select id, ended_at
            from quiz_sessions
            where user_id = ? and started_at >= ?
            """,
            (user_id, since),
        ).fetchall()
        session_ids = [row["id"] for row in session_rows]
        sessions_completed_last_14d = sum(1 for row in session_rows if row["ended_at"])

        if not session_ids:
            return DashboardResponse(
                today_time_spent_seconds=0,
                repeated_attempt_questions=0,
                recent_accuracy=0,
                average_confidence=0,
                low_confidence_subtopics=0,
                sessions_completed_last_14d=0,
                top_mistake_patterns=[],
            )

        session_placeholders = ",".join("?" for _ in session_ids)

        qsq_rows = conn.execute(
            f"""
            select id, question_id
            from quiz_session_questions
            where session_id in ({session_placeholders})
            """,
            session_ids,
        ).fetchall()
        session_questions = [dict(row) for row in qsq_rows]

        qsq_ids = [row["id"] for row in session_questions]
        question_ids = [row["question_id"] for row in session_questions]

        attempts = []
        if qsq_ids:
            qsq_placeholders = ",".join("?" for _ in qsq_ids)
            attempt_rows = conn.execute(
                f"""
                select id, session_question_id, is_correct, response_seconds, answered_at
                from question_attempts
                where session_question_id in ({qsq_placeholders})
                """,
                qsq_ids,
            ).fetchall()
            for row in attempt_rows:
                item = dict(row)
                item["is_correct"] = bool(item["is_correct"])
                attempts.append(item)

        question_lookup = {}
        if question_ids:
            question_placeholders = ",".join("?" for _ in question_ids)
            question_rows = conn.execute(
                f"""
                select id, difficulty, intent, expected_seconds
                from questions
                where id in ({question_placeholders})
                """,
                question_ids,
            ).fetchall()
            question_lookup = {row["id"]: dict(row) for row in question_rows}

        session_questions_enriched = [
            {
                "id": row["id"],
                "question": question_lookup.get(row["question_id"], {}),
            }
            for row in session_questions
        ]

        snapshot_rows = conn.execute(
            """
            select sms.subtopic_id, sms.confidence_score
            from subtopic_mastery_snapshots sms
            join (
              select subtopic_id, max(snapshot_at) as latest_snapshot_at
              from subtopic_mastery_snapshots
              where user_id = ?
              group by subtopic_id
            ) latest
            on latest.subtopic_id = sms.subtopic_id and latest.latest_snapshot_at = sms.snapshot_at
            where sms.user_id = ?
            """,
            (user_id, user_id),
        ).fetchall()

        payload = summarize_dashboard(
            attempts=attempts,
            session_questions=session_questions_enriched,
            latest_snapshots=[dict(row) for row in snapshot_rows],
            sessions_completed_last_14d=sessions_completed_last_14d,
            now=datetime.now(timezone.utc),
        )

        return DashboardResponse(**payload)
    finally:
        conn.close()


@router.get("/mistake-patterns", response_model=MistakePatternsResponse)
def get_mistake_patterns(user_id: str, topic_id: str | None = None, subtopic_id: str | None = None):
    conn = get_connection()
    try:
        scope = {
            "topic_id": None,
            "topic_title": None,
            "subtopic_id": None,
            "subtopic_title": None,
        }

        if subtopic_id:
            row = conn.execute(
                """
                select
                  st.id as subtopic_id,
                  st.title as subtopic_title,
                  mt.id as topic_id,
                  mt.title as topic_title
                from subtopics st
                join main_topics mt on mt.id = st.main_topic_id
                where st.id = ? and mt.user_id = ?
                """,
                (subtopic_id, user_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Subtopic not found")
            if topic_id and row["topic_id"] != topic_id:
                raise HTTPException(status_code=400, detail="subtopic_id does not belong to the provided topic_id")

            scope = {
                "topic_id": row["topic_id"],
                "topic_title": row["topic_title"],
                "subtopic_id": row["subtopic_id"],
                "subtopic_title": row["subtopic_title"],
            }
        elif topic_id:
            row = conn.execute(
                """
                select id, title
                from main_topics
                where id = ? and user_id = ?
                """,
                (topic_id, user_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")
            scope["topic_id"] = row["id"]
            scope["topic_title"] = row["title"]

        where_clauses = ["qs.user_id = ?", "qa.is_correct = 0"]
        params: list[str] = [user_id]
        if scope["subtopic_id"]:
            where_clauses.append("q.subtopic_id = ?")
            params.append(scope["subtopic_id"])
        elif scope["topic_id"]:
            where_clauses.append("st.main_topic_id = ?")
            params.append(scope["topic_id"])

        rows = conn.execute(
            f"""
            select q.difficulty, q.format, q.intent, count(*) as wrong_attempts
            from question_attempts qa
            join quiz_session_questions qsq on qsq.id = qa.session_question_id
            join quiz_sessions qs on qs.id = qsq.session_id
            join questions q on q.id = qsq.question_id
            join subtopics st on st.id = q.subtopic_id
            where {" and ".join(where_clauses)}
            group by q.difficulty, q.format, q.intent
            """,
            params,
        ).fetchall()

        difficulty_counts: Counter[str] = Counter()
        question_type_counts: Counter[str] = Counter()
        for row in rows:
            count = int(row["wrong_attempts"] or 0)
            if count <= 0:
                continue
            difficulty_counts[_difficulty_label(row["difficulty"])] += count
            question_type_counts[_question_type_label(row["format"], row["intent"])] += count

        ordered_difficulty = ["Basic", "Intermediate", "Advanced", "Unknown"]
        difficulty_distribution = [
            {"label": label, "count": difficulty_counts[label]}
            for label in ordered_difficulty
            if difficulty_counts[label] > 0
        ]

        type_distribution = [
            {"label": label, "count": count}
            for label, count in sorted(question_type_counts.items(), key=lambda item: (-item[1], item[0]))
        ]

        return MistakePatternsResponse(
            scope=scope,
            difficulty_distribution=difficulty_distribution,
            type_distribution=type_distribution,
        )
    finally:
        conn.close()


@router.get("/trends", response_model=DashboardTrendsResponse)
def get_dashboard_trends(user_id: str, days: int = 14):
    conn = get_connection()
    try:
        window_days = max(7, min(days, 60))
        start_dt = datetime.now(timezone.utc) - timedelta(days=window_days - 1)
        start_iso = start_dt.isoformat()

        attempts = conn.execute(
            """
            select qa.answered_at, qa.response_seconds, qa.is_correct
            from question_attempts qa
            join quiz_session_questions qsq on qsq.id = qa.session_question_id
            join quiz_sessions qs on qs.id = qsq.session_id
            where qs.user_id = ? and qa.answered_at >= ?
            """,
            (user_id, start_iso),
        ).fetchall()

        sessions = conn.execute(
            """
            select ended_at
            from quiz_sessions
            where user_id = ? and ended_at is not null and ended_at >= ?
            """,
            (user_id, start_iso),
        ).fetchall()

        snapshots = conn.execute(
            """
            select snapshot_at, adjusted_mastery
            from subtopic_mastery_snapshots
            where user_id = ? and snapshot_at >= ?
            """,
            (user_id, start_iso),
        ).fetchall()

        daily = {}
        for offset in range(window_days):
            date_key = (start_dt + timedelta(days=offset)).date().isoformat()
            daily[date_key] = {
                "study_seconds": 0,
                "correct": 0,
                "total": 0,
                "mastery_values": [],
                "quizzes_completed": 0,
            }

        for row in attempts:
            date_key = _safe_iso_to_date(row["answered_at"])
            if date_key not in daily:
                continue
            bucket = daily[date_key]
            bucket["study_seconds"] += int(row["response_seconds"] or 0)
            bucket["total"] += 1
            if bool(row["is_correct"]):
                bucket["correct"] += 1

        for row in sessions:
            date_key = _safe_iso_to_date(row["ended_at"])
            if date_key in daily:
                daily[date_key]["quizzes_completed"] += 1

        for row in snapshots:
            date_key = _safe_iso_to_date(row["snapshot_at"])
            if date_key in daily and row["adjusted_mastery"] is not None:
                daily[date_key]["mastery_values"].append(float(row["adjusted_mastery"]))

        points = []
        for date_key in sorted(daily.keys()):
            item = daily[date_key]
            accuracy = (item["correct"] / item["total"]) if item["total"] else 0.0
            mastery = (
                sum(item["mastery_values"]) / len(item["mastery_values"])
                if item["mastery_values"]
                else 0.0
            )
            points.append(
                {
                    "date": date_key,
                    "study_minutes": round(item["study_seconds"] / 60, 2),
                    "accuracy": round(accuracy, 4),
                    "avg_mastery": round(mastery, 4),
                    "quizzes_completed": item["quizzes_completed"],
                }
            )

        return DashboardTrendsResponse(points=points)
    finally:
        conn.close()
