from typing import Protocol


class MercariListingAdapter(Protocol):
    async def prepare_draft(self, item: dict, source: dict) -> dict:
        """Build listing fields for human review; live form automation is not wired yet."""
        ...

    async def publish(self, draft: dict) -> str:
        """Publish only after a human explicitly confirms the final draft."""
        ...
