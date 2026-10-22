# Project agent instructions

- At the beginning of a conversation, read `C:/Users/Administrator/.codex/MEMORY.md` for project history and user preferences.
- For Japan product discovery, Mercari keyword searches, or reference-seller monitoring, read and follow `.agents/skills/japan-product-selection/SKILL.md` and its linked selection criteria. Preserve both discovery modes: keyword search and seller-to-listing network expansion.
- Keep evidence attached to each conclusion. A seller-network candidate is an exploration lead until its product identity, price, availability state, and source page are checked. Sold listings indicate historical demand, not current stock.
- Before preparing a Mercari Shops listing, identify the product type and the exact category leaf from the live category tree. Category-specific attributes must come from the Japan item page or confirmed China source; unknown values stay unknown. Do not reuse a figurine schema for clothing, collectibles, or other categories.
- The current local workbench runs deterministic collectors and scheduled jobs; it does not autonomously execute this Skill or recursively build the seller-product graph. Do not describe those capabilities as implemented until the corresponding backend workflow exists.
