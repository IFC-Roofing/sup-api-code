"""
Dynamic Profit Margin Sheet Builder.

Creates a Google Sheet with:
  - Tab 1: Profit Margin (dropdowns + formulas)
  - Tab 2: Materials Summary (itemized, formula-driven)
  - Tab 3: Ref - Materials (raw pricing data)
  - Tab 4: Ref - Labor (raw labor rates)
  - Tab 5: Ref - Project (trade data, EV measurements)
"""

import logging
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build as google_build

logger = logging.getLogger("profit-margin")

SUPPLIERS = ["ABC", "SRS", "Beacon"]
CREWS = ["H&R", "G5", "Achilles"]
SHARED_DRIVE_ID = "0ANY__SN6vAmeUk9PVA"


def get_creds(scopes):
    from pathlib import Path
    creds_file = Path(__file__).parent.parent.parent / "google-drive-key.json"
    return service_account.Credentials.from_service_account_file(str(creds_file).with_subject('sup@ifcroofing.com'), scopes=scopes)


def get_services():
    creds = get_creds([
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ])
    sheets = google_build("sheets", "v4", credentials=creds)
    drive = google_build("drive", "v3", credentials=creds)
    return sheets, drive


def find_or_create_folder(drive, parent_id, name):
    q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
    results = drive.files().list(
        q=q, supportsAllDrives=True, includeItemsFromAllDrives=True,
        fields="files(id)", pageSize=1
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = drive.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return folder["id"]


# ── Sheet IDs ──────────────────────────────────────────────
SHEET_PROFIT = 0
SHEET_MATERIALS = 1
SHEET_REF_MAT = 2
SHEET_REF_LABOR = 3
SHEET_REF_PROJECT = 4


def build_sheet(project_name, trades, pricing_data, ev_data, labor_data_parsed,
                roof_scope=None):
    """
    Create the dynamic profit margin spreadsheet.
    
    Args:
        project_name: str
        trades: list of trade dicts (from get_trade_financials)
        pricing_data: dict with 'materials', 'labor', 'gutters' raw rows
        ev_data: dict with EV measurements
        labor_data_parsed: dict {crew: {base_rate, steep_adder, total_rate, total_cost}}
        roof_scope: dict from supplement_parser (overrides EV for quantities)
    
    Returns: sheet_url
    """
    sheets, drive = get_services()
    
    # ── Create spreadsheet in Shared Drive ─────────────────
    folder_id = find_or_create_folder(drive, SHARED_DRIVE_ID, "Profit Margin Sheets")
    
    file_meta = {
        "name": f"{project_name} — Profit Margin",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [folder_id],
    }
    file = drive.files().create(body=file_meta, fields="id,webViewLink", supportsAllDrives=True).execute()
    sid = file["id"]
    url = file["webViewLink"]
    logger.info(f"Created spreadsheet: {sid}")
    
    # ── Add tabs ───────────────────────────────────────────
    tab_requests = [
        {"updateSheetProperties": {"properties": {"sheetId": SHEET_PROFIT, "title": "Profit Margin"}, "fields": "title"}},
        {"addSheet": {"properties": {"sheetId": SHEET_MATERIALS, "title": "Materials Summary", "index": 1}}},
        {"addSheet": {"properties": {"sheetId": SHEET_REF_MAT, "title": "Ref - Materials", "index": 2}}},
        {"addSheet": {"properties": {"sheetId": SHEET_REF_LABOR, "title": "Ref - Labor", "index": 3}}},
        {"addSheet": {"properties": {"sheetId": SHEET_REF_PROJECT, "title": "Ref - Project", "index": 4}}},
    ]
    sheets.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": tab_requests}).execute()
    
    # ── Write reference data ───────────────────────────────
    batch_values = []
    
    # Ref - Materials (raw from pricing sheet)
    batch_values.append({
        "range": "'Ref - Materials'!A1",
        "majorDimension": "ROWS",
        "values": pricing_data["materials"],
    })
    
    # Ref - Labor (raw from pricing sheet)
    batch_values.append({
        "range": "'Ref - Labor'!A1",
        "majorDimension": "ROWS",
        "values": pricing_data["labor"],
    })
    
    # Ref - Project: trade data + EV measurements
    project_rows = build_project_ref(trades, ev_data)
    batch_values.append({
        "range": "'Ref - Project'!A1",
        "majorDimension": "ROWS",
        "values": project_rows,
    })
    
    # Materials Summary tab
    materials_summary = build_materials_summary(pricing_data["materials"], ev_data, roof_scope)
    batch_values.append({
        "range": "'Materials Summary'!A1",
        "majorDimension": "ROWS",
        "values": materials_summary,
    })
    
    # Profit Margin tab
    profit_rows = build_profit_margin_tab(trades, ev_data, pricing_data, roof_scope)
    batch_values.append({
        "range": "'Profit Margin'!A1",
        "majorDimension": "ROWS",
        "values": profit_rows,
    })
    
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=sid,
        body={"valueInputOption": "USER_ENTERED", "data": batch_values}
    ).execute()
    
    # ── Add dropdowns + formatting ─────────────────────────
    format_requests = build_formatting(trades, pricing_data["materials"])
    if format_requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=sid, body={"requests": format_requests}
        ).execute()
    
    logger.info(f"Sheet ready: {url}")
    return url


