from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from ..db import get_connection, new_id, utc_now_iso
from ..schemas import AuthLoginRequest, AuthResponse, AuthSignupRequest
from ..services.security import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse)
def signup(payload: AuthSignupRequest):
    conn = get_connection()
    try:
        existing = conn.execute(
            "select id from users where lower(email) = lower(?)",
            (payload.email.strip(),),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        user_id = new_id()
        now = utc_now_iso()

        conn.execute(
            """
            insert into users (id, email, password_hash, created_at, updated_at)
            values (?, ?, ?, ?, ?)
            """,
            (user_id, payload.email.strip(), hash_password(payload.password), now, now),
        )
        conn.commit()

        return AuthResponse(user_id=user_id, email=payload.email.strip())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthLoginRequest):
    conn = get_connection()
    try:
        row = conn.execute(
            "select id, email, password_hash from users where lower(email) = lower(?)",
            (payload.email.strip(),),
        ).fetchone()

        if not row or not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        return AuthResponse(user_id=row["id"], email=row["email"])
    finally:
        conn.close()
