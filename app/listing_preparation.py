"""Prepare platform fields from recorded evidence, without requiring profit inputs."""
import json
import hashlib
import re
import sqlite3

from app.audit import now_iso, record_event


PLATFORM_FIELDS = (
    ("image_asset_ids", "商品图片", "商品画像", "至少 1 张；工作台收图目标为 5 张且包含实物图"),
    ("title_ja", "日文商品名", "商品名", "最多 130 字符"),
    ("condition", "商品状态", "商品の状態", "选择平台的准确选项"),
    ("category", "商品分类", "カテゴリー", "选择完整分类路径"),
    ("inventory_quantity", "店铺库存", "数量", "普通销售的可售数量大于 0"),
    ("shipping_method", "配送方式", "配送方法", "店铺通用设置"),
    ("shipping_payer", "运费承担方", "配送料の負担", "店铺通用设置"),
    ("shipping_origin", "日本发货地区", "発送元の地域", "店铺通用设置"),
    ("handling_days", "发货时效", "発送までの日数", "店铺通用设置"),
    ("price_jpy", "销售价格", "販売価格", "300～9,999,999 日元"),
)


def listing_requirements() -> dict:
    return {
        "verified_on": "2026-10-18", "scope": "普通销售、单规格商品；根据实际店铺表单核对",
        "required": [dict(field=k, label=label, platform_label=ja, rule=rule) for k, label, ja, rule in PLATFORM_FIELDS],
        "optional": ["description_ja", "brand", "max_quantity_per_order", "jan_code", "management_code"],
        "conditional": {"reservation_sale": ["reservation_start_date", "reservation_end_date", "reservation_release_date", "reservation_cancel_deadline", "reservation_delivery_timing"], "multi_variant": ["inventory_variants"]},
        "category_dependent": {
            "discovery": "先在当前 Mercari Shops 分类树中选择准确末级分类，再检查该分类显示的商品专属字段。",
            "values": "category_attributes 只能使用日本商品页或已确认中国货源中的证据值。",
            "unresolved": "证据缺失时报告字段、必填状态和平台选项，不得猜测。",
        },
        "internal_only": ["exchange_rate_cny_per_jpy", "mercari_fee_rate", "estimated_china_to_japan_shipping_cny", "shipping_jpy", "other_costs_jpy"],
        "autosaves_on_edit": True,
        "publication": "正式发布由人在店铺完成；开始填写前需确认本地资料。",
    }