# ── Reference Tab: Project Data ────────────────────────────

def build_project_ref(trades, ev):
    rows = []
    rows.append(["TRADE DATA"])
    rows.append(["Trade", "Tag", "Doing", "INS RCV", "Supp RCV", "Sub Bid Cost",
                  "NRD", "Is Roof", "Emoji"])
    
    for t in trades:
        rows.append([
            t["trade_name"],
            t["tag"],
            "YES" if t["doing"] else "NO",
            t["ins_rcv"],
            t["supp_rcv"],
            t["sub_bid_cost"],
            t["nrd"],
            "YES" if t["is_roof"] else "NO",
            t.get("emoji", ""),
        ])
    
    rows.append([])
    rows.append(["EV MEASUREMENTS"])
    rows.append(["Metric", "Value"])
    ev_fields = [
        ("Total SQ (measured)", ev.get("sq_off", ev.get("measured_sq", ev.get("total_sq", 0)))),
        ("Suggested SQ (with waste)", ev.get("sq_on", ev.get("suggested_sq", 0))),
        ("Waste %", ev.get("waste_pct", 0)),
        ("Eaves + Rakes LF", ev.get("eaves_rakes_lf", ev.get("drip_edge_lf", 0))),
        ("Hip + Ridge LF", ev.get("hip_ridge_lf", ev.get("ridges_lf", 0))),
        ("Valleys LF", ev.get("valleys_lf", 0)),
        ("Ridge Vent LF", ev.get("ridge_vent_lf", 0)),
        ("Pitch", ev.get("pitch", ev.get("predominant_pitch", 0))),
    ]
    for name, val in ev_fields:
        rows.append([name, val])
    
    return rows


# ── Materials Summary Tab ──────────────────────────────────

