"""
estimate_utils.py — Shared utilities for estimate manipulation.

Consolidates functions used by multiple modules (qa_agent, edit_estimate, etc.)
to avoid duplication and ensure consistent behavior.
"""


def refresh_totals(estimate: dict):
    """Recalculate all section totals and grand totals from line items.
    
    Also re-numbers all items sequentially. Call after any batch of edits.
    """
    grand = {"remove": 0.0, "replace": 0.0, "tax": 0.0, "op": 0.0, "total": 0.0}
    coverage_totals = {"Dwelling": 0.0, "Other Structures": 0.0, "Contents": 0.0}

    # Re-number all items sequentially
    num = 1
    for section in estimate.get("sections", []):
        section_totals = {"remove": 0.0, "replace": 0.0, "tax": 0.0, "op": 0.0, "total": 0.0}

        for item in section.get("line_items", []):
            item["num"] = num
            num += 1

            for k in section_totals:
                section_totals[k] = round(section_totals[k] + item.get(k, 0), 2)

        section["totals"] = section_totals

        cov = section.get("coverage", "Dwelling")
        coverage_totals[cov] = round(coverage_totals.get(cov, 0.0) + section_totals["total"], 2)

        for k in grand:
            grand[k] = round(grand[k] + section_totals[k], 2)

    estimate["line_item_total"] = grand["total"]
    estimate["tax_total"] = grand["tax"]
    estimate["op_total"] = grand["op"]
    estimate["remove_total"] = grand["remove"]
    estimate["replace_total"] = grand["replace"]
    estimate["rcv_total"] = grand["total"]
    estimate["coverage_split"] = coverage_totals