def prepare_listing(connection: sqlite3.Connection, item_id: str, source_id: str | None = None) -> dict:
    item = connection.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if item is None:
        raise ValueError("未找到商品")
    draft = connection.execute("SELECT * FROM listing_drafts WHERE item_id=?", (item_id,)).fetchone()
    if source_id is None and draft:
        source_id = draft["china_source_id"]
    if source_id:
        source = connection.execute("SELECT * FROM china_sources WHERE id=? AND item_id=? AND archived_at IS NULL", (source_id, item_id)).fetchone()
        if source is None:
            raise ValueError("货源不属于该商品或已归档")
    else:
        source = connection.execute("SELECT * FROM china_sources WHERE item_id=? AND archived_at IS NULL AND match_status='confirmed' ORDER BY created_at DESC LIMIT 1", (item_id,)).fetchone()
    defaults = dict(connection.execute("SELECT * FROM listing_defaults WHERE id=1").fetchone())
    defaults.pop("id", None)
    values = {
        **defaults, "title_ja": item["japan_title"][:130],
        "description_ja": "", "category": "", "brand": "", "condition": "",
        "category_attributes": {},
        "inventory_quantity": 1, "max_quantity_per_order": None,
        "price_jpy": item["japan_price_jpy"], "image_asset_ids": [], "image_refs": [],
        "reservation_sale": False, "multi_variant": False, "inventory_variants": [],
        "management_code": f"PRD-{item_id[:8].upper()}", "jan_code": "",
    }
    origins = {key: "店铺通用设置" for key in defaults}
    origins.update(title_ja="日本选品标题", price_jpy="日本参考价，仅作待确认的建议售价", inventory_quantity="本地草稿初始值，可逐件调整", management_code="按本地商品编号生成")
    notes = []
    if source:
        values["china_source_id"] = source["id"]
        if source["availability_status"] == "unknown":
            notes.append("中国货源库存尚未核实；草稿中的库存数量仅为本地测试占位，店铺填表前需确认实际供货数量。")
        elif source["availability_status"] == "unavailable":
            notes.append("中国货源当前标记为无货；请勿按草稿库存数量发布，需先找到可供货来源。")
        note = (source["account_note"] or "") + "\n" + (source["match_note"] or "")
        title = values["title_ja"]
        if re.search(r"サンリオ|三丽鸥|Sanrio", title, re.I) and re.search(r"カード|卡片", title):
            values["category"] = "ゲーム・おもちゃ・グッズ > キャラクターグッズ > カード・フォト・ブロマイド"
            origins["category"] = "按商品类型建议；分类路径已在店铺菜单核对，填写前确认"
        values["brand"] = "サンリオ" if re.search(r"サンリオ|三丽鸥|Sanrio", title, re.I) else "Starbucks" if re.search(r"スターバックス|Starbucks", title, re.I) else ""
        lines = [title, "", "【商品について】", title]
        quantity = re.search(r"(\d+)枚(?:セット)?", title)
        if quantity:
            lines.append(f"セット内容：カード{quantity[1]}枚。")
        lines.extend(["", "【状態について】"])
        if "厂瑕" in note or "厂暇" in note:
            lines.append("仕入先より、製造時の初期不良が含まれる場合があると案内されています。状態をご確認のうえご検討ください。")
            notes.append("货源注明默认厂瑕，商品成色需要核对后选择，未自动标为新品。")
        elif re.search(r"全新未用|全新未使用|新品、未使用", note):
            values["condition"] = "新品、未使用"
            origins["condition"] = "已记录的货源成色信息，填写前仍需核对"
            lines.append("仕入先の掲載情報では新品・未使用です。")
        else:
            lines.append("商品の状態は、仕入先の掲載情報と画像をご確認ください。")
        lines.extend(["", "【お届けについて】", "ご注文後に仕入先の在庫と仕様を確認して手配し、日本到着後に検品して発送します。"])
        values["description_ja"] = "\n".join(lines)[:3000]
        origins["description_ja"] = "选品标题、货源备注和已确认履约流程；规则模板生成，待核对"
    if draft and (not source or draft["china_source_id"] == source["id"]):
        values.update(dict(draft))
        for name in ("image_refs", "image_asset_ids", "inventory_variants"):
            values[name] = json.loads(values[name] or "[]")
        values["category_attributes"] = json.loads(values.get("category_attributes") or "{}")
        origins.update({key: "已保存的上架草稿" for key in values})
    images = connection.execute("SELECT id,sha256,image_role,source_page_url FROM source_images WHERE source_id=? AND excluded_at IS NULL", (source["id"],)).fetchall() if source else []
    unique = {image["sha256"] for image in images}
    real = {image["sha256"] for image in images if image["image_role"] == "real_photo"}
    invalid_images = set(values.get("image_asset_ids", [])) - {image["id"] for image in images}
    if invalid_images:
        notes.append("草稿引用的部分图片已排除，请重新选择商品图片。")
    if images and not values["image_asset_ids"]:
        notes.append("已收集的图片作为选图候选；请确认与本次销售组合一致后勾选，参考图不会自动成为上架图。")
    fields = []
    for key, label, ja, rule in PLATFORM_FIELDS:
        value = values.get(key)
        present = bool(value) if key != "image_asset_ids" else bool(value or values.get("image_refs"))
        if key == "image_asset_ids" and invalid_images:
            present = False
        if key == "price_jpy":
            present = value is not None and 300 <= value <= 9_999_999
        fields.append(dict(field=key, label=label, platform_label=ja, rule=rule, ready=present, origin=origins.get(key, "待整理 / 核对")))
    missing = [field["label"] for field in fields if not field["ready"]]
    return {
        "values": values, "fields": fields, "missing": missing,
        "ready_for_review": not missing, "notes": notes,
        "photo_collection": {"unique_count": len(unique), "real_photo_count": len(real), "target_met": len(unique) >= 5 and bool(real)},
        "requirements": listing_requirements(),
    }


def _fingerprint(
    connection: sqlite3.Connection,
    item_id: str,
    source_id: str,
    item_status: str | None = None,
) -> str:
    item = connection.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    source = connection.execute("SELECT * FROM china_sources WHERE id=?", (source_id,)).fetchone()
    defaults = connection.execute("SELECT * FROM listing_defaults WHERE id=1").fetchone()
    images = connection.execute(
        "SELECT id,sha256,image_role,excluded_at,exclusion_reason FROM source_images WHERE source_id=? ORDER BY id", (source_id,)
    ).fetchall()
    item_evidence = dict(item)
    if item_status is not None:
        item_evidence["status"] = item_status
    evidence = {
        "item": item_evidence, "source": dict(source), "defaults": dict(defaults),
        "images": [dict(image) for image in images],
    }
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def attach_preparation_status(connection: sqlite3.Connection, item_id: str, preparation: dict) -> dict:
    source_id = preparation.get("values", {}).get("china_source_id")
    row = connection.execute(
        "SELECT source_id,fingerprint,status,generated_at FROM listing_preparations WHERE item_id=?",
        (item_id,),
    ).fetchone()
    current_fingerprint = _fingerprint(connection, item_id, source_id) if source_id else None
    lifecycle_statuses = ("candidate", "sourcing", "matched", "listing_draft", "listed", "rejected")
    matching_fingerprints = {current_fingerprint}
    if source_id and row:
        matching_fingerprints.update(
            _fingerprint(connection, item_id, source_id, status)
            for status in lifecycle_statuses
        )
    is_current = bool(
        row
        and source_id == row["source_id"]
        and row["fingerprint"] in matching_fingerprints
    )
    preparation["automation"] = {
        "generated_at": row["generated_at"] if is_current else None,
        "status": row["status"] if is_current else "stale" if row else "not_generated",
        "method": "rule_based",
    }
    return preparation