def build_materials_summary(materials_rows, ev, roof_scope=None):
    """Build the Materials Summary tab with formulas referencing selections.
    
    Priority: EV > Supplement for measurements (SQ, LF).
    Supplement fills in what EV can't see (vents, pipe jacks, ice & water, etc.).
    """
    rows = []
    
    # ── EV-sourced (actual measurements — always preferred) ──
    sq_on = ev.get("sq_on", ev.get("suggested_sq", 0))
    sq_off = ev.get("sq_off", ev.get("measured_sq", ev.get("total_sq", 0)))
    eaves_rakes = ev.get("eaves_rakes_lf", ev.get("drip_edge_lf", 0))
    hip_ridge = ev.get("hip_ridge_lf", ev.get("ridges_lf", 0))
    valleys = ev.get("valleys_lf", 0)
    ridge_vent = ev.get("ridge_vent_lf", 0)
    starter_lf = eaves_rakes  # EV proxy: eaves + rakes
    step_flashing_lf = ev.get("step_flashing_lf", 0)
    
    # ── Supplement-sourced (things EV can't measure) ─────────
    # These only exist in the supplement scope — EV doesn't count them
    ice_water_sf = 0
    pipe_jacks = 0
    turbines = 0
    turtle_vents = 0
    exhaust_caps = 0
    
    if roof_scope:
        ice_water_sf = roof_scope.get("ice_water_sf", 0)
        pipe_jacks = roof_scope.get("pipe_jacks", 0)
        turbines = roof_scope.get("turbines", 0)
        turtle_vents = roof_scope.get("turtle_vents", 0)
        exhaust_caps = roof_scope.get("exhaust_caps", 0)
        # Supplement fills gaps where EV has no data
        if step_flashing_lf == 0:
            step_flashing_lf = roof_scope.get("step_flashing_lf", 0)
        if starter_lf == 0:
            starter_lf = roof_scope.get("starter_lf", 0)
        if ridge_vent == 0:
            ridge_vent = roof_scope.get("ridge_vent_lf", 0)
    
    rows.append(["MATERIALS SUMMARY"])
    rows.append([f"Selections from Profit Margin tab drive the pricing below"])
    rows.append([])
    rows.append(["Selected Supplier:", "='Profit Margin'!C2"])
    rows.append(["Selected Shingle:", "='Profit Margin'!C3"])
    rows.append(["Selected Ridge Cap:", "='Profit Margin'!C4"])
    rows.append([])
    rows.append(["Category", "Product", "Qty", "Unit", "Unit Price", "Total"])
    
    # Supplier column lookup — resolves to column offset in Ref - Materials F:K range
    # F=ABC Price, G=ABC Total, H=SRS Price, I=SRS Total, J=Beacon Price, K=Beacon Total
    SUP = "'Profit Margin'!$C$2"
    SHINGLE = "'Profit Margin'!$C$3"
    RIDGE = "'Profit Margin'!$C$4"
    sup_col = f'MATCH({SUP},{{"ABC","SRS","Beacon"}},0)*2-1'
    
    def price_formula(match_expr):
        return f"=IFERROR(INDEX('Ref - Materials'!F:K,MATCH({match_expr},'Ref - Materials'!B:B,0),{sup_col}),0)"
    
    # Unit conversions — LF/SQ from EV → purchase units
    # Coverage per unit from pricing sheet descriptions:
    #   Shingles: per Square (direct)
    #   Starter SwiftStart: 116 LF per bundle
    #   Ridge caps: coverage varies by product (see description column)
    #     Shadow Ridge: 30 LF/bundle, Mountain Ridge: 20 LF, Z Ridge: 33 LF, etc.
    #   Underlayment maxfelt: 10 SQ per roll
    #   Drip Edge: 10 LF per stick
    #   Valley Metal 20"x50": 50" = 4.17 LF per piece
    #   Ridge Vent 4': 4 LF per piece
    #   Coil Nails: 1 box per 16 SQ
    
    import math
    
    # Use starter_lf from supplement scope if available, else fallback to eaves_rakes
    _starter_lf = starter_lf if roof_scope else eaves_rakes
    
    # Dynamic row counter for formula references
    data_row = 9  # first material data row
    
    # ── Core materials ─────────────────────────────────────
    
    # Shingles — SQ direct
    shingle_qty = math.ceil(sq_on) if sq_on > 0 else 0
    rows.append(["Shingles", f"={SHINGLE}", shingle_qty, "SQ",
                  price_formula(SHINGLE), f"=E{data_row}*C{data_row}"])
    data_row += 1
    
    # Ridge Cap — bundles (30 LF/bundle for Shadow Ridge)
    ridge_coverage = 30
    ridge_qty = math.ceil(hip_ridge / ridge_coverage) if hip_ridge > 0 else 0
    rows.append(["Ridge Cap", f"={RIDGE}", ridge_qty, f"Bundles ({ridge_coverage} LF ea)",
                  price_formula(RIDGE), f"=E{data_row}*C{data_row}"])
    data_row += 1
    
    # Starter — bundles (116 LF/bundle)
    starter_coverage = 116
    starter_qty = math.ceil(_starter_lf / starter_coverage) if _starter_lf > 0 else 0
    rows.append(["Starter", "SwiftStart", starter_qty, f"Bundles ({starter_coverage} LF ea)",
                  price_formula('"Certainteed SwiftStart*"'), f"=E{data_row}*C{data_row}"])
    data_row += 1
    
    # Underlayment — rolls (10 SQ/roll)
    felt_coverage = 10
    felt_qty = math.ceil(sq_off / felt_coverage) if sq_off > 0 else 0
    rows.append(["Underlayment", "Maxfelt XT", felt_qty, f"Rolls ({felt_coverage} SQ ea)",
                  price_formula('"Private label maxfelt*"'), f"=E{data_row}*C{data_row}"])
    data_row += 1
    
    # Drip Edge — sticks (10 LF/stick)
    drip_coverage = 10
    drip_qty = math.ceil(eaves_rakes / drip_coverage) if eaves_rakes > 0 else 0
    rows.append(["Drip Edge", "1.5 in Galvanized", drip_qty, f"Sticks ({drip_coverage} LF ea)",
                  price_formula('"1.5 in"'), f"=E{data_row}*C{data_row}"])
    data_row += 1
    
    # Valley Metal — pieces (50" = 4.17 LF ea)
    valley_coverage = 4.17
    valley_qty = math.ceil(valleys / valley_coverage) if valleys > 0 else 0
    rows.append(["Valley Metal", "20\" x 50\"", valley_qty, "Pieces (50\" ea)",
                  price_formula('"Valley Metal 20*"'), f"=E{data_row}*C{data_row}"])
    data_row += 1
    
    # Nails — boxes (1 per 16 SQ)
    nail_coverage = 16
    nail_qty = math.ceil(sq_on / nail_coverage) if sq_on > 0 else 0
    rows.append(["Coil Nails", "1 1/2\"", nail_qty, f"Boxes (1 per {nail_coverage} SQ)",
                  price_formula('"Coil Nails (1 1/2*"'), f"=E{data_row}*C{data_row}"])
    data_row += 1
    
    # ── Conditional items (from supplement scope) ──────────
    
    # Ice & Water — only if in scope
    if ice_water_sf > 0:
        iw_coverage = 200  # ~200 SF per roll (2 SQ)
        iw_qty = math.ceil(ice_water_sf / iw_coverage)
        rows.append(["Ice & Water Shield", "Stormguard / Polyglass", iw_qty, f"Rolls (~{iw_coverage} SF ea)",
                      price_formula('"Polyglass MTS*"'), f"=E{data_row}*C{data_row}"])
        data_row += 1
    
    # Ridge Vent — only if in scope (NOT turbines/turtles)
    if ridge_vent > 0:
        rv_coverage = 4
        rv_qty = math.ceil(ridge_vent / rv_coverage)
        rows.append(["Ridge Vent", "4' sections", rv_qty, f"Pieces ({rv_coverage} LF ea)",
                      price_formula('"Ridge Vent 4*"'), f"=E{data_row}*C{data_row}"])
        data_row += 1
    
    # Turbines — if in scope
    if turbines > 0:
        rows.append(["Turbines", "14\" Lomanco", turbines, "Each",
                      price_formula('"Turbines 14*"'), f"=E{data_row}*C{data_row}"])
        data_row += 1
    
    # Pipe Jacks — if in scope
    if pipe_jacks > 0:
        rows.append(["Pipe Jacks", "Lead", pipe_jacks, "Each",
                      price_formula('"1.5 in"'),  # TODO: match actual pipe jack size from pricing
                      f"=E{data_row}*C{data_row}"])
        data_row += 1
    
    # Step Flashing — if in scope
    if step_flashing_lf > 0:
        sf_coverage = 1  # step flashing bundles vary; approximate
        rows.append(["Step Flashing", "Bundle", math.ceil(step_flashing_lf / 100), "Bundles (~100 pcs)",
                      price_formula('"Step Flashing"'), f"=E{data_row}*C{data_row}"])
        data_row += 1
    
    last_material_row = data_row - 1
    
    rows.append([])
    total_row_num = data_row + 1  # +1 for empty row
    rows.append(["", "", "", "", "TOTAL MATERIALS:", f"=SUM(F9:F{last_material_row})"])
    
    return rows


