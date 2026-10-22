from typing import Protocol


class JapanSelectionAdapter(Protocol):
    site_id: str

    async def search(self, query: str) -> list[dict]:
        """Return normalized candidates. A real site connector is not wired yet."""
        ...
