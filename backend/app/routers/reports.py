from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_connection

router = APIRouter(prefix="/reports", tags=["reports"])


def _latest_snapshots_for_user(conn, user_id: str) -> dict[str, dict]:
    rows = conn.execute(
        """
        select sms.*
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
    return {row["subtopic_id"]: dict(row) for row in rows}


@router.get("/overview")
def get_overview_report(user_id: str):
    conn = get_connection()
    try:
        topics = conn.execute(
            "select id, title from main_topics where user_id = ? order by title asc",
            (user_id,),
        ).fetchall()
        latest_map = _latest_snapshots_for_user(conn, user_id)

        overview = []
        for topic in topics:
            subtopics = conn.execute(
                "select id from subtopics where main_topic_id = ?",
                (topic["id"],),
            ).fetchall()

            values = [latest_map[row["id"]] for row in subtopics if row["id"] in latest_map]
            if not values:
                continue

            adjusted = [float(item["adjusted_mastery"]) for item in values]
            confidence = [float(item["confidence_score"]) for item in values]

            overview.append(
                {
                    "main_topic_id": topic["id"],
                    "main_topic_title": topic["title"],
                    "avg_adjusted_mastery": sum(adjusted) / len(adjusted),
                    "weakest_subtopic_score": min(adjusted),
                    "strongest_subtopic_score": max(adjusted),
                    "avg_confidence": sum(confidence) / len(confidence),
                }
            )

        overview.sort(key=lambda row: row["avg_adjusted_mastery"], reverse=True)
        return overview
    finally:
        conn.close()


@router.get("/topic/{main_topic_id}")
def get_topic_report(main_topic_id: str, user_id: str):
    conn = get_connection()
    try:
        topic = conn.execute(
            """
            select id, title
            from main_topics
            where id = ? and user_id = ?
            """,
            (main_topic_id, user_id),
        ).fetchone()
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        subtopics = conn.execute(
            "select id, title from subtopics where main_topic_id = ?",
            (main_topic_id,),
        ).fetchall()

        if not subtopics:
            return {
                "main_topic": dict(topic),
                "strengths": [],
                "weaknesses": [],
            }

        latest_map = _latest_snapshots_for_user(conn, user_id)
        ranked = []
        for subtopic in subtopics:
            snapshot = latest_map.get(subtopic["id"])
            if not snapshot:
                continue
            ranked.append(
                {
                    "subtopic_id": subtopic["id"],
                    "subtopic_title": subtopic["title"],
                    "mastery_score": snapshot["mastery_score"],
                    "confidence_score": snapshot["confidence_score"],
                    "confidence_band": snapshot["confidence_band"],
                    "adjusted_mastery": snapshot["adjusted_mastery"],
                }
            )

        ranked.sort(key=lambda row: float(row["adjusted_mastery"]))

        weaknesses = ranked[:3]
        strengths = list(reversed(ranked[-3:]))

        return {
            "main_topic": dict(topic),
            "strengths": strengths,
            "weaknesses": weaknesses,
        }
    finally:
        conn.close()
