#!/usr/bin/env python3
"""Parse EagleView aerial measurement report PDFs and extract key roof measurements."""

import argparse
import json
import re
import sys

from typing import Optional

import fitz  # PyMuPDF


def ft_in_to_decimal(feet_str: str, inches_str: str) -> float:
    """Convert feet'inches" to decimal feet."""
    ft = int(feet_str.replace(",", ""))
    inch = int(inches_str)
    return round(ft + inch / 12, 2)


def parse_ft_in(text: str) -> Optional[float]:
    """Extract feet'inches" pattern and convert to decimal feet."""
    m = re.search(r"([\d,]+)'\s*(\d+)\"", text)
    if m:
        return ft_in_to_decimal(m.group(1), m.group(2))
    return None


def parse_int(text: str) -> Optional[int]:
    m = re.search(r"([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _find_suggested_waste_bbox(page, waste_table: list) -> tuple:
    """
    Use bbox x-positions to match 'Suggested' label to the correct waste % column.
    Only considers waste % values that are present in waste_table (ignores
    unrelated percentages on the page like 'Areas per Pitch: 100%').
    Returns (suggested_waste_pct, suggested_squares) or (None, None).
    """
    try:
        valid_pcts = {entry["waste_pct"] for entry in waste_table if "waste_pct" in entry}
        waste_pct_x = {}   # waste_pct → x-position
        suggested_x = None

        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = span["text"].strip()
                    x = span["bbox"][0]

                    if txt == "Suggested":
                        suggested_x = x
                    elif txt.endswith("%") and txt[:-1].isdigit():
                        pct = int(txt[:-1])
                        if pct in valid_pcts:   # only accept known waste pcts
                            waste_pct_x[pct] = x

        if suggested_x is None or not waste_pct_x:
            return None, None

        # Find the waste % column whose x is closest to suggested_x
        best_pct = min(waste_pct_x, key=lambda p: abs(waste_pct_x[p] - suggested_x))

        # Look up the squares for that pct in the waste_table
        for entry in waste_table:
            if entry.get("waste_pct") == best_pct:
                return best_pct, entry.get("squares")

        return best_pct, None
    except Exception:
        return None, None


def parse_eagleview(pdf_path: str) -> dict:
    doc = fitz.open(pdf_path)
    pages = [doc[i].get_text() for i in range(len(doc))]

    result = {
        "metadata": {"report_id": None, "property_address": None, "prepared_for": None, "date": None},
        "summary": {},
        "lengths": {},
        "roofing_summary": {"structures": [], "all_structures": {}},
    }

    # --- Metadata & Summary from page 1 (index 1) ---
    p1 = pages[1] if len(pages) > 1 else ""

    # Report ID
    m = re.search(r"(\d{7,})", p1)
    if m:
        result["metadata"]["report_id"] = m.group(1)

    # Date
    m = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\n?\s*\d{4})", p1)
    if m:
        result["metadata"]["date"] = re.sub(r"\s*\n\s*", " ", m.group(1)).strip()

    # Address - try multiple patterns
    m = re.search(r"Property Address\s*\n(.+?)\n(.+?)\n", p1)
    if m:
        result["metadata"]["property_address"] = f"{m.group(1).strip()}, {m.group(2).strip()}"
    if not result["metadata"]["property_address"]:
        m = re.search(r"PROPERTY\s*\n(.+?)\n(.+?)\n", p1)
        if m:
            result["metadata"]["property_address"] = f"{m.group(1).strip()}, {m.group(2).strip()}"

    # Prepared for
    m = re.search(r"Prepared for\s*\n(.+)", p1)
    if m:
        result["metadata"]["prepared_for"] = m.group(1).strip()

    # Summary measurements
    summary_map = {
        r"Area:\s*([\d,]+)\s*sq\s*ft": ("total_area_sf", lambda m: int(m.group(1).replace(",", ""))),
        r"Roof Facets:\s*(\d+)": ("roof_facets", lambda m: int(m.group(1))),
        r"Predominant Pitch:\s*(\d+)": ("predominant_pitch_degrees", lambda m: int(m.group(1))),
        r"Number of Stories:\s*(.+)": ("stories", lambda m: m.group(1).strip()),
        r"Ridges/Hips:\s*([\d,]+)'\s*(\d+)": ("ridges_hips_lf", lambda m: ft_in_to_decimal(m.group(1), m.group(2))),
        r"Valleys:\s*([\d,]+)'\s*(\d+)": ("valleys_lf", lambda m: ft_in_to_decimal(m.group(1), m.group(2))),
        r"Rakes:\s*([\d,]+)'\s*(\d+)": ("rakes_lf", lambda m: ft_in_to_decimal(m.group(1), m.group(2))),
        r"Eaves:\s*([\d,]+)'\s*(\d+)": ("eaves_lf", lambda m: ft_in_to_decimal(m.group(1), m.group(2))),
        r"Estimated Attic:\s*([\d,]+)\s*sq\s*ft": ("estimated_attic_sf", lambda m: int(m.group(1).replace(",", ""))),
        r"Roof Penetrations:\s*(\d+)\s*\n": ("penetrations", lambda m: int(m.group(1))),
        r"Roof Penetrations Perimeter:\s*([\d,]+)'\s*(\d+)": ("penetrations_perimeter_lf", lambda m: ft_in_to_decimal(m.group(1), m.group(2))),
        r"Roof Penetrations Area:\s*(\d+)\s*sq\s*ft": ("penetrations_area_sf", lambda m: int(m.group(1))),
    }
    for pattern, (key, extractor) in summary_map.items():
        m = re.search(pattern, p1)
        if m:
            result["summary"][key] = extractor(m)

    # --- Lengths — search ALL pages (EagleView sometimes puts them on page 4, 5, or 6) ---
    lengths_map = {
        r"Ridges\s*=\s*([\d,]+)'\s*(\d+)": "ridges_lf",
        r"Hips\s*=\s*([\d,]+)'\s*(\d+)": "hips_lf",
        r"Valleys\s*=\s*([\d,]+)'\s*(\d+)": "valleys_lf",
        r"Rakes\s*=\s*([\d,]+)'\s*(\d+)": "rakes_lf",
        r"Eaves\s*=\s*([\d,]+)'\s*(\d+)": "eaves_lf",
        r"(?:^|\n)\s*Flashing\s*=\s*([\d,]+)'\s*(\d+)": "flashing_lf",
        r"Step\s+[Ff]lashing\s*=\s*([\d,]+)'\s*(\d+)": "step_flashing_lf",
        r"Parapets\s*=\s*([\d,]+)'\s*(\d+)": "parapets_lf",
        r"Other\s*=\s*([\d,]+)'\s*(\d+)": "other_lf",
    }
    for page_text in pages:
        for pattern, key in lengths_map.items():
            if key in result["lengths"]:
                continue  # already found
            m = re.search(pattern, page_text, re.IGNORECASE | re.MULTILINE)
            if m:
                result["lengths"][key] = ft_in_to_decimal(m.group(1), m.group(2))

    # --- Roofing Report Summary (page 11+) ---
    for i, page_text in enumerate(pages):
        fitz_page = doc[i]  # keep fitz page object for bbox-based extraction
        if "ROOFING REPORT SUMMARY" not in page_text:
            continue

        structure = {}

        # Structure name
        m = re.search(r"ROOFING REPORT SUMMARY\s*\n(.+)", page_text)
        if m:
            structure["name"] = m.group(1).strip()

        # Areas per pitch — EagleView lays out as columns:
        #   Roof Pitches: 1/12, 6/12, 8/12, 12/12
        #   Area (sq ft): 9.8, 1891.1, 5.7, 1984.8
        #   % of Roof: 0.3%, 48.6%, 0.1%, 51%
        # First try column format, then fall back to row format
        pitches = []
        areas_per_pitch_m = re.search(
            r"Areas?\s+per\s+Pitch.*?Roof\s+Pitches?\s*\n(.*?)Area\s*\(sq\s*ft\)\s*\n(.*?)%\s*of\s*Roof\s*\n(.*?)(?:The table|Structure|\n\n)",
            page_text, re.DOTALL | re.IGNORECASE
        )
        if areas_per_pitch_m:
            pitch_vals = re.findall(r"(\d+/\d+)", areas_per_pitch_m.group(1))
            area_vals = re.findall(r"([\d.]+)", areas_per_pitch_m.group(2))
            pct_vals = re.findall(r"([\d.]+)%?", areas_per_pitch_m.group(3))
            for j in range(min(len(pitch_vals), len(area_vals))):
                entry = {"pitch": pitch_vals[j], "area_sf": float(area_vals[j])}
                if j < len(pct_vals):
                    entry["pct"] = float(pct_vals[j])
                pitches.append(entry)
        else:
            # Fallback: row format (pitch, area, pct on consecutive lines)
            for pm in re.finditer(r"(\d+/\d+)\s*\n([\d.]+)\s*\n([\d.]+)%", page_text):
                pitches.append({"pitch": pm.group(1), "area_sf": float(pm.group(2)), "pct": float(pm.group(3))})
        if pitches:
            structure["areas_per_pitch"] = pitches

        # Complexity
        complexity_m = re.search(r"Structure Complexity\s*\n(\w+)\s*\n(\w+)\s*\n(\w+)", page_text)
        if complexity_m:
            # The bolded/selected one... just store all three, we can't tell from text
            structure["complexity_options"] = [complexity_m.group(1), complexity_m.group(2), complexity_m.group(3)]

        # Waste table — EagleView uses either "Area (Sq ft)" or "Area (m²)" labels
        waste_pcts = []
        if "Waste %" in page_text:
            after_waste = page_text.split("Waste %")[1]
            # Stop at whatever area header comes next
            for stop in ["Area (Sq ft)", "Area (m²)", "Area (sq ft)", "Squares"]:
                if stop in after_waste:
                    waste_pcts = re.findall(r"(\d+)%", after_waste.split(stop)[0])
                    break
        waste_areas_m = re.search(r"Area \([Sm][qm²² ]+\)\s*\n([\d\s]+)\n", page_text)
        waste_squares_m = re.search(r"Squares \*\s*\n([\d.\s]+)\n", page_text)

        if waste_pcts and waste_areas_m:
            areas = waste_areas_m.group(1).split()
            squares = waste_squares_m.group(1).split() if waste_squares_m else []
            waste_table = []
            for j, pct in enumerate(waste_pcts):
                entry = {"waste_pct": int(pct)}
                if j < len(areas):
                    entry["area_sf"] = int(areas[j])
                if j < len(squares):
                    entry["squares"] = float(squares[j])
                waste_table.append(entry)
            structure["waste_table"] = waste_table

            if waste_table:
                structure["measured_area_sf"] = waste_table[0].get("area_sf")
                structure["measured_squares"] = waste_table[0].get("squares")

            # Find suggested waste via bbox x-position matching
            suggested_pct, suggested_sq = _find_suggested_waste_bbox(fitz_page, waste_table)
            if suggested_pct is not None:
                structure["suggested_waste_pct"] = suggested_pct
                structure["suggested_squares"] = suggested_sq

        # Totals
        m = re.search(r"Total Roof Facets\s*=\s*(\d+)", page_text)
        if m:
            structure["total_facets"] = int(m.group(1))

        m = re.search(r"Total Area \(All Pitches\)\s*=\s*([\d,]+)\s*sq\s*ft", page_text)
        if m:
            structure["total_area_sf"] = int(m.group(1).replace(",", ""))

        # Lengths
        struct_lengths = {}
        for pattern, key in lengths_map.items():
            lm = re.search(pattern, page_text, re.IGNORECASE | re.MULTILINE)
            if lm:
                struct_lengths[key] = ft_in_to_decimal(lm.group(1), lm.group(2))

        # Additional lengths (All Structure Totals page uses these variants)
        for extra_pat, extra_key in [
            (r"Eaves/Starters?\s*[‡†]?\s*=\s*([\d,]+)'\s*(\d+)", "eaves_starter_lf"),
            (r"Drip Edge[^=]*=\s*([\d,]+)'\s*(\d+)", "drip_edge_lf"),
            (r"Step\s+Flashing\s*=\s*([\d,]+)'\s*(\d+)", "step_flashing_lf"),
        ]:
            em = re.search(extra_pat, page_text, re.IGNORECASE | re.MULTILINE)
            if em:
                struct_lengths[extra_key] = ft_in_to_decimal(em.group(1), em.group(2))

        if struct_lengths:
            structure["lengths"] = struct_lengths

        # Predominant pitch
        m = re.search(r"Predominant Pitch\s*=\s*(\d+/\d+)", page_text, re.IGNORECASE)
        if m:
            structure["predominant_pitch"] = m.group(1)

        name = structure.get("name", "")
        if "All Structure" in name:   # catches "All Structures" and "All Structure Totals"
            # Merge into all_structures (don't overwrite, update)
            existing = result["roofing_summary"].get("all_structures", {})
            existing.update(structure)
            result["roofing_summary"]["all_structures"] = existing
        else:
            result["roofing_summary"]["structures"].append(structure)

    # Build simplified top-level roofing_summary fields for easy access
    all_s = result["roofing_summary"].get("all_structures", {})
    lengths = result["lengths"]
    struct_lengths = all_s.get("lengths", {})

    # Measured squares (0% waste = base measurement)
    wt = all_s.get("waste_table", [])
    measured_sq = None
    suggested_sq = None
    suggested_waste_pct = all_s.get("suggested_waste_pct")
    if wt:
        measured_sq = wt[0].get("squares")
        result["roofing_summary"]["measured_sq"] = measured_sq
        result["roofing_summary"]["total_area_sf"] = wt[0].get("area_sf")
    if all_s.get("suggested_squares"):
        suggested_sq = all_s["suggested_squares"]
        result["roofing_summary"]["suggested_sq"] = suggested_sq
        result["roofing_summary"]["suggested_waste_pct"] = suggested_waste_pct

    # Key lengths — prefer All Structure Totals page, fall back to lengths page
    def _best(key):
        return struct_lengths.get(key) or lengths.get(key)

    ridges  = _best("ridges_lf") or 0
    hips    = _best("hips_lf") or 0
    if ridges or hips:
        result["roofing_summary"]["ridges_hips_lf"] = round(ridges + hips, 2)

    for key in ["step_flashing_lf", "eaves_lf", "eaves_starter_lf", "drip_edge_lf",
                "flashing_lf", "valleys_lf", "rakes_lf"]:
        val = _best(key)
        if val:
            result["roofing_summary"][key] = val

    doc.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="Parse EagleView PDF reports")
    parser.add_argument("pdf", help="Path to EagleView PDF")
    parser.add_argument("--output", "-o", help="Output JSON file (default: stdout)")
    args = parser.parse_args()

    result = parse_eagleview(args.pdf)
    output = json.dumps(result, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
