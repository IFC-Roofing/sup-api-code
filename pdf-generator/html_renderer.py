"""
html_renderer.py — Renders estimate.json → HTML via Jinja2 template.
"""

import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ASSETS_DIR = Path(__file__).parent / "assets"
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Category mapping for Recap by Category
# Order matters — more specific patterns first, first match wins.
# Using a list of tuples instead of dict to guarantee match order.
CATEGORY_MAP = [
    # Multi-word specific matches first
    ("labor minimum", "LABOR MINIMUMS"),
    ("drip edge", "ROOFING"),
    ("step flashing", "ROOFING"),
    ("counter flashing", "ROOFING"),
    ("pipe jack", "ROOFING"),
    ("high roof", "ROOFING"),
    ("o&p", "OVERHEAD & PROFIT"),
    ("overhead", "OVERHEAD & PROFIT"),
    # Roofing — before generic "remove"
    ("shingle", "ROOFING"),
    ("roofing", "ROOFING"),
    ("felt", "ROOFING"),
    ("underlayment", "ROOFING"),
    ("starter", "ROOFING"),
    ("hip", "ROOFING"),
    ("ridge", "ROOFING"),
    ("valley", "ROOFING"),
    ("flashing", "ROOFING"),
    ("exhaust", "ROOFING"),
    ("vent", "ROOFING"),
    ("cap", "ROOFING"),
    ("steep", "ROOFING"),
    # Gutters
    ("gutter", "SOFFIT, FASCIA, & GUTTER"),
    ("downspout", "SOFFIT, FASCIA, & GUTTER"),
    ("fascia", "SOFFIT, FASCIA, & GUTTER"),
    ("soffit", "SOFFIT, FASCIA, & GUTTER"),
    ("guard", "SOFFIT, FASCIA, & GUTTER"),
    ("splash", "SOFFIT, FASCIA, & GUTTER"),
    # Paint — before fencing so "paint iron fence" → PAINTING not FENCING
    ("paint", "PAINTING"),
    ("stain", "PAINTING"),
    # Fencing
    ("fence", "FENCING"),
    ("iron", "FENCING"),
    ("gate", "FENCING"),
    # Windows
    ("window", "WINDOWS & DOORS"),
    ("screen", "WINDOWS & DOORS"),
    ("door", "WINDOWS & DOORS"),
    # Siding
    ("siding", "SIDING"),
    # Specialty — before demolition so "remove chimney" → SPECIALTY not DEMOLITION
    ("copper", "SPECIALTY ITEMS"),
    ("chimney", "SPECIALTY ITEMS"),
    ("pergola", "SPECIALTY ITEMS"),
    ("arbor", "SPECIALTY ITEMS"),
    ("shutter", "SPECIALTY ITEMS"),
    ("corbel", "SPECIALTY ITEMS"),
    ("pilar", "SPECIALTY ITEMS"),
    ("pillar", "SPECIALTY ITEMS"),
    # Interior
    ("ceiling", "INTERIOR"),
    ("drywall", "INTERIOR"),
    ("insulation", "INTERIOR"),
    ("carpet", "INTERIOR"),
    ("floor", "INTERIOR"),
    # Demolition — generic "remove", "tear" last so they don't steal specific items
    ("haul", "GENERAL DEMOLITION"),
    ("dumpster", "GENERAL DEMOLITION"),
    ("demo", "GENERAL DEMOLITION"),
    ("debris", "GENERAL DEMOLITION"),
    ("tear off", "GENERAL DEMOLITION"),
    # General
    ("supervision", "GENERAL"),
    ("ladder", "GENERAL"),
    ("permit", "GENERAL"),
    ("tarp", "GENERAL"),
]


def categorize_item(description: str) -> str:
    desc_lower = description.lower()
    for keyword, category in CATEGORY_MAP:
        if keyword in desc_lower:
            return category
    return "GENERAL"


def build_categories(estimate: dict) -> dict[str, float]:
    """Build category totals dict for Recap by Category."""
    cats: dict[str, float] = {}
    for section in estimate.get("sections", []):
        for item in section.get("line_items", []):
            cat = categorize_item(item.get("description", ""))
            cats[cat] = round(cats.get(cat, 0.0) + item.get("total", 0.0), 2)
    # Sort by amount descending
    return dict(sorted(cats.items(), key=lambda x: -x[1]))


def build_item_categories(estimate: dict) -> dict[str, str]:
    """Map each item description → category name."""
    result = {}
    for section in estimate.get("sections", []):
        for item in section.get("line_items", []):
            desc = item.get("description", "")
            result[desc] = categorize_item(desc)
    return result


def render(estimate: dict, output_path: str) -> str:
    """
    Render estimate dict → HTML file.
    Returns path to written HTML file.
    """
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    env.filters["money"] = lambda v: "{:,.2f}".format(float(v or 0))
    template = env.get_template("estimate.html")

    logo_path = str(ASSETS_DIR / "ifc_roofing_logo.jpeg")
    css_path = str(ASSETS_DIR / "style.css")

    categories = build_categories(estimate)
    item_categories = build_item_categories(estimate)

    html_content = template.render(
        estimate=estimate,
        logo_path=logo_path,
        css_path=css_path,
        categories=categories,
        item_categories=item_categories,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[html_renderer] HTML written to {output_path}")
    return output_path


if __name__ == "__main__":
    import sys
    import json

    json_path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "estimate.json")
    with open(json_path) as f:
        estimate = json.load(f)

    output = str(Path(json_path).parent / "estimate.html")
    render(estimate, output)
