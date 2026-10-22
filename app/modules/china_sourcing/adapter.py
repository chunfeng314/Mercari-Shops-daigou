from typing import Protocol


class ChinaSourcingAdapter(Protocol):
    site_id: str

    async def search(self, query: str, image_url: str | None = None) -> list[dict]:
        """Return normalized source candidates. Search and matching stay manual initially."""
        ...
