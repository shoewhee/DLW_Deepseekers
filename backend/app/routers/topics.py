from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..db import get_connection, new_id, utc_now_iso
from ..schemas import (
    NoteCreate,
    QuestionCreate,
    QuestionGenerateRequest,
    SubtopicCreate,
    SubtopicUpdate,
    TopicCreate,
    TopicIngestRequest,
    TopicUpdate,
)
from ..services.openai_helper import (
    generate_questions_with_ai,
    generate_topic_breakdown_with_ai,
)
from ..services.pdf_text import extract_pdf_text_from_bytes
from ..services.question_rules import (
    difficulty_weight,
    estimate_expected_seconds,
    normalize_options,
)

router = APIRouter(prefix="/topics", tags=["topics"])


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


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


def _auth_subtopic(conn: sqlite3.Connection, *, subtopic_id: str, user_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        select st.id, st.title, st.description, st.main_topic_id, mt.title as main_topic_title
        from subtopics st
        join main_topics mt on mt.id = st.main_topic_id
        where st.id = ? and mt.user_id = ?
        """,
        (subtopic_id, user_id),
    ).fetchone()


def _prepare_question_payload(payload: QuestionCreate) -> dict:
    format_type = payload.format
    options = normalize_options(payload.options or [])
    correct_answer = payload.correct_answer.strip()

    if format_type == "mcq":
        if len(options) < 2:
            raise HTTPException(status_code=400, detail="MCQ requires at least two options")

        option_lookup = {option.lower(): option for option in options}
        if correct_answer.lower() not in option_lookup:
            raise HTTPException(status_code=400, detail="correct_answer must match one of the MCQ options")
        correct_answer = option_lookup[correct_answer.lower()]
    else:
        options = []
        if not correct_answer:
            raise HTTPException(status_code=400, detail="Open-ended questions require a reference answer")

    return {
        "prompt": payload.prompt.strip(),
        "difficulty": payload.difficulty,
        "format": format_type,
        "intent": payload.intent,
        "options": options,
        "correct_answer": correct_answer,
        "expected_seconds": estimate_expected_seconds(
            difficulty=payload.difficulty,
            format_type=format_type,
            intent=payload.intent,
        ),
        "weight": difficulty_weight(payload.difficulty),
    }


def _coerce_generated_question(item: dict) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    difficulty = str(item.get("difficulty", "basic")).strip().lower()
    if difficulty not in {"basic", "intermediate", "advanced"}:
        difficulty = "basic"

    format_type = str(item.get("format", "mcq")).strip().lower()
    if format_type not in {"mcq", "open_ended"}:
        format_type = "mcq"

    intent = str(item.get("intent", "concept")).strip().lower()
    if intent not in {"concept", "application"}:
        intent = "concept"

    prompt = " ".join(str(item.get("prompt", "")).strip().split())
    if not prompt:
        return None

    raw_options = item.get("options")
    options = normalize_options(raw_options if isinstance(raw_options, list) else [])
    correct_answer = " ".join(str(item.get("correct_answer", "")).strip().split())

    if format_type == "mcq":
        if len(options) < 2:
            return None
        option_lookup = {option.lower(): option for option in options}

        if len(correct_answer) == 1 and correct_answer.upper() in {"A", "B", "C", "D"}:
            idx = ord(correct_answer.upper()) - ord("A")
            if idx < len(options):
                correct_answer = options[idx]

        if correct_answer.lower() not in option_lookup:
            return None
        else:
            correct_answer = option_lookup[correct_answer.lower()]
    else:
        options = []
        if not correct_answer:
            return None

    return {
        "prompt": prompt,
        "difficulty": difficulty,
        "format": format_type,
        "intent": intent,
        "options": options,
        "correct_answer": correct_answer,
    }


def _serialize_question_row(row: sqlite3.Row, *, include_answers: bool) -> dict:
    output = {
        "id": row["id"],
        "subtopic_id": row["subtopic_id"],
        "prompt": row["prompt"],
        "difficulty": row["difficulty"],
        "format": row["format"],
        "intent": row["intent"],
        "expected_seconds": row["expected_seconds"],
        "weight": row["weight"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }

    options = _parse_options(row["options_json"])
    if row["format"] == "mcq":
        output["options"] = options

    if include_answers:
        output["correct_answer"] = row["correct_answer"]

    return output


def _dedupe_strings(values: list[str], *, max_items: int = 6) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value).strip().split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized[:180])
        if len(output) >= max_items:
            break
    return output


def _coerce_ingested_subtopics(raw_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not raw_result or not isinstance(raw_result, dict):
        return []

    topic_obj = raw_result.get("topic")
    if not isinstance(topic_obj, dict):
        return []

    raw_subtopics = topic_obj.get("subtopics")
    if not isinstance(raw_subtopics, list):
        return []

    output: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for item in raw_subtopics:
        if not isinstance(item, dict):
            continue

        name = " ".join(str(item.get("name", "")).strip().split())[:120]
        if not name:
            continue
        lowered = name.lower()
        if lowered in seen_names:
            continue

        concepts = item.get("concepts")
        normalized_concepts = _dedupe_strings(concepts if isinstance(concepts, list) else [], max_items=6)
        if not normalized_concepts:
            continue

        mastery_score = item.get("masteryScore")
        if mastery_score is None:
            mastery_score = item.get("mastery_score")

        output.append(
            {
                "name": name,
                "concepts": normalized_concepts,
                "mastery_score": mastery_score,
            }
        )
        seen_names.add(lowered)
        if len(output) >= 8:
            break

    return output


def _mastery_to_exam_weight(raw_value: Any) -> float:
    try:
        mastery = float(raw_value)
    except (TypeError, ValueError):
        mastery = 0.5
    mastery = max(0.0, min(1.0, mastery))

    # Lower mastery -> higher exam weight.
    return round(0.8 + ((1.0 - mastery) * 1.2), 2)


def _concepts_to_description(concepts: list[str]) -> str:
    if not concepts:
        return ""
    preview = concepts[:4]
    return f"Key concepts: {'; '.join(preview)}"


def _concepts_note_body(topic_title: str, subtopic_title: str, concepts: list[str]) -> str:
    lines = [
        f"Auto-generated concept list for **{subtopic_title}** in **{topic_title}**.",
        "",
        "Focus concepts:",
    ]
    lines.extend([f"- {concept}" for concept in concepts])
    return "\n".join(lines)


@router.get("")
def list_topics(user_id: str):
    conn = get_connection()
    try:
        topic_rows = conn.execute(
            """
            select id, title, description, importance, created_at, updated_at
            from main_topics
            where user_id = ?
            order by created_at asc
            """,
            (user_id,),
        ).fetchall()

        topics = []
        for topic_row in topic_rows:
            topic = _row_to_dict(topic_row)
            subtopic_rows = conn.execute(
                """
                select
                  st.id,
                  st.title,
                  st.description,
                  st.exam_weight,
                  st.main_topic_id,
                  sms.mastery_score,
                  sms.confidence_score,
                  sms.confidence_band,
                  sms.adjusted_mastery
                from subtopics st
                left join subtopic_mastery_snapshots sms
                  on sms.id = (
                    select s2.id
                    from subtopic_mastery_snapshots s2
                    where s2.user_id = ? and s2.subtopic_id = st.id
                    order by s2.snapshot_at desc
                    limit 1
                  )
                where st.main_topic_id = ?
                order by st.created_at asc
                """,
                (user_id, topic["id"]),
            ).fetchall()

            subtopics = []
            for subtopic_row in subtopic_rows:
                subtopic = {
                    "id": subtopic_row["id"],
                    "title": subtopic_row["title"],
                    "description": subtopic_row["description"],
                    "exam_weight": subtopic_row["exam_weight"],
                    "main_topic_id": subtopic_row["main_topic_id"],
                }
                if subtopic_row["adjusted_mastery"] is not None:
                    subtopic["latest_mastery"] = {
                        "subtopic_id": subtopic_row["id"],
                        "mastery_score": subtopic_row["mastery_score"],
                        "confidence_score": subtopic_row["confidence_score"],
                        "confidence_band": subtopic_row["confidence_band"],
                        "adjusted_mastery": subtopic_row["adjusted_mastery"],
                    }
                subtopics.append(subtopic)

            topic["subtopics"] = subtopics
            topics.append(topic)

        return topics
    finally:
        conn.close()


@router.post("")
def create_topic(payload: TopicCreate):
    if payload.importance not in {"low", "medium", "high"}:
        raise HTTPException(status_code=400, detail="importance must be low/medium/high")

    conn = get_connection()
    try:
        user_exists = conn.execute("select id from users where id = ?", (payload.user_id,)).fetchone()
        if not user_exists:
            raise HTTPException(status_code=404, detail="User not found")

        topic_id = new_id()
        now = utc_now_iso()

        conn.execute(
            """
            insert into main_topics (id, user_id, title, description, importance, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_id,
                payload.user_id,
                payload.title,
                payload.description,
                payload.importance,
                now,
                now,
            ),
        )
        conn.commit()

        row = conn.execute(
            "select id, user_id, title, description, importance, created_at, updated_at from main_topics where id = ?",
            (topic_id,),
        ).fetchone()
        return _row_to_dict(row)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/ingest")
