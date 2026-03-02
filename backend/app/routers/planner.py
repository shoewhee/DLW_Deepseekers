from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..db import get_connection, new_id, utc_now_iso
from ..schemas import ImprovementModelUpsert, PlannerRequest, PlannerResponse
from ..services.openai_helper import generate_study_plan_with_ai
from ..services.planner import build_study_plan

router = APIRouter(prefix="/planner", tags=["planner"])


@router.post("/improvement-model")
def upsert_improvement_model(payload: ImprovementModelUpsert):
    conn = get_connection()
    try:
        now = utc_now_iso()
        row = conn.execute(
            """
            select id
            from subtopic_improvement_models
            where user_id = ? and subtopic_id = ?
            limit 1
            """,
            (payload.user_id, payload.subtopic_id),
        ).fetchone()

        if row:
            conn.execute(
                """
                update subtopic_improvement_models
                set estimated_gain_per_hour = ?, source = ?, updated_at = ?
                where id = ?
                """,
                (payload.estimated_gain_per_hour, payload.source, now, row["id"]),
            )
            conn.commit()
            updated = conn.execute(
                """
                select id, user_id, subtopic_id, estimated_gain_per_hour, source, last_practiced_at, created_at, updated_at
                from subtopic_improvement_models
                where id = ?
                """,
                (row["id"],),
            ).fetchone()
            return dict(updated)

        created_id = new_id()
        conn.execute(
            """
            insert into subtopic_improvement_models (
              id, user_id, subtopic_id, estimated_gain_per_hour, source, last_practiced_at, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_id,
                payload.user_id,
                payload.subtopic_id,
                payload.estimated_gain_per_hour,
                payload.source,
                None,
                now,
                now,
            ),
        )
        conn.commit()

        created = conn.execute(
            """
            select id, user_id, subtopic_id, estimated_gain_per_hour, source, last_practiced_at, created_at, updated_at
            from subtopic_improvement_models
            where id = ?
            """,
            (created_id,),
        ).fetchone()
        return dict(created)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/generate", response_model=PlannerResponse)
def generate_plan(payload: PlannerRequest):
    conn = get_connection()
    try:
        now = utc_now_iso()
        today = datetime.now(timezone.utc).date()
        days_until_exam = max((payload.exam_date - today).days, 0)

        profile_row = conn.execute(
            "select id from study_planning_profiles where user_id = ? limit 1",
            (payload.user_id,),
        ).fetchone()

        if profile_row:
            conn.execute(
                """
                update study_planning_profiles
                set exam_date = ?, updated_at = ?
                where id = ?
                """,
                (
                    payload.exam_date.isoformat(),
                    now,
                    profile_row["id"],
                ),
            )
        else:
            conn.execute(
                """
                insert into study_planning_profiles (
                  id, user_id, exam_date, hours_available_total, study_style, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    payload.user_id,
                    payload.exam_date.isoformat(),
                    None,
                    None,
                    now,
                    now,
                ),
            )

        topic_rows = conn.execute(
            """
            select id, title, importance
            from main_topics
            where user_id = ?
            """,
            (payload.user_id,),
        ).fetchall()
        topics = [dict(row) for row in topic_rows]
        if not topics:
            raise HTTPException(status_code=400, detail="No topics found. Create topics first.")

        topic_lookup = {row["id"]: row for row in topics}
        placeholders = ",".join("?" for _ in topic_lookup)

        subtopic_rows = conn.execute(
            f"""
            select id, title, main_topic_id, exam_weight
            from subtopics
            where main_topic_id in ({placeholders})
            """,
            list(topic_lookup.keys()),
        ).fetchall()
        all_subtopics = [dict(row) for row in subtopic_rows]
        if not all_subtopics:
            raise HTTPException(status_code=400, detail="No subtopics found. Create subtopics first.")

        requested_ids = set(payload.subtopic_ids or [])
        if requested_ids:
            selected_subtopics = [row for row in all_subtopics if row["id"] in requested_ids]
            if len(selected_subtopics) != len(requested_ids):
                raise HTTPException(status_code=400, detail="Some selected subtopics are invalid")
        else:
            selected_subtopics = all_subtopics

        for row in selected_subtopics:
            row["main_topic"] = topic_lookup.get(row["main_topic_id"], {})

        subtopic_ids = [row["id"] for row in selected_subtopics]
        subtopic_placeholders = ",".join("?" for _ in subtopic_ids)

        latest_rows = conn.execute(
            f"""
            select sms.subtopic_id, sms.adjusted_mastery, sms.confidence_score
            from subtopic_mastery_snapshots sms
            join (
              select subtopic_id, max(snapshot_at) as latest_snapshot_at
              from subtopic_mastery_snapshots
              where user_id = ? and subtopic_id in ({subtopic_placeholders})
              group by subtopic_id
            ) latest
            on latest.subtopic_id = sms.subtopic_id and latest.latest_snapshot_at = sms.snapshot_at
            where sms.user_id = ?
            """,
            [payload.user_id, *subtopic_ids, payload.user_id],
        ).fetchall()
        latest_mastery = {
            row["subtopic_id"]: {
                "adjusted_mastery": float(row["adjusted_mastery"]) if row["adjusted_mastery"] is not None else 0.5,
                "confidence_score": float(row["confidence_score"]) if row["confidence_score"] is not None else 0.0,
            }
            for row in latest_rows
        }

        improvement_rows = conn.execute(
            """
            select id, subtopic_id, estimated_gain_per_hour, last_practiced_at, source
            from subtopic_improvement_models
            where user_id = ?
            """,
            (payload.user_id,),
        ).fetchall()
        improvement_lookup = {row["subtopic_id"]: dict(row) for row in improvement_rows}

        for subtopic in selected_subtopics:
            if subtopic["id"] in improvement_lookup:
                continue
            model_id = new_id()
            default_model = {
                "id": model_id,
                "subtopic_id": subtopic["id"],
                "estimated_gain_per_hour": 0.08,
                "last_practiced_at": None,
                "source": "global_default",
            }
            conn.execute(
                """
                insert into subtopic_improvement_models (
                  id, user_id, subtopic_id, estimated_gain_per_hour, source, last_practiced_at, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    payload.user_id,
                    subtopic["id"],
                    0.08,
                    "global_default",
                    None,
                    now,
                    now,
                ),
            )
            improvement_lookup[subtopic["id"]] = default_model

        conn.commit()

        ai_input_subtopics = []
        for row in selected_subtopics:
            mastery_info = latest_mastery.get(row["id"], {"adjusted_mastery": 0.5, "confidence_score": 0.0})
            ai_input_subtopics.append(
                {
                    "subtopic_id": row["id"],
                    "main_topic": row.get("main_topic", {}).get("title", "Topic"),
                    "subtopic": row["title"],
                    "importance": row.get("main_topic", {}).get("importance", "medium"),
                    "exam_weight": row.get("exam_weight", 1.0),
                    "current_mastery": round(float(mastery_info.get("adjusted_mastery", 0.5)), 4),
                    "confidence": round(float(mastery_info.get("confidence_score", 0.0)), 4),
                }
            )

        ai_plan = generate_study_plan_with_ai(
            exam_date=payload.exam_date.isoformat(),
            days_until_exam=days_until_exam,
            selected_subtopics=ai_input_subtopics,
        )

        if ai_plan:
            sanitized_recommendations = []
            valid_subtopic_ids = {row["id"] for row in selected_subtopics}
            for idx, row in enumerate(ai_plan.get("recommendations", []), start=1):
                if not isinstance(row, dict):
                    continue
                subtopic_id = str(row.get("subtopic_id", "")).strip()
                if subtopic_id and subtopic_id not in valid_subtopic_ids:
                    continue
                tasks = row.get("tasks")
                if not isinstance(tasks, list):
                    tasks = []
                sanitized_recommendations.append(
                    {
                        "day": int(row.get("day", idx)),
                        "subtopic_id": subtopic_id,
                        "main_topic": str(row.get("main_topic", "Topic")),
                        "subtopic": str(row.get("subtopic", "Study focus")),
                        "tasks": [str(task) for task in tasks if str(task).strip()],
                        "reason": str(row.get("reason", "High expected impact before the exam.")),
                    }
                )

            return PlannerResponse(
                exam_date=payload.exam_date,
                days_until_exam=days_until_exam,
                generated_by="openai",
                summary=ai_plan.get("summary", "AI-generated study plan."),
                recommendations=sanitized_recommendations,
            )

        hours_for_fallback = max(4, min(50, max(days_until_exam, 1) * 2))
        heuristic = build_study_plan(
            exam_date=payload.exam_date,
            hours_available_total=hours_for_fallback,
            subtopic_rows=selected_subtopics,
            latest_mastery_by_subtopic={
                key: value["adjusted_mastery"] if isinstance(value, dict) else float(value)
                for key, value in latest_mastery.items()
            },
            improvement_models_by_subtopic=improvement_lookup,
            now=datetime.now(timezone.utc),
        )

        summary = (
            f"Heuristic plan generated for {len(selected_subtopics)} subtopics across "
            f"approximately {hours_for_fallback} study hours before {payload.exam_date.isoformat()}."
        )

        return PlannerResponse(
            exam_date=payload.exam_date,
            days_until_exam=days_until_exam,
            generated_by="heuristic",
            summary=summary,
            recommendations=heuristic.get("recommendations", []),
        )
    finally:
        conn.close()