# ── Profit Margin Tab ──────────────────────────────────────

def build_profit_margin_tab(trades, ev, pricing_data, roof_scope=None):
    """Build the main Profit Margin tab with dropdowns and formulas."""
    
    # Pre-select defaults from supplement scope if available
    default_shingle = "Certainteed Landmark"
    default_ridge = "Certainteed Shadow Ridge"
    vent_info = ""
    
    if roof_scope:
        if roof_scope.get("shingle_type"):
            default_shingle = roof_scope["shingle_type"]
        
        # Build vent summary from supplement
        vent_parts = []
        if roof_scope.get("ridge_vent_lf", 0) > 0:
            vent_parts.append(f"Ridge Vent: {roof_scope['ridge_vent_lf']} LF")
        if roof_scope.get("turbines", 0) > 0:
            vent_parts.append(f"Turbines: {roof_scope['turbines']}")
        if roof_scope.get("turtle_vents", 0) > 0:
            vent_parts.append(f"Turtle Vents: {roof_scope['turtle_vents']}")
        if roof_scope.get("power_vents", 0) > 0:
            vent_parts.append(f"Power Vents: {roof_scope['power_vents']}")
        if roof_scope.get("exhaust_caps", 0) > 0:
            vent_parts.append(f"Exhaust Caps: {roof_scope['exhaust_caps']}")
        if roof_scope.get("pipe_jacks", 0) > 0:
            vent_parts.append(f"Pipe Jacks: {roof_scope['pipe_jacks']}")
        vent_info = " | ".join(vent_parts) if vent_parts else "None specified"
    
    rows = []
    rows.append(["PROFIT MARGIN BREAKDOWN", "", "SELECTIONS", "", "", "", "", "", "", ""])
    rows.append(["Supplier:", "", "ABC", "", "", "", "", "", "", ""])                    # C2
    rows.append(["Shingle:", "", default_shingle, "", "", "", "", "", "", ""])           # C3
    rows.append(["Ridge Cap:", "", default_ridge, "", "", "", "", "", "", ""])           # C4
    rows.append(["Crew:", "", "H&R", "", f"Ventilation: {vent_info}" if vent_info else "", "", "", "", "", ""])  # C5 + vent info in E5
    rows.append([])
    
    # ── Column headers (row 7) ─────────────────────────────
    rows.append([
        "Trade",           # A
        "Scope",           # B
        "Source",          # C
        "True Cost",       # D
        "Guaranteed Rev",  # E (Current INS)
        "Potential Rev",   # F (IFC Supp)
        "Guar. Margin $",  # G
        "Guar. Margin %",  # H
        "Pot. Margin $",   # I
        "Pot. Margin %",   # J
    ])
    
    # ── Trade rows (row 8+) ────────────────────────────────
    active_trades = [t for t in trades if t["doing"]]

    # EV > Supplement for SQ (EV is the actual measurement)
    sq_on = ev.get("sq_on", ev.get("suggested_sq", 0))
    if sq_on == 0 and roof_scope and roof_scope.get("shingle_sq", 0) > 0:
        sq_on = roof_scope["shingle_sq"]  # fallback to supplement only if no EV
    has_ev = sq_on > 0

    pitch = ev.get("pitch", ev.get("predominant_pitch", 0))

    data_row = 8  # first trade data row (1-indexed in sheets)
    roof_rows = []

    # ── Combine all roof trades into one row ───────────────
    # All structures (house, detached garage, etc.) share one material calc
    # based on total EV SQ. Revenue = sum of all active roof trades.
    roof_trades = [t for t in active_trades if t["is_roof"]]
    non_roof_trades = [t for t in active_trades if not t["is_roof"]]

    if roof_trades and has_ev:
        r = data_row
        roof_ins = sum(t["ins_rcv"] for t in roof_trades)
        roof_supp = sum(t["supp_rcv"] for t in roof_trades)
        roof_nrd = sum(t["nrd"] for t in roof_trades)
        nrd_note = f" (⚠️ NRD: ${roof_nrd:,.0f})" if roof_nrd > 0 else ""
        trade_names = " + ".join(t["trade_name"] for t in roof_trades)
        scope = f"{sq_on} SQ" if len(roof_trades) == 1 else f"{sq_on} SQ (all structures)"

        crew_rate = (
            f'IFERROR(IF($C$5="H&R",INDEX(\'Ref - Labor\'!$D:$D,MATCH("Field Squares",\'Ref - Labor\'!$B:$B,0)),'
            f'IF($C$5="G5",INDEX(\'Ref - Labor\'!$F:$F,MATCH("Field Squares",\'Ref - Labor\'!$B:$B,0)),'
            f'INDEX(\'Ref - Labor\'!$H:$H,MATCH("Field Squares",\'Ref - Labor\'!$B:$B,0)))),0)'
        )
        steep_rate = (
            f'IFERROR(IF($C$5="H&R",INDEX(\'Ref - Labor\'!$D:$D,MATCH("{pitch}/12",\'Ref - Labor\'!$B:$B,0)),'
            f'IF($C$5="G5",INDEX(\'Ref - Labor\'!$F:$F,MATCH("{pitch}/12",\'Ref - Labor\'!$B:$B,0)),'
            f'INDEX(\'Ref - Labor\'!$H:$H,MATCH("{pitch}/12",\'Ref - Labor\'!$B:$B,0)))),0)'
        )

        extra_mat = 0
        if roof_scope:
            if roof_scope.get("ice_water_sf", 0) > 0: extra_mat += 1
            if roof_scope.get("ridge_vent_lf", 0) > 0: extra_mat += 1
            if roof_scope.get("turbines", 0) > 0: extra_mat += 1
            if roof_scope.get("pipe_jacks", 0) > 0: extra_mat += 1
            if roof_scope.get("step_flashing_lf", 0) > 0: extra_mat += 1
        mat_total_row = 9 + 7 + extra_mat + 1
        mat_total_ref = f"'Materials Summary'!F{mat_total_row}"
        cost_formula = f"={mat_total_ref}+({crew_rate}+{steep_rate})*{sq_on}"

        rows.append([
            trade_names + nrd_note,
            scope,
            f"=C2&\" + \"&C5",
            cost_formula,
            roof_ins - roof_nrd,
            roof_supp - roof_nrd,
            f"=E{r}-D{r}",
            f"=IF(E{r}>0,G{r}/E{r},0)",
            f"=F{r}-D{r}",
            f"=IF(F{r}>0,I{r}/F{r},0)",
        ])
        roof_rows.append(r)
        data_row += 1

    elif roof_trades and not has_ev:
        # Roof trades exist but no EV — show as sub-bid fallback
        for t in roof_trades:
            r = data_row
            nrd_note = f" (⚠️ NRD: ${t['nrd']:,.0f})" if t["nrd"] > 0 else ""
            rows.append([
                t["trade_name"] + nrd_note,
                "⚠️ No EV",
                "Sub bid" if t["sub_bid_cost"] > 0 else "⚠️ MISSING",
                t["sub_bid_cost"] if t["sub_bid_cost"] > 0 else "⚠️ MISSING",
                t["ins_rcv"] - t["nrd"],
                t["supp_rcv"] - t["nrd"],
                f"=IF(ISNUMBER(D{r}),E{r}-D{r},\"—\")",
                f"=IF(ISNUMBER(G{r}),IF(E{r}>0,G{r}/E{r},0),\"—\")",
                f"=IF(ISNUMBER(D{r}),F{r}-D{r},\"—\")",
                f"=IF(ISNUMBER(I{r}),IF(F{r}>0,I{r}/F{r},0),\"—\")",
            ])
            data_row += 1

    for t in non_roof_trades:
        r = data_row
        ins_rcv = t["ins_rcv"]
        supp_rcv = t["supp_rcv"]
        sub_bid = t["sub_bid_cost"]
        nrd = t["nrd"]
        nrd_note = f" (⚠️ NRD: ${nrd:,.0f})" if nrd > 0 else ""

        scope = "Per bid" if sub_bid > 0 else "⚠️ No bid"
        rows.append([
            t["trade_name"] + nrd_note,
            scope,
            "Sub bid" if sub_bid > 0 else "⚠️ MISSING",
            sub_bid if sub_bid > 0 else "⚠️ MISSING",
            ins_rcv - nrd,
            supp_rcv - nrd,
            f"=IF(ISNUMBER(D{r}),E{r}-D{r},\"—\")",
            f"=IF(ISNUMBER(G{r}),IF(E{r}>0,G{r}/E{r},0),\"—\")",
            f"=IF(ISNUMBER(D{r}),F{r}-D{r},\"—\")",
            f"=IF(ISNUMBER(I{r}),IF(F{r}>0,I{r}/F{r},0),\"—\")",
        ])
        data_row += 1
    
    last_trade_row = data_row - 1
    
    # ── Opted out trades ───────────────────────────────────
    opted_out = [t for t in trades if not t["doing"] and t["ins_rcv"] > 0]
    if opted_out:
        rows.append([])
        data_row += 1
        rows.append(["OPTED OUT (applied to deductible)"])
        data_row += 1
        for t in opted_out:
            rows.append([
                f"👎 {t['trade_name']}",
                "HO opted out",
                "—",
                0,
                f"${t['ins_rcv']:,.2f} → deductible",
            ])
            data_row += 1
    
    # ── Overhead + EV cost ─────────────────────────────────
    rows.append([])
    data_row += 1
    
    oh_row = data_row
    rows.append([
        "Office Overhead (10%)",
        "",
        "Fixed",
        f"=SUM(E8:E{last_trade_row})*0.10",  # 10% of guaranteed revenue
    ])
    data_row += 1
    
    ev_row = data_row
    rows.append(["EagleView", "", "Fixed", 45])
    data_row += 1
    
    # ── Totals ─────────────────────────────────────────────
    rows.append([])
    data_row += 1
    
    total_row = data_row
    rows.append([
        "TOTALS",
        "",
        "",
        f"=SUMPRODUCT((ISNUMBER(D8:D{last_trade_row}))*D8:D{last_trade_row})+D{oh_row}+D{ev_row}",
        f"=SUM(E8:E{last_trade_row})",
        f"=SUM(F8:F{last_trade_row})",
        f"=E{total_row}-D{total_row}",
        f"=IF(E{total_row}>0,G{total_row}/E{total_row},0)",
        f"=F{total_row}-D{total_row}",
        f"=IF(F{total_row}>0,I{total_row}/F{total_row},0)",
    ])
    data_row += 1
    
    # ── Commission ─────────────────────────────────────────
    rows.append([])
    data_row += 1
    rows.append(["COMMISSION (50% standard)"])
    data_row += 1
    rows.append(["Guaranteed Commission", "", "", "", "", "", f"=G{total_row}*0.5"])
    data_row += 1
    rows.append(["Potential Commission", "", "", "", "", "", "", "", f"=I{total_row}*0.5"])
    
    return rows


