from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..db import get_connection, new_id, utc_now_iso
from ..schemas import FinishQuizRequest, StartQuizRequest, SubmitAttemptRequest
from ..services.mastery import (
    calculate_subtopic_mastery,
    classify_error_pattern,
    derive_tries_to_correct,
)
from ..services.question_rules import grade_open_ended, normalize_answer

router = APIRouter(prefix="/quiz", tags=["quiz"])


def _parse_options(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _group_by_difficulty(questions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for question in questions:
        grouped[question.get("difficulty", "basic")].append(question)
    return grouped


def _select_balanced_questions(questions: list[dict[str, Any]], question_count: int) -> list[dict[str, Any]]:
    grouped = _group_by_difficulty(questions)
    selected: list[dict[str, Any]] = []

    for bucket in ("basic", "intermediate", "advanced"):
        pool = grouped.get(bucket, [])
        random.shuffle(pool)
        selected.extend(pool[:2])

    remaining_slots = max(question_count - len(selected), 0)
    if remaining_slots:
        selected_ids = {row["id"] for row in selected}
        leftovers = [row for row in questions if row["id"] not in selected_ids]
        random.shuffle(leftovers)
        selected.extend(leftovers[:remaining_slots])

    if len(selected) < question_count:
        random.shuffle(questions)
        selected_ids = {row["id"] for row in selected}
        for question in questions:
            if question["id"] in selected_ids:
                continue
            selected.append(question)
            selected_ids.add(question["id"])
            if len(selected) >= question_count:
                break

    return selected[:question_count]


def _sanitize_question_for_quiz(question_row: dict[str, Any]) -> dict[str, Any]:
    output = {
        "id": question_row["id"],
        "prompt": question_row["prompt"],
        "difficulty": question_row["difficulty"],
        "format": question_row["format"],
        "intent": question_row["intent"],
        "expected_seconds": question_row["expected_seconds"],
        "weight": question_row["weight"],
        "subtopic_id": question_row["subtopic_id"],
    }

    if question_row["format"] == "mcq":
        output["options"] = _parse_options(question_row.get("options_json"))

    return output


def _attempt_summary_for_question(attempts: list[dict[str, Any]]) -> tuple[bool, int]:
    if not attempts:
        return False, 0
    is_correct = any(bool(item.get("is_correct")) for item in attempts)
    total_seconds = sum(int(item.get("response_seconds", 0)) for item in attempts)
    return is_correct, total_seconds


@router.post("/sessions/start")
def start_quiz_session(payload: StartQuizRequest):
    conn = get_connection()
    try:
        subtopic_row = conn.execute(
            """
            select st.id, st.main_topic_id
            from subtopics st
            join main_topics mt on mt.id = st.main_topic_id
            where st.id = ? and mt.user_id = ?
            """,
            (payload.subtopic_id, payload.user_id),
        ).fetchone()
        if not subtopic_row:
            raise HTTPException(status_code=404, detail="Subtopic not found")

        question_rows = conn.execute(
            """
            select id, prompt, difficulty, format, intent, expected_seconds, weight, subtopic_id, options_json
            from questions
            where subtopic_id = ?
            """,
            (payload.subtopic_id,),
        ).fetchall()
        questions = [dict(row) for row in question_rows]

        if len(questions) < 3:
            raise HTTPException(
                status_code=400,
                detail="Need at least 3 questions in the bank for this subtopic",
            )

        selected_questions = _select_balanced_questions(questions, payload.question_count)
        now = utc_now_iso()
        session_id = new_id()

        conn.execute(
            """
            insert into quiz_sessions (
              id, user_id, main_topic_id, session_type, started_at, ended_at, exam_date, hours_left_to_exam, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                payload.user_id,
                payload.main_topic_id or subtopic_row["main_topic_id"],
                "quiz",
                now,
                None,
                payload.exam_date.isoformat() if payload.exam_date else None,
                payload.hours_left_to_exam,
                now,
            ),
        )

        qsq_rows: list[dict[str, Any]] = []
        for idx, question in enumerate(selected_questions, start=1):
            qsq_id = new_id()
            max_attempts = 2 if question["format"] == "mcq" else 1
            allocated_seconds = int(question.get("expected_seconds") or 300)
            conn.execute(
                """
                insert into quiz_session_questions (id, session_id, question_id, position, max_attempts, allocated_seconds)
                values (?, ?, ?, ?, ?, ?)
                """,
                (qsq_id, session_id, question["id"], idx, max_attempts, allocated_seconds),
            )
            qsq_rows.append(
                {
                    "id": qsq_id,
                    "session_id": session_id,
                    "question_id": question["id"],
                    "position": idx,
                    "max_attempts": max_attempts,
                    "allocated_seconds": allocated_seconds,
                }
            )

        conn.commit()

        question_lookup = {row["id"]: _sanitize_question_for_quiz(row) for row in selected_questions}

        return {
            "session": {
                "id": session_id,
                "user_id": payload.user_id,
                "main_topic_id": payload.main_topic_id or subtopic_row["main_topic_id"],
                "session_type": "quiz",
                "started_at": now,
                "ended_at": None,
                "exam_date": payload.exam_date.isoformat() if payload.exam_date else None,
                "hours_left_to_exam": payload.hours_left_to_exam,
                "created_at": now,
            },
            "questions": [
                {
                    "id": row["id"],
                    "session_question_id": row["id"],
                    "position": row["position"],
                    "max_attempts": row["max_attempts"],
                    "allocated_seconds": row["allocated_seconds"],
                    "question": question_lookup[row["question_id"]],
                }
                for row in sorted(qsq_rows, key=lambda item: item["position"])
            ],
        }
    finally:
        conn.close()


@router.get("/sessions/{session_id}")
def get_quiz_session(session_id: str, user_id: str):
    conn = get_connection()
    try:
        session = conn.execute(
            """
            select id, started_at, ended_at, main_topic_id
            from quiz_sessions
            where id = ? and user_id = ?
            """,
            (session_id, user_id),
        ).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        qsq_rows = conn.execute(
            """
            select id, position, max_attempts, allocated_seconds, question_id
            from quiz_session_questions
            where session_id = ?
            order by position asc
            """,
            (session_id,),
        ).fetchall()

        question_lookup: dict[str, dict[str, Any]] = {}
        question_ids = [row["question_id"] for row in qsq_rows]
        if question_ids:
            placeholders = ",".join("?" for _ in question_ids)
            query = f"""
                select id, prompt, difficulty, format, intent, expected_seconds, weight, subtopic_id, options_json
                from questions
                where id in ({placeholders})
            """
            question_rows = conn.execute(query, question_ids).fetchall()
            question_lookup = {row["id"]: _sanitize_question_for_quiz(dict(row)) for row in question_rows}

        attempts_by_q: dict[str, list[dict[str, Any]]] = defaultdict(list)
        qsq_ids = [row["id"] for row in qsq_rows]
        if qsq_ids:
            placeholders = ",".join("?" for _ in qsq_ids)
            query = f"""
                select id, session_question_id, attempt_no, is_correct, response_seconds, rubric_score, answered_at
                from question_attempts
                where session_question_id in ({placeholders})
                order by attempt_no asc
            """
            attempt_rows = conn.execute(query, qsq_ids).fetchall()
            for row in attempt_rows:
                item = dict(row)
                item["is_correct"] = bool(item["is_correct"])
                attempts_by_q[item["session_question_id"]].append(item)

        enriched = []
        for row in qsq_rows:
            item = dict(row)
            item["question"] = question_lookup.get(row["question_id"])
            item["attempts"] = attempts_by_q.get(row["id"], [])
            enriched.append(item)

        return {
            "session": dict(session),
            "questions": enriched,
        }
    finally:
        conn.close()


@router.post("/sessions/{session_id}/attempt")
def submit_attempt(session_id: str, payload: SubmitAttemptRequest):
    conn = get_connection()
    try:
        session = conn.execute(
            "select id from quiz_sessions where id = ? and user_id = ?",
            (session_id, payload.user_id),
        ).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_question = conn.execute(
            """
            select
              qsq.id,
              qsq.max_attempts,
              qsq.question_id,
              q.expected_seconds,
              q.format,
              q.correct_answer,
              q.options_json
            from quiz_session_questions qsq
            join questions q on q.id = qsq.question_id
            where qsq.id = ? and qsq.session_id = ?
            """,
            (payload.session_question_id, session_id),
        ).fetchone()
        if not session_question:
            raise HTTPException(status_code=404, detail="Question not found in this session")

        existing_rows = conn.execute(
            """
            select id, attempt_no, is_correct, response_seconds, rubric_score
            from question_attempts
            where session_question_id = ?
            order by attempt_no asc
            """,
            (payload.session_question_id,),
        ).fetchall()
        existing_attempts = [dict(row) for row in existing_rows]
        for item in existing_attempts:
            item["is_correct"] = bool(item["is_correct"])

        if len(existing_attempts) >= int(session_question["max_attempts"]):
            raise HTTPException(status_code=400, detail="No remaining attempts")
        if any(item.get("is_correct") for item in existing_attempts):
            raise HTTPException(status_code=400, detail="Question already answered correctly")

        submitted_answer = payload.submitted_answer or ""
        question_format = session_question["format"]
        reference_answer = session_question["correct_answer"]

        if question_format == "open_ended":
            is_correct, rubric = grade_open_ended(submitted_answer, reference_answer)
        else:
            options = _parse_options(session_question["options_json"])
            normalized_submitted = normalize_answer(submitted_answer)
            normalized_reference = normalize_answer(reference_answer)

            if len(submitted_answer.strip()) == 1 and submitted_answer.strip().upper() in {"A", "B", "C", "D"}:
                idx = ord(submitted_answer.strip().upper()) - ord("A")
                if idx < len(options):
                    normalized_submitted = normalize_answer(options[idx])

            is_correct = normalized_submitted and normalized_submitted == normalized_reference
            rubric = None

        next_attempt_no = len(existing_attempts) + 1
        attempt_id = new_id()
        now = utc_now_iso()

        conn.execute(
            """
            insert into question_attempts (
              id, session_question_id, attempt_no, submitted_answer, is_correct, rubric_score, answered_at, response_seconds
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                payload.session_question_id,
                next_attempt_no,
                submitted_answer,
                1 if is_correct else 0,
                rubric,
                now,
                payload.response_seconds,
            ),
        )

        attempt_row = {
            "id": attempt_id,
            "session_question_id": payload.session_question_id,
            "attempt_no": next_attempt_no,
            "submitted_answer": submitted_answer,
            "is_correct": bool(is_correct),
            "rubric_score": rubric,
            "answered_at": now,
            "response_seconds": payload.response_seconds,
        }

        combined_attempts = [*existing_attempts, attempt_row]
        tries_to_correct = derive_tries_to_correct(combined_attempts, int(session_question["max_attempts"]))

        speed_bucket, analysis_label = classify_error_pattern(
            expected_seconds=session_question["expected_seconds"],
            response_seconds=payload.response_seconds,
            tries_to_correct=tries_to_correct,
        )

        conn.execute(
            """
            insert into attempt_analysis (
              id, question_attempt_id, speed_bucket, tries_to_correct, analysis_label, created_at
            ) values (?, ?, ?, ?, ?, ?)
            """,
            (new_id(), attempt_id, speed_bucket, tries_to_correct, analysis_label, now),
        )

        conn.execute(
            """
            insert into study_activity_events (
              id, user_id, subtopic_id, session_id, event_type, event_payload, occurred_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                payload.user_id,
                None,
                session_id,
                "question_attempted",
                json.dumps(
                    {
                        "session_question_id": payload.session_question_id,
                        "attempt_no": next_attempt_no,
                        "is_correct": bool(is_correct),
                        "response_seconds": payload.response_seconds,
                        "analysis_label": analysis_label,
                    }
                ),
                now,
            ),
        )

        conn.commit()

        remaining_attempts = max(int(session_question["max_attempts"]) - next_attempt_no, 0)

        return {
            "attempt": attempt_row,
            "analysis": {
                "speed_bucket": speed_bucket,
                "tries_to_correct": tries_to_correct,
                "analysis_label": analysis_label,
            },
            "remaining_attempts": remaining_attempts,
        }
    finally:
        conn.close()


@router.post("/sessions/{session_id}/finish")
def finish_quiz_session(session_id: str, payload: FinishQuizRequest):
    conn = get_connection()
    settings = get_settings()

    try:
        session = conn.execute(
            "select id, started_at from quiz_sessions where id = ? and user_id = ?",
            (session_id, payload.user_id),
        ).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_question_rows = conn.execute(
            """
            select
              qsq.id,
              qsq.max_attempts,
              q.id as question_id,
              q.subtopic_id,
              q.difficulty,
              q.format,
              q.intent,
              q.expected_seconds,
              q.weight
            from quiz_session_questions qsq
            join questions q on q.id = qsq.question_id
            where qsq.session_id = ?
            order by qsq.position asc
            """,
            (session_id,),
        ).fetchall()
        if not session_question_rows:
            raise HTTPException(status_code=400, detail="No questions attached to session")

        session_questions_with_question: list[dict[str, Any]] = []
        sq_ids: list[str] = []
        for row in session_question_rows:
            item = dict(row)
            sq_ids.append(item["id"])
            session_questions_with_question.append(
                {
                    "id": item["id"],
                    "max_attempts": item["max_attempts"],
                    "question": {
                        "id": item["question_id"],
                        "subtopic_id": item["subtopic_id"],
                        "difficulty": item["difficulty"],
                        "format": item["format"],
                        "intent": item["intent"],
                        "expected_seconds": item["expected_seconds"],
                        "weight": item["weight"],
                    },
                }
            )

        attempts_by_sq: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if sq_ids:
            placeholders = ",".join("?" for _ in sq_ids)
            query = f"""
                select id, session_question_id, attempt_no, is_correct, response_seconds, rubric_score
                from question_attempts
                where session_question_id in ({placeholders})
                order by attempt_no asc
            """
            attempt_rows = conn.execute(query, sq_ids).fetchall()
            for row in attempt_rows:
                item = dict(row)
                item["is_correct"] = bool(item["is_correct"])
                attempts_by_sq[item["session_question_id"]].append(item)

        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()

        by_subtopic: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in session_questions_with_question:
            by_subtopic[row["question"]["subtopic_id"]].append(row)

        snapshots = []
        for subtopic_id, sq_rows in by_subtopic.items():
            previous_row = conn.execute(
                """
                select snapshot_at
                from subtopic_mastery_snapshots
                where user_id = ? and subtopic_id = ?
                order by snapshot_at desc
                limit 1
                """,
                (payload.user_id, subtopic_id),
            ).fetchone()

            previous_snapshot_at = None
            if previous_row:
                previous_snapshot_at = datetime.fromisoformat(previous_row["snapshot_at"].replace("Z", "+00:00"))

            result = calculate_subtopic_mastery(
                session_questions=sq_rows,
                attempts_by_session_question=attempts_by_sq,
                previous_snapshot_at=previous_snapshot_at,
                now=now_dt,
                second_attempt_discount=settings.mastery_second_attempt_discount,
                time_decay_lambda=settings.mastery_time_decay_lambda,
                confidence_k=settings.mastery_confidence_k,
                forgetting_daily_decay=settings.forgetting_daily_decay,
            )

            snapshot_id = new_id()
            conn.execute(
                """
                insert into subtopic_mastery_snapshots (
                  id, user_id, subtopic_id, snapshot_at, attempts_sample_size, weighted_accuracy,
                  speed_score, mastery_score, confidence_score, confidence_band, decay_factor, adjusted_mastery
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    payload.user_id,
                    subtopic_id,
                    now,
                    result["attempts_sample_size"],
                    result["weighted_accuracy"],
                    result["speed_score"],
                    result["mastery_score"],
                    result["confidence_score"],
                    result["confidence_band"],
                    result["decay_factor"],
                    result["adjusted_mastery"],
                ),
            )

            snapshots.append(
                {
                    "id": snapshot_id,
                    "user_id": payload.user_id,
                    "subtopic_id": subtopic_id,
                    "snapshot_at": now,
                    **result,
                }
            )

        conn.execute("update quiz_sessions set ended_at = ? where id = ?", (now, session_id))

        total_questions = len(session_questions_with_question)
        correct_questions = 0
        total_time_seconds = 0
        for row in session_questions_with_question:
            sq_attempts = attempts_by_sq.get(row["id"], [])
            is_correct, question_seconds = _attempt_summary_for_question(sq_attempts)
            total_time_seconds += question_seconds
            if is_correct:
                correct_questions += 1

        started_at = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
        session_duration_seconds = max(int((now_dt - started_at).total_seconds()), 0)

        conn.execute(
            """
            insert into study_activity_events (
              id, user_id, subtopic_id, session_id, event_type, event_payload, occurred_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                payload.user_id,
                None,
                session_id,
                "quiz_finished",
                json.dumps(
                    {
                        "snapshot_count": len(snapshots),
                        "overall_score": round((correct_questions / max(total_questions, 1)) * 100, 2),
                        "total_time_seconds": total_time_seconds,
                    }
                ),
                now,
            ),
        )

        conn.commit()

        ranked_snapshots = sorted(snapshots, key=lambda row: float(row.get("adjusted_mastery", 0)))
        weaknesses = ranked_snapshots[:2]
        strengths = list(reversed(ranked_snapshots[-2:]))

        overall_score = round((correct_questions / max(total_questions, 1)) * 100, 2)

        return {
            "snapshots": snapshots,
            "summary": {
                "overall_score": overall_score,
                "correct_questions": correct_questions,
                "total_questions": total_questions,
                "total_time_seconds": total_time_seconds,
                "session_duration_seconds": session_duration_seconds,
                "strengths": strengths,
                "weaknesses": weaknesses,
            },
        }
    finally:
        conn.close()