def save_listing_preparation(
    connection: sqlite3.Connection,
    item_id: str,
    source_id: str | None = None,
    generated_by: str = "manual",
) -> dict:
    item = connection.execute("SELECT status,archived_at FROM items WHERE id=?", (item_id,)).fetchone()
    if item is None:
        raise ValueError("未找到商品")
    if item["archived_at"]:
        raise ValueError("请先恢复已归档商品")
    draft = connection.execute(
        "SELECT china_source_id,status FROM listing_drafts WHERE item_id=?", (item_id,)
    ).fetchone()
    if draft:
        if draft["status"] != "draft":
            raise ValueError("仅能为待发布草稿刷新上架资料包")
        if source_id and source_id != draft["china_source_id"]:
            raise ValueError("资料包必须使用当前上架草稿关联的中国货源")
        source_id = draft["china_source_id"]
    elif item["status"] != "matched":
        raise ValueError("仅能为已确认货源的商品生成资料包")
    preparation = prepare_listing(connection, item_id, source_id)
    source_id = preparation.get("values", {}).get("china_source_id")
    if not source_id:
        raise ValueError("请先确认一条中国货源，再生成上架资料")
    source = connection.execute(
        "SELECT match_status,price_cny,archived_at FROM china_sources WHERE id=? AND item_id=?",
        (source_id, item_id),
    ).fetchone()
    if source is None or source["match_status"] != "confirmed" or source["archived_at"]:
        raise ValueError("请先确认同款货源，再生成上架资料")

    fingerprint = _fingerprint(connection, item_id, source_id)
    existing = connection.execute(
        "SELECT fingerprint,generated_at FROM listing_preparations WHERE item_id=?", (item_id,)
    ).fetchone()
    changed = existing is None or existing["fingerprint"] != fingerprint
    generated_at = existing["generated_at"] if existing and not changed else now_iso()
    status = "ready_for_review" if preparation["ready_for_review"] else "needs_review"
    snapshot = {
        "values": preparation["values"], "fields": preparation["fields"],
        "missing": preparation["missing"], "notes": preparation["notes"],
        "photo_collection": preparation["photo_collection"],
        "requirements": preparation["requirements"],
    }
    connection.execute(
        """INSERT INTO listing_preparations
        (item_id,source_id,fingerprint,status,generated_data,generated_at,generation_method)
        VALUES (?,?,?,?,?,?, 'rule_based')
        ON CONFLICT(item_id) DO UPDATE SET source_id=excluded.source_id,
        fingerprint=excluded.fingerprint,status=excluded.status,
        generated_data=excluded.generated_data,generated_at=excluded.generated_at,
        generation_method=excluded.generation_method""",
        (item_id, source_id, fingerprint, status, json.dumps(snapshot, ensure_ascii=False), generated_at),
    )
    if changed:
        record_event(connection, "item", item_id, "listing_preparation_generated", {
            "source_id": source_id, "generated_by": generated_by,
            "status": status, "missing": preparation["missing"],
        })
    preparation["automation"] = {"generated_at": generated_at, "status": status, "method": "rule_based"}
    preparation["changed"] = changed
    return preparation


def prepare_confirmed_batch(connection: sqlite3.Connection, limit: int = 20, checkpoint=lambda: None) -> dict:
    rows = connection.execute(
        """SELECT i.id AS item_id,
            (SELECT s.id FROM china_sources s WHERE s.item_id=i.id AND s.match_status='confirmed'
             AND s.price_cny IS NOT NULL AND s.archived_at IS NULL
             ORDER BY s.availability_checked_at DESC,s.created_at DESC LIMIT 1) AS source_id
        FROM items i WHERE i.status='matched' AND i.archived_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM listing_drafts d WHERE d.item_id=i.id)
          AND EXISTS (SELECT 1 FROM china_sources s WHERE s.item_id=i.id AND s.match_status='confirmed'
             AND s.price_cny IS NOT NULL AND s.archived_at IS NULL)
        ORDER BY i.created_at LIMIT ?""",
        (limit,),
    ).fetchall()
    prepared, refreshed, unchanged = [], 0, 0
    for row in rows:
        checkpoint()
        result = save_listing_preparation(connection, row["item_id"], row["source_id"], "scheduled_batch")
        changed = result.pop("changed")
        refreshed += int(changed)
        unchanged += int(not changed)
        item = connection.execute("SELECT japan_title FROM items WHERE id=?", (row["item_id"],)).fetchone()
        prepared.append({
            "item_id": row["item_id"], "source_id": row["source_id"],
            "title": item["japan_title"], "status": result["automation"]["status"],
            "generated_at": result["automation"]["generated_at"],
            "missing": result["missing"], "photo_collection": result["photo_collection"],
        })
    connection.commit()
    return {"prepared": prepared, "count": len(prepared), "refreshed": refreshed, "unchanged": unchanged}