# ── Formatting & Dropdowns ─────────────────────────────────

def get_shingle_options(materials_rows):
    """Extract available shingle names from the pricing table."""
    shingles = []
    in_pricing_table = False
    in_shingle_section = False
    for row in materials_rows:
        if len(row) < 2:
            continue
        item = row[1].strip() if len(row) > 1 else ""
        
        if "Material Specifications" in item:
            in_pricing_table = True
            continue
        if not in_pricing_table:
            continue
        
        if item == "Shingles":
            in_shingle_section = True
            continue
        if in_shingle_section:
            if item == "Starter" or item == "Ridge" or not item:
                break
            if any(c.isalpha() for c in item):
                shingles.append(item)
    return shingles


def get_ridge_options(materials_rows):
    """Extract available ridge cap names from the pricing table (not the input area).
    The pricing table starts after 'Material Specifications' row."""
    ridges = []
    in_pricing_table = False
    in_ridge_section = False
    for row in materials_rows:
        if len(row) < 2:
            continue
        item = row[1].strip() if len(row) > 1 else ""
        
        # Only look in the pricing table section
        if "Material Specifications" in item:
            in_pricing_table = True
            continue
        if not in_pricing_table:
            continue
        
        if item == "Ridge":
            in_ridge_section = True
            continue
        if in_ridge_section:
            if item in ("Underlayment", "Drip edge", "") or not any(c.isalpha() for c in item):
                break
            ridges.append(item)
    return ridges


