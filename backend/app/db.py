from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from .config import get_settings
from .services.security import hash_password

DEMO_USER_ID = "local-demo-user"
DEMO_USER_EMAIL = "demo@study-helper.local"
DEMO_USER_PASSWORD = "local-demo-password"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _resolve_demo_email(conn: sqlite3.Connection) -> str:
    email = DEMO_USER_EMAIL
    counter = 0

    while True:
        existing = conn.execute(
            "select id from users where lower(email) = lower(?)",
            (email,),
        ).fetchone()
        if not existing:
            return email
        counter += 1
        email = f"demo+{counter}@study-helper.local"


def ensure_local_demo_user(conn: sqlite3.Connection) -> None:
    existing = conn.execute("select id from users where id = ?", (DEMO_USER_ID,)).fetchone()
    if existing:
        return

    now = utc_now_iso()
    email = _resolve_demo_email(conn)
    conn.execute(
        """
        insert into users (id, email, password_hash, created_at, updated_at)
        values (?, ?, ?, ?, ?)
        """,
        (DEMO_USER_ID, email, hash_password(DEMO_USER_PASSWORD), now, now),
    )


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"pragma table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(f"alter table {table_name} add column {column_name} {definition}")


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(
            """
            create table if not exists users (
              id text primary key,
              email text not null unique,
              password_hash text not null,
              created_at text not null,
              updated_at text not null
            );

            create table if not exists main_topics (
              id text primary key,
              user_id text not null references users(id) on delete cascade,
              title text not null,
              description text,
              importance text not null default 'medium' check (importance in ('low', 'medium', 'high')),
              created_at text not null,
              updated_at text not null,
              unique (user_id, title)
            );

            create table if not exists subtopics (
              id text primary key,
              main_topic_id text not null references main_topics(id) on delete cascade,
              title text not null,
              description text,
              exam_weight real not null default 1.0,
              created_at text not null,
              updated_at text not null,
              unique (main_topic_id, title)
            );

            create index if not exists idx_subtopics_main_topic_id on subtopics(main_topic_id);

            create table if not exists notes (
              id text primary key,
              subtopic_id text not null references subtopics(id) on delete cascade,
              parent_note_id text references notes(id) on delete cascade,
              title text not null,
              body_md text not null,
              source_url text,
              created_at text not null,
              updated_at text not null
            );

            create index if not exists idx_notes_subtopic_id on notes(subtopic_id);

            create table if not exists questions (
              id text primary key,
              subtopic_id text not null references subtopics(id) on delete cascade,
              prompt text not null,
              difficulty text not null check (difficulty in ('basic', 'intermediate', 'advanced')),
              format text not null check (format in ('mcq', 'open_ended')),
              intent text not null check (intent in ('concept', 'application')),
              expected_seconds integer,
              weight real not null,
              options_json text,
              correct_answer text,
              created_by text not null default 'system',
              created_at text not null
            );

            create index if not exists idx_questions_subtopic_id on questions(subtopic_id);

            create table if not exists quiz_sessions (
              id text primary key,
              user_id text not null references users(id) on delete cascade,
              main_topic_id text references main_topics(id) on delete set null,
              session_type text not null default 'quiz' check (session_type in ('quiz', 'study', 'review')),
              started_at text not null,
              ended_at text,
              exam_date text,
              hours_left_to_exam real,
              created_at text not null
            );

            create index if not exists idx_quiz_sessions_user_id on quiz_sessions(user_id, started_at);

            create table if not exists quiz_session_questions (
              id text primary key,
              session_id text not null references quiz_sessions(id) on delete cascade,
              question_id text not null references questions(id) on delete restrict,
              position integer not null,
              max_attempts integer not null,
              allocated_seconds integer,
              unique (session_id, position),
              unique (session_id, question_id)
            );

            create index if not exists idx_qsq_session_id on quiz_session_questions(session_id);

            create table if not exists question_attempts (
              id text primary key,
              session_question_id text not null references quiz_session_questions(id) on delete cascade,
              attempt_no integer not null,
              submitted_answer text,
              is_correct integer not null check (is_correct in (0, 1)),
              rubric_score real check (rubric_score between 0 and 1),
              answered_at text not null,
              response_seconds integer not null,
              ai_feedback text,
              unique (session_question_id, attempt_no)
            );

            create index if not exists idx_attempts_session_question_id on question_attempts(session_question_id);

            create table if not exists subtopic_mastery_snapshots (
              id text primary key,
              user_id text not null references users(id) on delete cascade,
              subtopic_id text not null references subtopics(id) on delete cascade,
              snapshot_at text not null,
              attempts_sample_size integer not null,
              weighted_accuracy real not null,
              speed_score real not null,
              mastery_score real not null,
              confidence_score real not null,
              confidence_band text not null,
              decay_factor real not null,
              adjusted_mastery real not null
            );

            create index if not exists idx_mastery_user_subtopic_time
              on subtopic_mastery_snapshots(user_id, subtopic_id, snapshot_at);

            create table if not exists attempt_analysis (
              id text primary key,
              question_attempt_id text not null unique references question_attempts(id) on delete cascade,
              speed_bucket text not null check (speed_bucket in ('fast', 'slow')),
              tries_to_correct integer not null,
              analysis_label text not null,
              created_at text not null
            );

            create table if not exists study_activity_events (
              id text primary key,
              user_id text not null references users(id) on delete cascade,
              subtopic_id text references subtopics(id) on delete set null,
              session_id text references quiz_sessions(id) on delete set null,
              event_type text not null,
              event_payload text not null,
              occurred_at text not null
            );

            create index if not exists idx_activity_user_time on study_activity_events(user_id, occurred_at);

            create table if not exists study_planning_profiles (
              id text primary key,
              user_id text not null unique references users(id) on delete cascade,
              exam_date text,
              hours_available_total real,
              study_style text,
              created_at text not null,
              updated_at text not null
            );

            create table if not exists subtopic_improvement_models (
              id text primary key,
              user_id text not null references users(id) on delete cascade,
              subtopic_id text not null references subtopics(id) on delete cascade,
              estimated_gain_per_hour real not null,
              source text not null,
              last_practiced_at text,
              created_at text not null,
              updated_at text not null,
              unique (user_id, subtopic_id)
            );

            create index if not exists idx_improvement_user_subtopic
              on subtopic_improvement_models(user_id, subtopic_id);
            """
        )
        _ensure_column(conn, "questions", "options_json", "text")
        _ensure_column(conn, "questions", "correct_answer", "text")
        ensure_local_demo_user(conn)
        conn.commit()
    finally:
        conn.close()
