from fastapi import HTTPException


ALLOWED_TRANSITIONS = {
    "candidate": {"sourcing", "rejected"},
    "sourcing": {"matched", "rejected"},
    "matched": {"listing_draft", "rejected"},
    "listing_draft": {"listed", "rejected"},
    "listed": set(),
    "rejected": set(),
}


def require_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=409,
            detail=f"不允许商品状态从 {current} 变更为 {target}",
        )