def build_formatting(trades, materials_rows):
    """Build formatting requests: dropdowns, bold headers, number formats, column widths."""
    requests = []
    
    # ── Dropdowns ──────────────────────────────────────────
    
    # Supplier dropdown (C2)
    requests.append(data_validation(SHEET_PROFIT, 1, 2, SUPPLIERS))
    
    # Shingle dropdown (C3)
    shingle_options = get_shingle_options(materials_rows)
    if shingle_options:
        requests.append(data_validation(SHEET_PROFIT, 2, 2, shingle_options))
    
    # Ridge Cap dropdown (C4)
    ridge_options = get_ridge_options(materials_rows)
    if ridge_options:
        requests.append(data_validation(SHEET_PROFIT, 3, 2, ridge_options))
    
    # Crew dropdown (C5)
    requests.append(data_validation(SHEET_PROFIT, 4, 2, CREWS))
    
    # ── Bold headers ───────────────────────────────────────
    
    # Title row
    requests.append(bold_row(SHEET_PROFIT, 0, 0, 10, font_size=14))
    
    # Selection labels
    for r in range(1, 5):
        requests.append(bold_row(SHEET_PROFIT, r, 0, 1))
    
    # Column headers (row 7, index 6)
    requests.append(bold_row(SHEET_PROFIT, 6, 0, 10, bg=(0.2, 0.2, 0.2), fg=(1, 1, 1)))
    
    # Materials Summary title
    requests.append(bold_row(SHEET_MATERIALS, 0, 0, 6, font_size=14))
    requests.append(bold_row(SHEET_MATERIALS, 7, 0, 6, bg=(0.2, 0.2, 0.2), fg=(1, 1, 1)))
    
    # ── Number formats ─────────────────────────────────────
    
    # Currency format for cost/revenue/margin columns (D, E, F, G, I)
    # Use row 50 as end to cover trades + opted out + overhead + totals + commission
    for col in [3, 4, 5, 6, 8]:  # D=3, E=4, F=5, G=6, I=8
        requests.append(number_format(SHEET_PROFIT, 7, 50, col, col + 1, "$#,##0.00"))
    
    # Percentage format for margin % columns (H, J)
    for col in [7, 9]:  # H=7, J=9
        requests.append(number_format(SHEET_PROFIT, 7, 50, col, col + 1, "0.0%"))
    
    # Materials Summary currency
    requests.append(number_format(SHEET_MATERIALS, 8, 20, 4, 6, "$#,##0.00"))
    
    # ── Column widths ──────────────────────────────────────
    col_widths = [200, 120, 120, 120, 140, 140, 140, 100, 140, 100]
    for i, w in enumerate(col_widths):
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": SHEET_PROFIT,
                    "dimension": "COLUMNS",
                    "startIndex": i,
                    "endIndex": i + 1,
                },
                "properties": {"pixelSize": w},
                "fields": "pixelSize",
            }
        })
    
    # Freeze rows
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": SHEET_PROFIT, "gridProperties": {"frozenRowCount": 7}},
            "fields": "gridProperties.frozenRowCount",
        }
    })
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": SHEET_MATERIALS, "gridProperties": {"frozenRowCount": 8}},
            "fields": "gridProperties.frozenRowCount",
        }
    })
    
    # Hide reference tabs
    for sheet_id in [SHEET_REF_MAT, SHEET_REF_LABOR, SHEET_REF_PROJECT]:
        requests.append({
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "hidden": True},
                "fields": "hidden",
            }
        })
    
    return requests


