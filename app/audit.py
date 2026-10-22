from datetime import datetime, timezone
import json
import sqlite3
import uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_event(connection: sqlite3.Connection, entity_type: str, entity_id: str,
                 action: str, details: dict | None = None) -> None:
    connection.execute(
        "INSERT INTO audit_events (id,entity_type,entity_id,action,details,created_at) VALUES (?,?,?,?,?,?)",
        (uuid.uuid4().hex, entity_type, entity_id, action, json.dumps(details or {}, ensure_ascii=False), now_iso()),
    )


def entity_events(connection: sqlite3.Connection, entity_type: str, entity_id: str) -> list[dict]:
    rows = connection.execute(
        "SELECT * FROM audit_events WHERE entity_type=? AND entity_id=? ORDER BY created_at DESC",
        (entity_type, entity_id),
    ).fetchall()
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]
