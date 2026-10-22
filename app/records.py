import json
import sqlite3


def listing_draft_record(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    record = dict(row)
    for field in ("image_refs", "image_asset_ids", "inventory_variants"):
        record[field] = json.loads(record[field] or "[]")
    record["category_attributes"] = json.loads(record.get("category_attributes") or "{}")
    return record