def ingest_topic_from_pdf(payload: TopicIngestRequest):
    topic_title = " ".join(payload.title.strip().split())
    if not topic_title:
        raise HTTPException(status_code=400, detail="title is required")

    if payload.importance not in {"low", "medium", "high"}:
        raise HTTPException(status_code=400, detail="importance must be low/medium/high")

    filename = payload.file_name.strip().lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF")

    try:
        file_bytes = base64.b64decode(payload.file_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid PDF payload encoding") from exc

    if len(file_bytes) < 8:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        source_text = extract_pdf_text_from_bytes(file_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Unable to extract text from the uploaded PDF") from exc

    if not source_text.strip():
        raise HTTPException(status_code=400, detail="No extractable text found in uploaded PDF")

    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is required for AI topic ingestion from PDF")

    ai_result = generate_topic_breakdown_with_ai(topic_title=topic_title, source_text=source_text)
    if not ai_result:
        raise HTTPException(status_code=502, detail="OpenAI did not return a valid topic breakdown. Please retry.")

    subtopic_specs = _coerce_ingested_subtopics(ai_result)
    if not subtopic_specs:
        raise HTTPException(
            status_code=502,
            detail="OpenAI returned an unusable topic breakdown. Try a clearer PDF or retry.",
        )

    conn = get_connection()
    try:
        user_exists = conn.execute("select id from users where id = ?", (payload.user_id,)).fetchone()
        if not user_exists:
            raise HTTPException(status_code=404, detail="User not found")

        duplicate = conn.execute(
            "select id from main_topics where user_id = ? and lower(title) = lower(?)",
            (payload.user_id, topic_title),
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail="A topic with this title already exists")

        topic_id = new_id()
        now = utc_now_iso()

        conn.execute(
            """
            insert into main_topics (id, user_id, title, description, importance, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_id,
                payload.user_id,
                topic_title,
                f"Imported from PDF: {payload.file_name}",
                payload.importance,
                now,
                now,
            ),
        )

        created_subtopics = []
        concept_count = 0
        notes_created = 0

        for spec in subtopic_specs:
            subtopic_id = new_id()
            concepts = spec["concepts"]
            concept_count += len(concepts)

            conn.execute(
                """
                insert into subtopics (id, main_topic_id, title, description, exam_weight, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subtopic_id,
                    topic_id,
                    spec["name"],
                    _concepts_to_description(concepts),
                    _mastery_to_exam_weight(spec.get("mastery_score")),
                    now,
                    now,
                ),
            )

            note_id = new_id()
            conn.execute(
                """
                insert into notes (id, subtopic_id, parent_note_id, title, body_md, source_url, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    note_id,
                    subtopic_id,
                    None,
                    "Generated concepts from uploaded PDF",
                    _concepts_note_body(topic_title, spec["name"], concepts),
                    None,
                    now,
                    now,
                ),
            )
            notes_created += 1

            created_subtopics.append(
                {
                    "id": subtopic_id,
                    "title": spec["name"],
                    "concepts": concepts,
                    "exam_weight": _mastery_to_exam_weight(spec.get("mastery_score")),
                }
            )

        conn.commit()

        return {
            "generated_by": "openai",
            "topic": {
                "id": topic_id,
                "title": topic_title,
                "importance": payload.importance,
            },
            "subtopics_created": len(created_subtopics),
            "concepts_captured": concept_count,
            "notes_created": notes_created,
            "subtopics": created_subtopics,
        }
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.patch("/{topic_id}")
def update_topic(topic_id: str, payload: TopicUpdate):
    if payload.importance is not None and payload.importance not in {"low", "medium", "high"}:
        raise HTTPException(status_code=400, detail="importance must be low/medium/high")

    conn = get_connection()
    try:
        existing = conn.execute(
            "select id from main_topics where id = ? and user_id = ?",
            (topic_id, payload.user_id),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Topic not found")

        updates = []
        values = []
        if payload.title is not None:
            updates.append("title = ?")
            values.append(payload.title)
        if payload.description is not None:
            updates.append("description = ?")
            values.append(payload.description)
        if payload.importance is not None:
            updates.append("importance = ?")
            values.append(payload.importance)

        updates.append("updated_at = ?")
        values.append(utc_now_iso())
        values.append(topic_id)

        conn.execute(f"update main_topics set {', '.join(updates)} where id = ?", values)
        conn.commit()

        row = conn.execute(
            "select id, user_id, title, description, importance, created_at, updated_at from main_topics where id = ?",
            (topic_id,),
        ).fetchone()
        return _row_to_dict(row)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/{topic_id}/subtopics")
def create_subtopic(topic_id: str, payload: SubtopicCreate):
    conn = get_connection()
    try:
        topic_row = conn.execute(
            "select id from main_topics where id = ? and user_id = ?",
            (topic_id, payload.user_id),
        ).fetchone()
        if not topic_row:
            raise HTTPException(status_code=404, detail="Topic not found")

        subtopic_id = new_id()
        now = utc_now_iso()

        conn.execute(
            """
            insert into subtopics (id, main_topic_id, title, description, exam_weight, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (subtopic_id, topic_id, payload.title, payload.description, payload.exam_weight, now, now),
        )
        conn.commit()

        row = conn.execute(
            "select id, main_topic_id, title, description, exam_weight, created_at, updated_at from subtopics where id = ?",
            (subtopic_id,),
        ).fetchone()
        return _row_to_dict(row)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.patch("/subtopics/{subtopic_id}")
def update_subtopic(subtopic_id: str, payload: SubtopicUpdate):
    conn = get_connection()
    try:
        auth_check = _auth_subtopic(conn, subtopic_id=subtopic_id, user_id=payload.user_id)
        if not auth_check:
            raise HTTPException(status_code=404, detail="Subtopic not found")

        updates = []
        values = []
        if payload.title is not None:
            updates.append("title = ?")
            values.append(payload.title)
        if payload.description is not None:
            updates.append("description = ?")
            values.append(payload.description)
        if payload.exam_weight is not None:
            updates.append("exam_weight = ?")
            values.append(payload.exam_weight)

        updates.append("updated_at = ?")
        values.append(utc_now_iso())
        values.append(subtopic_id)

        conn.execute(f"update subtopics set {', '.join(updates)} where id = ?", values)
        conn.commit()

        row = conn.execute(
            "select id, main_topic_id, title, description, exam_weight, created_at, updated_at from subtopics where id = ?",
            (subtopic_id,),
        ).fetchone()
        return _row_to_dict(row)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/subtopics/{subtopic_id}/notes")
def list_notes(subtopic_id: str, user_id: str):
    conn = get_connection()
    try:
        auth_check = _auth_subtopic(conn, subtopic_id=subtopic_id, user_id=user_id)
        if not auth_check:
            raise HTTPException(status_code=404, detail="Subtopic not found")

        notes = conn.execute(
            """
            select id, title, body_md, source_url, parent_note_id, created_at, updated_at
            from notes
            where subtopic_id = ?
            order by created_at asc
            """,
            (subtopic_id,),
        ).fetchall()

        return [_row_to_dict(row) for row in notes]
    finally:
        conn.close()


@router.post("/subtopics/{subtopic_id}/notes")
def create_note(subtopic_id: str, payload: NoteCreate):
    conn = get_connection()
    try:
        auth_check = _auth_subtopic(conn, subtopic_id=subtopic_id, user_id=payload.user_id)
        if not auth_check:
            raise HTTPException(status_code=404, detail="Subtopic not found")

        note_id = new_id()
        now = utc_now_iso()
        conn.execute(
            """
            insert into notes (id, subtopic_id, parent_note_id, title, body_md, source_url, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note_id,
                subtopic_id,
                payload.parent_note_id,
                payload.title,
                payload.body_md,
                payload.source_url,
                now,
                now,
            ),
        )
        conn.commit()

        row = conn.execute(
            """
            select id, subtopic_id, parent_note_id, title, body_md, source_url, created_at, updated_at
            from notes
            where id = ?
            """,
            (note_id,),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


@router.get("/subtopics/{subtopic_id}/questions")
def list_questions(subtopic_id: str, user_id: str):
    conn = get_connection()
    try:
        auth_check = _auth_subtopic(conn, subtopic_id=subtopic_id, user_id=user_id)
        if not auth_check:
            raise HTTPException(status_code=404, detail="Subtopic not found")

        rows = conn.execute(
            """
            select id, subtopic_id, prompt, difficulty, format, intent, expected_seconds, weight,
                   options_json, correct_answer, created_by, created_at
            from questions
            where subtopic_id = ?
            order by created_at asc
            """,
            (subtopic_id,),
        ).fetchall()
        return [_serialize_question_row(row, include_answers=True) for row in rows]
    finally:
        conn.close()


@router.post("/subtopics/{subtopic_id}/questions")
def create_question(subtopic_id: str, payload: QuestionCreate):
    conn = get_connection()
    try:
        auth_check = _auth_subtopic(conn, subtopic_id=subtopic_id, user_id=payload.user_id)
        if not auth_check:
            raise HTTPException(status_code=404, detail="Subtopic not found")

        prepared = _prepare_question_payload(payload)

        question_id = new_id()
        now = utc_now_iso()
        conn.execute(
            """
            insert into questions (
              id, subtopic_id, prompt, difficulty, format, intent, expected_seconds,
              weight, options_json, correct_answer, created_by, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question_id,
                subtopic_id,
                prepared["prompt"],
                prepared["difficulty"],
                prepared["format"],
                prepared["intent"],
                prepared["expected_seconds"],
                prepared["weight"],
                json.dumps(prepared["options"]),
                prepared["correct_answer"],
                "user",
                now,
            ),
        )
        conn.commit()

        row = conn.execute(
            """
            select id, subtopic_id, prompt, difficulty, format, intent, expected_seconds, weight,
                   options_json, correct_answer, created_by, created_at
            from questions
            where id = ?
            """,
            (question_id,),
        ).fetchone()
        return _serialize_question_row(row, include_answers=True)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/subtopics/{subtopic_id}/questions/generate")
def generate_questions(subtopic_id: str, payload: QuestionGenerateRequest):
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is required for AI question generation")

    conn = get_connection()
    try:
        subtopic = _auth_subtopic(conn, subtopic_id=subtopic_id, user_id=payload.user_id)
        if not subtopic:
            raise HTTPException(status_code=404, detail="Subtopic not found")

        ai_questions = generate_questions_with_ai(
            topic_title=subtopic["main_topic_title"],
            subtopic_title=subtopic["title"],
            subtopic_description=subtopic["description"],
            count=payload.count,
        )
        if not ai_questions:
            raise HTTPException(
                status_code=502,
                detail="OpenAI did not return valid questions. Please retry question generation.",
            )

        now = utc_now_iso()
        inserted = []
        for raw_question in ai_questions[: payload.count]:
            question = _coerce_generated_question(raw_question)
            if not question:
                continue
            expected_seconds = estimate_expected_seconds(
                difficulty=question["difficulty"],
                format_type=question["format"],
                intent=question["intent"],
            )

            question_id = new_id()
            conn.execute(
                """
                insert into questions (
                  id, subtopic_id, prompt, difficulty, format, intent, expected_seconds,
                  weight, options_json, correct_answer, created_by, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question_id,
                    subtopic_id,
                    question["prompt"],
                    question["difficulty"],
                    question["format"],
                    question["intent"],
                    expected_seconds,
                    difficulty_weight(question["difficulty"]),
                    json.dumps(question["options"]),
                    question["correct_answer"],
                    "ai",
                    now,
                ),
            )

            inserted.append(
                {
                    "id": question_id,
                    "subtopic_id": subtopic_id,
                    "prompt": question["prompt"],
                    "difficulty": question["difficulty"],
                    "format": question["format"],
                    "intent": question["intent"],
                    "expected_seconds": expected_seconds,
                    "weight": difficulty_weight(question["difficulty"]),
                    "options": question["options"] if question["format"] == "mcq" else [],
                    "correct_answer": question["correct_answer"],
                    "created_by": "ai",
                    "created_at": now,
                }
            )

        if not inserted:
            raise HTTPException(
                status_code=502,
                detail="OpenAI response did not include usable questions. Please retry.",
            )

        conn.commit()

        return {
            "generated_by": "openai",
            "questions": inserted,
        }
    finally:
        conn.close()
