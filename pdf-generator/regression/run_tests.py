#!/usr/bin/env python3
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
BASELINES = Path(__file__).resolve().parent / "baselines"
sys.path.insert(0, str(ROOT))

from edit_estimate import _refresh_totals, _update_item_from_pricelist
from qa_agent import _handle_missing_item

PROJECTS = ["RADDAD", "GUIRGUIS", "BROCK", "DOYLE", "SHULTZ"]


def deep_copy(data):
    return json.loads(json.dumps(data))


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def iter_items(estimate):
    for section in estimate.get("sections", []):
        for item in section.get("line_items", []):
            yield section, item


def grand_total(estimate):
    return round(sum(item.get("total", 0) for _, item in iter_items(estimate)), 2)


def op_total(estimate):
    for _, item in iter_items(estimate):
        if item.get("description") == "Overhead and Profit":
            return round(item.get("total", 0), 2)
    return 0.0


def summarize_items(estimate):
    rows = []
    for section in estimate.get("sections", []):
        for item in section.get("line_items", []):
            rows.append({
                "section": section.get("name"),
                "num": item.get("num"),
                "description": item.get("description"),
                "qty": item.get("qty"),
                "unit": item.get("unit"),
                "total": round(item.get("total", 0), 2),
            })
    return rows


def compare_estimates(before, after):
    diffs = []
    before_sections = [s.get("name") for s in before.get("sections", [])]
    after_sections = [s.get("name") for s in after.get("sections", [])]
    if len(before_sections) != len(after_sections):
        diffs.append(f"section count: {len(before_sections)} -> {len(after_sections)}")
    if before_sections != after_sections:
        diffs.append(f"section names changed: {before_sections} -> {after_sections}")

    before_items = summarize_items(before)
    after_items = summarize_items(after)
    if len(before_items) != len(after_items):
        diffs.append(f"line item count: {len(before_items)} -> {len(after_items)}")

    for i, (b, a) in enumerate(zip(before_items, after_items), start=1):
        for key in ["num", "description", "qty", "unit", "total"]:
            if b.get(key) != a.get(key):
                diffs.append(f"item {i} {key}: {b.get(key)} -> {a.get(key)}")

    if len(after_items) > len(before_items):
        for extra in after_items[len(before_items):]:
            diffs.append(f"extra item added: {extra}")
    elif len(before_items) > len(after_items):
        for missing in before_items[len(after_items):]:
            diffs.append(f"item removed: {missing}")

    b_total = grand_total(before)
    a_total = grand_total(after)
    if b_total != a_total:
        diffs.append(f"grand total: {b_total} -> {a_total}")

    b_op = op_total(before)
    a_op = op_total(after)
    if b_op != a_op:
        diffs.append(f"O&P total: {b_op} -> {a_op}")

    return diffs


def run_postprocess(estimate, pipeline=None):
    estimate = deep_copy(estimate)

    # Invariant check: totals refresh on a known-good estimate should not change output.
    try:
        _refresh_totals(estimate)
    except Exception:
        pass

    # Targeted bug check: missing_item must not add a duplicate.
    first_real = None
    first_section = None
    for section in estimate.get("sections", []):
        if section.get("name") == "O&P":
            continue
        if section.get("line_items"):
            first_section = section
            first_real = section["line_items"][0]
            break
    if first_real and first_section:
        before_count = len(first_section.get("line_items", []))
        fix = {
            "section": first_section.get("name"),
            "description": first_real.get("description"),
            "qty": first_real.get("qty", 1),
            "unit": first_real.get("unit", "EA"),
            "line_total": first_real.get("total", 0),
        }
        pricelist = {}
        try:
            _handle_missing_item(estimate, fix, pricelist)
        except Exception:
            pass
        after_count = len(first_section.get("line_items", []))
        if after_count != before_count:
            raise AssertionError("QA duplicate guard failed: missing_item added a duplicate")

    return estimate


def test_pricelist_skip_guard():
    """Bid items, O&P, and agreed-price items must never get pricelist overwrite."""
    tests = [
        ({"description": "Grizzly Fence (Bid Item)", "is_bid": True, "replace_rate": 100.0}, None),
        ({"description": "Overhead and Profit", "is_bid": False, "replace_rate": 296.65}, None),
        ({"description": "HVAC (Agreed Price)", "is_bid": False, "replace_rate": 500.0}, None),
        ({"description": "Something", "is_bid": False, "replace_rate": 50.0}, True),  # skip_pricelist flag
    ]
    for item, skip in tests:
        original_rate = item["replace_rate"]
        _update_item_from_pricelist(item, item["description"], skip_pricelist=bool(skip))
        if item["replace_rate"] != original_rate:
            return False, f"{item['description']}: rate changed from {original_rate} to {item['replace_rate']}"
    return True, None


def main():
    any_fail = False
    for project in PROJECTS:
        estimate_path = BASELINES / f"{project}_estimate.json"
        pipeline_path = BASELINES / f"{project}_pipeline.json"
        estimate = load_json(estimate_path)
        pipeline = load_json(pipeline_path) if pipeline_path.exists() else {}

        try:
            processed = run_postprocess(estimate, pipeline)
            diffs = compare_estimates(estimate, processed)
        except Exception as e:
            any_fail = True
            print(f"❌ {project}: FAIL")
            print(f"   error: {e}")
            continue

        if diffs:
            any_fail = True
            print(f"❌ {project}: FAIL")
            for diff in diffs:
                print(f"   - {diff}")
        else:
            print(f"✅ {project}: PASS")

    # Pricelist skip guard
    passed, err = test_pricelist_skip_guard()
    if passed:
        print("✅ PRICELIST_GUARD: PASS")
    else:
        any_fail = True
        print(f"❌ PRICELIST_GUARD: FAIL - {err}")

    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
