from datetime import datetime, timedelta, timezone
import json
import sqlite3
import uuid

from app.audit import now_iso


TERMINAL = {"succeeded", "failed", "cancelled"}
WAITING = {"waiting_login", "waiting_review"}


def job_record(row) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    result["payload"] = json.loads(result["payload"])
    result["result"] = json.loads(result["result"]) if result["result"] else None
    return result


def enqueue(connection: sqlite3.Connection, kind: str, payload: dict, watch_id: str | None = None) -> dict:
    job_id = uuid.uuid4().hex
    connection.execute("INSERT INTO automation_jobs (id,kind,payload,created_at,watch_id) VALUES (?,?,?,?,?)",
                       (job_id, kind, json.dumps(payload, ensure_ascii=False), now_iso(), watch_id))
    return job_record(connection.execute("SELECT * FROM automation_jobs WHERE id=?", (job_id,)).fetchone())


def schedule_next(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def save_watch_observations(connection: sqlite3.Connection, watch_id: str, job_id: str, items: list[dict]) -> dict:
    counts = {"new": 0, "price_changed": 0}
    now = now_iso()
    for item in items:
        previous = connection.execute("SELECT * FROM watch_items WHERE watch_id=? AND url=?", (watch_id, item["url"])).fetchone()
        change = "new" if previous is None else "price_changed" if previous["price"] != item.get("price") else None
        if change:
            counts[change] += 1
            connection.execute("INSERT INTO watch_changes (id,watch_id,job_id,url,change_type,previous_price,current_price,title,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                               (uuid.uuid4().hex, watch_id, job_id, item["url"], change, previous["price"] if previous else None, item.get("price"), item["title"], now))
        connection.execute("INSERT INTO watch_items (watch_id,url,title,price,image_url,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(watch_id,url) DO UPDATE SET title=excluded.title,price=excluded.price,image_url=excluded.image_url,last_seen_at=excluded.last_seen_at",
                           (watch_id, item["url"], item["title"], item.get("price"), item.get("image_url"), now, now))
    return counts
