import sqlite3
import json
import re
from collections.abc import Generator
from pathlib import Path

from app.config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    japan_site TEXT NOT NULL,
    japan_url TEXT NOT NULL,
    japan_title TEXT NOT NULL,
    japan_price_jpy INTEGER,
    japan_image_url TEXT,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS china_sources (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    china_site TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_title TEXT NOT NULL DEFAULT '',
    price_cny REAL,
    account_note TEXT NOT NULL DEFAULT '',
    match_status TEXT NOT NULL DEFAULT 'pending',
    match_note TEXT NOT NULL DEFAULT '',
    availability_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK(availability_status IN ('available','unavailable','unknown')),
    availability_commitment INTEGER NOT NULL DEFAULT 0,
    committed_quantity INTEGER NOT NULL DEFAULT 0,
    commitment_valid_until TEXT,
    availability_checked_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listing_drafts (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL UNIQUE REFERENCES items(id) ON DELETE CASCADE,
    china_source_id TEXT NOT NULL REFERENCES china_sources(id),
    estimated_source_price_cny REAL NOT NULL,
    source_checked_at TEXT NOT NULL,
    title_ja TEXT NOT NULL,
    description_ja TEXT NOT NULL DEFAULT '',
    image_refs TEXT NOT NULL DEFAULT '[]',
    image_asset_ids TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL,
    category_attributes TEXT NOT NULL DEFAULT '{}',
    brand TEXT NOT NULL DEFAULT '',
    condition TEXT NOT NULL,
    reservation_sale INTEGER NOT NULL DEFAULT 0,
    multi_variant INTEGER NOT NULL DEFAULT 0,
    inventory_quantity INTEGER NOT NULL DEFAULT 1,
    max_quantity_per_order INTEGER,
    inventory_variants TEXT NOT NULL DEFAULT '[]',
    reservation_release_date TEXT NOT NULL,
    reservation_start_date TEXT NOT NULL,
    reservation_end_date TEXT NOT NULL,
    reservation_cancel_deadline TEXT NOT NULL,
    reservation_delivery_timing TEXT NOT NULL,
    jan_code TEXT NOT NULL DEFAULT '',
    management_code TEXT NOT NULL DEFAULT '',
    shipping_method TEXT NOT NULL,
    shipping_payer TEXT NOT NULL,
    shipping_origin TEXT NOT NULL,
    handling_days TEXT NOT NULL,
    estimated_china_to_japan_shipping_cny REAL,
    price_jpy INTEGER NOT NULL,
    exchange_rate_cny_per_jpy REAL,
    mercari_fee_rate REAL NOT NULL,
    shipping_jpy INTEGER,
    other_costs_jpy INTEGER,
    estimated_profit_cny REAL,
    estimated_margin_pct REAL,
    status TEXT NOT NULL DEFAULT 'draft',
    listing_url TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS listing_defaults (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    shipping_method TEXT NOT NULL,
    shipping_payer TEXT NOT NULL,
    shipping_origin TEXT NOT NULL,
    handling_days TEXT NOT NULL,
    mercari_fee_rate REAL NOT NULL CHECK (mercari_fee_rate >= 0 AND mercari_fee_rate < 1)
);

CREATE TABLE IF NOT EXISTS listing_preparations (
    item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES china_sources(id),
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('needs_review','ready_for_review')),
    generated_data TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    generation_method TEXT NOT NULL DEFAULT 'rule_based'
);

CREATE TABLE IF NOT EXISTS shop_browser_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    browser_mode TEXT NOT NULL CHECK(browser_mode IN ('managed','temporary','existing_chrome')),
    browser_channel TEXT NOT NULL CHECK(browser_channel IN ('chrome','msedge')),
    url TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sales_orders (
    id TEXT PRIMARY KEY,
    mercari_order_id TEXT NOT NULL,
    item_id TEXT NOT NULL REFERENCES items(id),
    listing_draft_id TEXT NOT NULL REFERENCES listing_drafts(id),
    china_source_id TEXT NOT NULL REFERENCES china_sources(id),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    sold_price_jpy INTEGER NOT NULL,
    actual_purchase_price_cny REAL,
    actual_china_to_japan_shipping_cny REAL NOT NULL DEFAULT 0,
    fulfillment_status TEXT NOT NULL DEFAULT 'awaiting_purchase'
        CHECK(fulfillment_status IN ('awaiting_purchase','purchased')),
    inbound_status TEXT NOT NULL DEFAULT 'awaiting_dispatch',
    china_carrier TEXT,
    china_tracking_number TEXT,
    china_shipped_at TEXT,
    received_at_japan TEXT,
    inspection_result TEXT NOT NULL DEFAULT 'pending',
    inspection_note TEXT NOT NULL DEFAULT '',
    domestic_status TEXT NOT NULL DEFAULT 'not_shipped',
    japan_carrier TEXT,
    japan_tracking_number TEXT,
    shipped_to_buyer_at TEXT,
    delivered_at TEXT,
    created_at TEXT NOT NULL,
    purchased_at TEXT,
    UNIQUE(mercari_order_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_sources_item_id ON china_sources(item_id);
CREATE TABLE IF NOT EXISTS source_images (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES china_sources(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    source_path TEXT NOT NULL,
    listing_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    listing_content_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    image_role TEXT NOT NULL DEFAULT 'other'
        CHECK(image_role IN ('real_photo','catalog','screenshot','other')),
    source_page_url TEXT NOT NULL,
    source_asset_url TEXT NOT NULL DEFAULT '',
    collection_note TEXT NOT NULL DEFAULT '',
    vision_review_json TEXT NOT NULL DEFAULT '{}',
    vision_review_at TEXT,
    vision_review_model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_images_source_id ON source_images(source_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sales_orders_item_id ON sales_orders(item_id, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type, entity_id, created_at);
CREATE TABLE IF NOT EXISTS order_refunds (
    id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES sales_orders(id),
    refund_reference TEXT NOT NULL UNIQUE, amount_jpy INTEGER NOT NULL CHECK(amount_jpy > 0),
    reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS automation_jobs (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued', progress TEXT NOT NULL DEFAULT '',
    result TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, watch_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON automation_jobs(status,created_at);
CREATE TABLE IF NOT EXISTS watches (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, site_id TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
    interval_minutes INTEGER NOT NULL DEFAULT 360, result_limit INTEGER NOT NULL DEFAULT 20,
    enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
    next_run_at TEXT NOT NULL, last_job_id TEXT, last_run_at TEXT
);
CREATE TABLE IF NOT EXISTS watch_items (
    watch_id TEXT NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    url TEXT NOT NULL, title TEXT NOT NULL, price REAL, image_url TEXT,
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    PRIMARY KEY(watch_id,url)
);
CREATE TABLE IF NOT EXISTS watch_changes (
    id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id),
    job_id TEXT NOT NULL REFERENCES automation_jobs(id), url TEXT NOT NULL,
    change_type TEXT NOT NULL, previous_price REAL, current_price REAL,
    title TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shop_order_imports (
    id TEXT PRIMARY KEY, external_order_id TEXT NOT NULL, external_product_url TEXT NOT NULL,
    title TEXT NOT NULL, quantity INTEGER NOT NULL, amount_jpy INTEGER,
    raw_data TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'unmatched',
    local_order_id TEXT REFERENCES sales_orders(id), created_at TEXT NOT NULL,
    UNIQUE(external_order_id, external_product_url)
);
"""


MIGRATIONS = {
    "watches": {"archived_at": "TEXT"},
    "items": {"archived_at": "TEXT"},
    "china_sources": {
        "archived_at": "TEXT",
        "availability_commitment": "INTEGER NOT NULL DEFAULT 0",
        "committed_quantity": "INTEGER NOT NULL DEFAULT 0",
        "commitment_valid_until": "TEXT",
    },
    "source_images": {
        "collection_note": "TEXT NOT NULL DEFAULT ''", "excluded_at": "TEXT", "exclusion_reason": "TEXT NOT NULL DEFAULT ''",
        "vision_review_json": "TEXT NOT NULL DEFAULT '{}'", "vision_review_at": "TEXT", "vision_review_model": "TEXT NOT NULL DEFAULT ''",
    },
    "listing_drafts": {
        "image_asset_ids": "TEXT NOT NULL DEFAULT '[]'",
        "category_attributes": "TEXT NOT NULL DEFAULT '{}'",
        "reservation_release_date": "TEXT NOT NULL DEFAULT ''",
        "reservation_start_date": "TEXT NOT NULL DEFAULT ''",
        "reservation_end_date": "TEXT NOT NULL DEFAULT ''",
        "reservation_cancel_deadline": "TEXT NOT NULL DEFAULT ''",
        "reservation_delivery_timing": "TEXT NOT NULL DEFAULT 'after_release'",
        "estimated_china_to_japan_shipping_cny": "REAL NOT NULL DEFAULT 0",
    },
    "sales_orders": {
        "order_status": "TEXT NOT NULL DEFAULT 'active'",
        "cancel_reason": "TEXT NOT NULL DEFAULT ''",
        "cancelled_at": "TEXT",
        "inventory_released": "INTEGER NOT NULL DEFAULT 0",
        "return_received_at": "TEXT",
        "return_note": "TEXT NOT NULL DEFAULT ''",
        "actual_china_to_japan_shipping_cny": "REAL NOT NULL DEFAULT 0",
        "inbound_status": "TEXT NOT NULL DEFAULT 'awaiting_dispatch'",
        "china_carrier": "TEXT",
        "china_tracking_number": "TEXT",
        "china_shipped_at": "TEXT",
        "received_at_japan": "TEXT",
        "inspection_result": "TEXT NOT NULL DEFAULT 'pending'",
        "inspection_note": "TEXT NOT NULL DEFAULT ''",
        "domestic_status": "TEXT NOT NULL DEFAULT 'not_shipped'",
        "japan_carrier": "TEXT",
        "japan_tracking_number": "TEXT",
        "shipped_to_buyer_at": "TEXT",
        "delivered_at": "TEXT",
    },
}


def connect_db() -> sqlite3.Connection:
    db_path: Path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may create a sync dependency in its worker pool and then pass it
    # to an async endpoint (for example, the multipart image upload route).
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def init_db() -> None:
    connection = connect_db()
    try:
        connection.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing_columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, definition in columns.items():
                if column not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    )
        connection.execute(
            """INSERT OR IGNORE INTO listing_defaults
            (id, shipping_method, shipping_payer, shipping_origin, handling_days, mercari_fee_rate)
            VALUES (1, ?, ?, ?, ?, ?)""",
            ("らくらくメルカリ便", "送料込み（出品者負担）", "東京都", "4〜7日で発送", 0.1),
        )
        _allow_managed_browser(connection)
        profile_path = settings.database_path.parent / "shop-profile.json"
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            profile = {}
        connection.execute(
            "INSERT OR IGNORE INTO shop_browser_settings VALUES (1, ?, 'chrome', ?)",
            ("managed", profile.get("management_url", "")),
        )
        connection.commit()
        _allow_pending_profit(connection)
    finally:
        connection.close()


def _allow_managed_browser(connection: sqlite3.Connection) -> None:
    sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='shop_browser_settings'").fetchone()[0]
    if "'managed'" in sql:
        return
    connection.execute("SAVEPOINT managed_browser_settings")
    try:
        connection.execute("""CREATE TABLE shop_browser_settings_new (
            id INTEGER PRIMARY KEY CHECK(id=1),
            browser_mode TEXT NOT NULL CHECK(browser_mode IN ('managed','temporary','existing_chrome')),
            browser_channel TEXT NOT NULL CHECK(browser_channel IN ('chrome','msedge')),
            url TEXT NOT NULL DEFAULT '')""")
        connection.execute("INSERT INTO shop_browser_settings_new SELECT * FROM shop_browser_settings")
        connection.execute("DROP TABLE shop_browser_settings")
        connection.execute("ALTER TABLE shop_browser_settings_new RENAME TO shop_browser_settings")
        connection.execute("RELEASE SAVEPOINT managed_browser_settings")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT managed_browser_settings")
        connection.execute("RELEASE SAVEPOINT managed_browser_settings")
        raise


def _allow_pending_profit(connection: sqlite3.Connection) -> None:
    """Keep historical estimates, while allowing platform drafts without cost estimates."""
    columns = connection.execute("PRAGMA table_info(listing_drafts)").fetchall()
    optional = {
        "estimated_china_to_japan_shipping_cny", "exchange_rate_cny_per_jpy",
        "shipping_jpy", "other_costs_jpy", "estimated_profit_cny", "estimated_margin_pct",
    }
    if not any(row["name"] in optional and row["notnull"] for row in columns):
        return
    sql = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='listing_drafts'").fetchone()[0]
    sql = sql.replace("CREATE TABLE listing_drafts", "CREATE TABLE listing_drafts_new", 1)
    for name in optional:
        sql = re.sub(rf"(?m)(\b{re.escape(name)}\s+(?:REAL|INTEGER))\s+NOT NULL(?:\s+DEFAULT\s+0)?", r"\1", sql)
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(sql)
        names = ",".join(row["name"] for row in columns)
        connection.execute(f"INSERT INTO listing_drafts_new ({names}) SELECT {names} FROM listing_drafts")
        connection.execute("DROP TABLE listing_drafts")
        connection.execute("ALTER TABLE listing_drafts_new RENAME TO listing_drafts")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("上架草稿迁移后的关联检查未通过")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def get_db() -> Generator[sqlite3.Connection, None, None]:
    connection = connect_db()
    try:
        yield connection
    finally:
        connection.close()