def data_validation(sheet_id, row, col, options):
    """Create a dropdown data validation rule."""
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row,
                "endRowIndex": row + 1,
                "startColumnIndex": col,
                "endColumnIndex": col + 1,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": v} for v in options],
                },
                "showCustomUi": True,
                "strict": True,
            },
        }
    }


def bold_row(sheet_id, row, start_col, end_col, font_size=None, bg=None, fg=None):
    """Format a row as bold with optional background/foreground colors."""
    fmt = {"bold": True}
    if font_size:
        fmt["fontSize"] = font_size
    if fg:
        fmt["foregroundColor"] = {"red": fg[0], "green": fg[1], "blue": fg[2]}
    
    cell_format = {"textFormat": fmt}
    if bg:
        cell_format["backgroundColor"] = {"red": bg[0], "green": bg[1], "blue": bg[2]}
    
    fields = "userEnteredFormat(textFormat"
    if bg:
        fields += ",backgroundColor"
    fields += ")"
    
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row,
                "endRowIndex": row + 1,
                "startColumnIndex": start_col,
                "endColumnIndex": end_col,
            },
            "cell": {"userEnteredFormat": cell_format},
            "fields": fields,
        }
    }


def number_format(sheet_id, start_row, end_row, start_col, end_col, pattern):
    """Apply number format to a range."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": start_row,
                "endRowIndex": end_row,
                "startColumnIndex": start_col,
                "endColumnIndex": end_col,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "NUMBER", "pattern": pattern}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }
