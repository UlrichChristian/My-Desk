"""Curated EA-matching colour palette and task accent resolution."""

from __future__ import annotations

FRAME_STYLES = ("subtle", "medium", "bold")

PALETTE = [
    {"id": "ea-blue", "hex": "#1a99d6", "label": "Blue"},
    {"id": "ea-green", "hex": "#6ebe44", "label": "Green"},
    {"id": "ea-orange", "hex": "#f07c3a", "label": "Orange"},
    {"id": "ea-grey", "hex": "#9aa5ab", "label": "Grey"},
    {"id": "ea-teal", "hex": "#0a83be", "label": "Teal"},
    {"id": "ea-purple", "hex": "#7b1fa2", "label": "Purple"},
    {"id": "ea-red", "hex": "#c73f27", "label": "Red"},
    {"id": "ea-amber", "hex": "#e65100", "label": "Amber"},
    {"id": "ea-slate", "hex": "#616163", "label": "Slate"},
    {"id": "ea-mint", "hex": "#2e7d32", "label": "Mint"},
    {"id": "ea-rose", "hex": "#c62828", "label": "Rose"},
    {"id": "ea-indigo", "hex": "#3949ab", "label": "Indigo"},
]

DEFAULT_COLOR = PALETTE[0]["hex"]

# Backfill colours for seeded parent categories (by name)
PARENT_CATEGORY_COLORS = {
    "Issues": "#c73f27",
    "Strategic": "#3949ab",
    "Monthly Recurring": "#6ebe44",
}


def palette_hex_ids() -> set[str]:
    return {p["hex"].lower() for p in PALETTE}


def resolve_task_accent(task_row: dict, category_row: dict | None = None) -> tuple[str | None, str]:
    """Return (accent_hex, frame_style) for a task tile."""
    accent = task_row.get("accent_color")
    if accent:
        frame = "subtle"
        if category_row and category_row.get("frame_style"):
            frame = category_row["frame_style"]
        elif task_row.get("category_frame_style"):
            frame = task_row["category_frame_style"]
        return accent, frame

    cat_color = task_row.get("category_color")
    if not cat_color and category_row:
        cat_color = category_row.get("color")
    if not cat_color:
        return None, "subtle"

    frame = task_row.get("category_frame_style") or "subtle"
    if category_row and category_row.get("frame_style"):
        frame = category_row["frame_style"]
    return cat_color, frame


def chip_tint(hex_color: str) -> str:
    """Light background tint for category chips."""
    return f"color-mix(in srgb, {hex_color} 18%, white)"
