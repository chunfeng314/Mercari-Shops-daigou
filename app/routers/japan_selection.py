from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
import sqlite3

from app.db import get_db
from app.schemas import JapanCandidateCreate
from app.site_catalog import JAPAN_SITE_IDS, JAPAN_SITES
from app.audit import record_event


router = APIRouter(prefix="/api/japan", tags=["日本网站选品"])


@router.get("/sites")
def list_japan_sites() -> list[dict]:
    return JAPAN_SITES


@router.post("/candidates", status_code=201)
def create_candidate(
    payload: JapanCandidateCreate,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    if payload.japan_site not in JAPAN_SITE_IDS:
        raise HTTPException(status_code=422, detail="未知的日本选品站点")

    candidate_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """INSERT INTO items
        (id, japan_site, japan_url, japan_title, japan_price_jpy,
         japan_image_url, note, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)""",
        (
            candidate_id,
            payload.japan_site,
            payload.japan_url,
            payload.japan_title,
            payload.japan_price_jpy,
            payload.japan_image_url,
            payload.note,
            created_at,
        ),
    )
    record_event(connection, "item", candidate_id, "candidate_created")
    connection.commit()
    return dict(connection.execute("SELECT * FROM items WHERE id = ?", (candidate_id,)).fetchone())


@router.get("/candidates")
def list_candidates(
    connection: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    rows = connection.execute("SELECT * FROM items WHERE archived_at IS NULL ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]
