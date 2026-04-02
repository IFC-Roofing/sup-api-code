"""
flow_package.py — Build the Clarity Flow card update package.

Core change: AI attributes EVERY line item (INS + our estimate) to a @tag.
Then we sum per @tag to get the trade card totals.

This replaces the old section-name mapping approach. The AI handles edge cases:
  - Dumpster → @shingle_roof (roof debris)
  - Satellite dish → @shingle_roof (R&R for roof access)
  - Electrician labor → context-dependent (@shingle_roof if for disconnect, or own trade)
  - Debris removal → @shingle_roof
  - General conditions → AI decides based on project scope
  - Supervision → split or assign to largest trade

Output (Clarity schema):
  - Bid cards: retail_exactimate_bid, op_from_ifc_supplement, original_sub_bid_price,
               latest_rcv_rcv, latest_rcv_op, latest_rcv_non_recoverable_depreciation,
               supplement_notes
  - Pricelist card: ins_price_list, our_price_list
  - O&P card: Clarity derives from trade totals — we skip
  - IFC card: manual for now — skip
"""

import json
import os
from typing import Optional
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

OP_RATE    = 0.20
OP_DIVISOR = 1.20  # retail already includes O&P


def _op_from_retail(retail: float) -> float:
    return round(retail / OP_DIVISOR * OP_RATE, 2)


# ---------------------------------------------------------------------------
# Action tracker helpers
# ---------------------------------------------------------------------------

def _get_cards_by_type(action_trackers: list) -> dict:
    result = {"bid": [], "o&p": None, "pricelist": None, "project_created": None}
    for card in action_trackers:
        atype = (card.get("action_type") or "").lower()
        if atype == "bid":
            result["bid"].append(card)
        elif atype == "o&p":
            result["o&p"] = card
        elif atype == "pricelist":
            result["pricelist"] = card
        elif atype == "project_created":
            result["project_created"] = card
    return result


def _find_bid_card(bid_cards: list, tag: str, scope: str = "") -> Optional[dict]:
    matching = [c for c in bid_cards if c.get("tag") == tag]
    if not matching:
        return None
    if len(matching) == 1:
        return matching[0]
    if scope:
        scope_lower = scope.lower()
        for card in matching:
            content = (card.get("content") or card.get("description") or
                       card.get("trade_production_notes") or "").lower()
            if scope_lower in content or (content and content in scope_lower):
                return card
    return matching[0]


# ---------------------------------------------------------------------------
# Build tag catalogue from Flow bid cards
# ---------------------------------------------------------------------------

def _build_tag_catalogue(bid_cards: list, bids: list) -> dict:
    """
    Build a dict of available @tags for this project with descriptions.
    Sources: existing Flow bid cards + pipeline bids.

    Returns: {"@shingle_roof": "Shingle Roof", "@gutter": "Gutters — Grizzly Fence", ...}
    """
    catalogue = {}
    for card in bid_cards:
        tag = card.get("tag")
        if not tag:
            continue
        label = (card.get("content") or card.get("description") or
                 card.get("trade_production_notes") or tag.lstrip("@").replace("_", " ").title())
        if tag in catalogue:
            catalogue[tag] += f" / {label}"
        else:
            catalogue[tag] = label

    for bid in bids:
        tag = bid.get("trade")
        if not tag or tag in catalogue:
            continue
        scope = bid.get("scope") or tag.lstrip("@").replace("_", " ").title()
        catalogue[tag] = scope

    return catalogue


# ---------------------------------------------------------------------------
# AI attribution — the core
# ---------------------------------------------------------------------------

ATTRIBUTION_PROMPT = """You are an insurance supplement expert for a roofing and construction company.

Your job: attribute every line item to the correct trade tag so we can populate Flow card totals.

## AVAILABLE TRADES FOR THIS PROJECT
{tag_catalogue}

## ATTRIBUTION RULES
- Assign each item to the ONE @tag it primarily belongs to
- If an item clearly supports a specific trade's work, assign it there
- Common edge cases:
  * Dumpster / debris haul / dump fees → @shingle_roof (roof debris is the primary driver)
  * Satellite dish D&R / antenna → @shingle_roof (removed for roof access)
  * Electrician labor for disconnect/reconnect → @shingle_roof (enabling roof work)
  * Electrician labor for actual electrical repairs → @other or its own tag if present
  * Scaffolding / staging → assign to the trade that requires it most
  * Supervision / project management → split proportionally — assign to the largest trade
  * General conditions → @shingle_roof if roof-dominant project, otherwise split
  * Labor minimums → assign to the trade the labor is for
  * Tax line items → assign same tag as the material they tax
  * O&P line items → mark as op=true, assign to the overall project (tag = "__op__")
  * Paint / prime on existing structure → @paint if available, otherwise parent trade
  * Permits → assign to the primary trade requiring the permit

## PROJECT CONTEXT
{project_context}

## ITEMS TO ATTRIBUTE

### INS ESTIMATE ITEMS (what insurance is paying):
{ins_items}

### OUR SUPPLEMENT ITEMS (what we are requesting):
{supp_items}

## OUTPUT FORMAT
Return ONLY valid JSON — no markdown, no explanation:
{{
  "ins": [
    {{"id": 1, "tag": "@shingle_roof", "note": "brief reason"}},
    {{"id": 2, "tag": "@shingle_roof", "note": "dumpster for roof debris"}},
    ...
  ],
  "supp": [
    {{"id": 1, "tag": "@shingle_roof", "note": "brief reason"}},
    ...
  ]
}}

Rules:
- Every item must get a tag — no skipping
- Use exactly the @tags listed above (or "__op__" for O&P lines)
- id = the number shown before each item
- If a tag from the list doesn't exist for an edge-case item, use the closest match"""


def ai_attribute_items(ins_items: list, supp_items: list,
                        tag_catalogue: dict, project_context: str,
                        verbose: bool = False) -> dict:
    """
    AI pass: attribute every INS and estimate line item to a @tag.

    Returns:
    {
        "ins":  {1: "@shingle_roof", 2: "@gutter", ...},   # keyed by item id
        "supp": {1: "@shingle_roof", 2: "@fence",  ...},
    }
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Format tag catalogue
    tag_lines = []
    for tag, label in tag_catalogue.items():
        tag_lines.append(f"  {tag} — {label}")
    tag_str = "\n".join(tag_lines) or "  (no specific trades — use @other)"

    # Format INS items
    ins_lines = []
    for i, item in enumerate(ins_items, 1):
        desc    = item.get("description", "")
        qty     = item.get("quantity") or item.get("qty") or ""
        unit    = item.get("unit", "")
        rcv     = item.get("rcv") or item.get("total") or 0
        section = item.get("section", "")
        ins_lines.append(f"{i}. [{section}] {desc} — {qty} {unit} — ${rcv}")

    # Format supplement items
    supp_lines = []
    for i, item in enumerate(supp_items, 1):
        desc    = item.get("description", "")
        qty     = item.get("qty", "")
        unit    = item.get("unit", "")
        total   = item.get("total") or 0
        section = item.get("section", "") or ""
        is_bid  = item.get("is_bid", False)
        tag_hint = f" [bid:{item.get('trade','')}]" if is_bid else ""
        supp_lines.append(f"{i}. [{section}] {desc}{tag_hint} — {qty} {unit} — ${total:.2f}")

    prompt = ATTRIBUTION_PROMPT.format(
        tag_catalogue=tag_str,
        project_context=project_context,
        ins_items="\n".join(ins_lines) if ins_lines else "(no INS items)",
        supp_items="\n".join(supp_lines) if supp_lines else "(no supplement items)",
    )

    if verbose:
        print(f"[flow_package] AI attribution: {len(ins_items)} INS + {len(supp_items)} supp items → {len(tag_catalogue)} tags")

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(raw)
    except Exception as e:
        print(f"[flow_package] ⚠️  AI attribution failed: {e} — falling back to section-based")
        return _fallback_attribution(ins_items, supp_items, tag_catalogue)

    # Convert list → dict keyed by id
    ins_map  = {entry["id"]: entry["tag"] for entry in result.get("ins", [])}
    supp_map = {entry["id"]: entry["tag"] for entry in result.get("supp", [])}

    if verbose:
        print(f"[flow_package] Attribution done: {len(ins_map)} INS, {len(supp_map)} supp")

    return {"ins": ins_map, "supp": supp_map}


def _fallback_attribution(ins_items: list, supp_items: list, tag_catalogue: dict) -> dict:
    """Section-based fallback if AI call fails."""
    from data_pipeline import INS_SECTION_TO_TAG, ESTIMATE_SECTION_TO_TAG, _section_name_to_tag

    def _map(items, mapping):
        result = {}
        for i, item in enumerate(items, 1):
            section = item.get("section", "") or ""
            tag, _ = _section_name_to_tag(section, mapping)
            result[i] = tag or "@other"
        return result

    return {
        "ins":  _map(ins_items,  INS_SECTION_TO_TAG),
        "supp": _map(supp_items, ESTIMATE_SECTION_TO_TAG),
    }


# ---------------------------------------------------------------------------
# Sum attributed items per @tag
# ---------------------------------------------------------------------------

def sum_by_tag(items: list, attribution: dict, source: str) -> dict:
    """
    Sum item values per @tag using attribution map.

    For INS items:   sums rcv, depreciation, non_recoverable_depreciation, o_and_p
    For supp items:  sums total (retail), op

    Returns:
    {
        "@shingle_roof": {"rcv": 0, "dep": 0, "nrd": 0, "ins_op": 0},        # INS
        "@shingle_roof": {"retail": 0, "op": 0, "remove": 0, "replace": 0},  # supp
    }
    """
    totals: dict[str, dict] = {}

    for i, item in enumerate(items, 1):
        tag = attribution.get(i)
        if not tag or tag == "__op__":
            continue  # skip O&P lines and unattributed

        if tag not in totals:
            if source == "ins":
                totals[tag] = {"rcv": 0.0, "dep": 0.0, "nrd": 0.0, "ins_op": 0.0}
            else:
                totals[tag] = {"retail": 0.0, "op": 0.0, "remove": 0.0, "replace": 0.0}

        if source == "ins":
            totals[tag]["rcv"]    += float(item.get("rcv") or item.get("total") or 0)
            totals[tag]["dep"]    += float(item.get("depreciation") or 0)
            totals[tag]["nrd"]    += float(item.get("non_recoverable_depreciation") or 0)
            totals[tag]["ins_op"] += float(item.get("o_and_p") or 0)
        else:
            totals[tag]["retail"]  += float(item.get("total") or 0)
            totals[tag]["op"]      += float(item.get("op") or 0)
            totals[tag]["remove"]  += float(item.get("remove") or 0)
            totals[tag]["replace"] += float(item.get("replace") or 0)

    # Round everything
    for tag_data in totals.values():
        for k in tag_data:
            tag_data[k] = round(tag_data[k], 2)

    return totals


# ---------------------------------------------------------------------------
# Supplement notes generation
# ---------------------------------------------------------------------------

def _generate_supplement_notes_batch(trade_data: list[dict],
                                      supp_context: list, momentum_context: list) -> dict[str, str]:
    """
    Generate supplement_notes for ALL trades in a single AI call.
    
    trade_data: list of {"key": str, "tag": str, "scope": str, "retail": float,
                         "ins_rcv": float, "ins_nrd": float, "ins_op": float}
    Returns: {"key": "note text", ...}
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    lines = []
    for t in trade_data:
        delta = round(t["retail"] - t["ins_rcv"], 2) if t["ins_rcv"] else None
        lines.append(
            f"- KEY={t['key']} | {t['tag']} ({t['scope']}) | "
            f"Ours: ${t['retail']:,.2f} | INS: ${t['ins_rcv']:,.2f} | "
            f"Delta: {'${:+,.2f}'.format(delta) if delta is not None else '?'} | "
            f"O&P: {'yes' if t['ins_op'] else 'NO'} | "
            f"NRD: ${t['ins_nrd']:,.2f}{'⚠️' if t['ins_nrd'] else ''}"
        )

    context_str = " | ".join((supp_context + momentum_context)[:3]) or "none"

    prompt = f"""Write a 1-2 sentence supplement_notes for EACH Flow bid card below. Team-facing, specific.

Context: {context_str}

Trades:
{chr(10).join(lines)}

Examples: "INS short $1,200. Not paying O&P." / "Approved in full." / "NRD $450 — flag for rebuttal."

Return ONLY valid JSON — a dict mapping each KEY to its note text:
{{"key1": "note", "key2": "note", ...}}"""

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)
    except Exception as e:
        print(f"[flow_package] ⚠️  batch supplement_notes failed: {e} — using fallback")
        result = {}
        for t in trade_data:
            parts = []
            delta = round(t["retail"] - t["ins_rcv"], 2) if t["ins_rcv"] else None
            if delta and abs(delta) > 10:
                parts.append(f"INS {'short' if delta > 0 else 'over'} ${abs(delta):,.2f}.")
            if not t["ins_op"] and t["retail"] > 0:
                parts.append("Not paying O&P.")
            if t["ins_nrd"]:
                parts.append(f"NRD ${t['ins_nrd']:,.2f} — flag for rebuttal.")
            result[t["key"]] = " ".join(parts) or "Supplement submitted."
        return result


# ---------------------------------------------------------------------------
# Core package builder
# ---------------------------------------------------------------------------

def generate_flow_package(estimate: dict, pipeline_data: dict,
                           verbose: bool = False) -> dict:
    """
    Build the Clarity Flow card update package.

    1. AI attributes ALL INS + estimate line items to @tags
    2. Sums per @tag for both INS and supplement
    3. Merges with bid data (sub bids already have @tags)
    4. Builds Clarity JSON per trade card
    """
    project_id      = pipeline_data.get("project_id")
    project_name    = pipeline_data.get("project", {}).get("name", "")
    action_trackers = pipeline_data.get("action_trackers", [])
    bids            = pipeline_data.get("bids", [])
    ins_data        = pipeline_data.get("ins_data", {})
    notes           = pipeline_data.get("notes", {})

    cards_by_type      = _get_cards_by_type(action_trackers)
    existing_bid_cards = cards_by_type["bid"]

    ifc_context  = " | ".join(notes.get("ifc", [])[:2])
    supp_context = notes.get("supplement", [])
    mom_context  = notes.get("momentum", [])

    # ── Collect all items ─────────────────────────────────────────────────────
    ins_items  = ins_data.get("items", [])
    supp_items = []
    for section in estimate.get("sections", []):
        sec_name = section.get("name", "")
        for item in section.get("line_items", []):
            enriched = dict(item)
            enriched["section"] = sec_name
            # Bid items already have a trade tag — tag them so AI knows
            if item.get("is_bid") and item.get("sub_name"):
                # find matching bid to get trade tag
                for bid in bids:
                    if bid.get("sub_name", "").lower() in item.get("description", "").lower():
                        enriched["trade"] = bid.get("trade", "@other")
                        break
            supp_items.append(enriched)

    # ── Build tag catalogue from this project's Flow cards + bids ─────────────
    tag_catalogue = _build_tag_catalogue(existing_bid_cards, bids)

    # Ensure at minimum @shingle_roof is in the catalogue (every roofing project)
    if "@shingle_roof" not in tag_catalogue:
        tag_catalogue["@shingle_roof"] = "Shingle Roof"

    print(f"[flow_package] Trades for this project: {list(tag_catalogue.keys())}")

    # ── AI attribution pass ───────────────────────────────────────────────────
    print(f"[flow_package] Running AI attribution ({len(ins_items)} INS + {len(supp_items)} supp items)...")
    attribution = ai_attribute_items(
        ins_items, supp_items, tag_catalogue,
        project_context=ifc_context,
        verbose=verbose,
    )

    # ── Sum per @tag ──────────────────────────────────────────────────────────
    ins_by_tag  = sum_by_tag(ins_items,  attribution["ins"],  source="ins")
    supp_by_tag = sum_by_tag(supp_items, attribution["supp"], source="supp")

    print(f"[flow_package] INS  by tag: {list(ins_by_tag.keys())}")
    print(f"[flow_package] Supp by tag: {list(supp_by_tag.keys())}")

    # ── Build cards ───────────────────────────────────────────────────────────
    cards    = []
    warnings = []
    skipped  = []

    # All tags we need to produce cards for: supp tags + INS-only tags + bid tags
    all_tags = set(supp_by_tag.keys()) | set(ins_by_tag.keys()) | {b.get("trade") for b in bids if b.get("trade")}
    all_tags.discard("__op__")
    all_tags.discard(None)

    # Track @other cards — each scope gets its own card
    other_scope_seen: set = set()

    # ── Phase 1: Collect trade data for all cards ─────────────────────────────
    # We collect everything first so we can batch the supplement_notes AI call
    card_drafts: list[dict] = []

    for tag in sorted(all_tags):
        scopes_for_tag = []
        if tag in ("@other", "@shed", "@other_structure"):
            for bid in bids:
                if bid.get("trade") == tag:
                    scopes_for_tag.append(bid.get("scope", ""))
            for card in existing_bid_cards:
                if card.get("tag") == tag:
                    content = card.get("content") or card.get("description") or ""
                    if content and content not in scopes_for_tag:
                        scopes_for_tag.append(content)
            if not scopes_for_tag:
                scopes_for_tag = [""]
        else:
            scopes_for_tag = [""]

        for scope in scopes_for_tag:
            scope_key = (tag, scope.lower()[:40])
            if scope_key in other_scope_seen:
                continue
            other_scope_seen.add(scope_key)

            matching_bid = next(
                (b for b in bids if b.get("trade") == tag and
                 (not scope or scope.lower() in (b.get("scope") or "").lower())),
                None
            )

            supp = supp_by_tag.get(tag, {})
            retail = supp.get("retail", 0.0)
            op     = supp.get("op", 0.0)

            if matching_bid:
                bid_retail = float(matching_bid.get("retail_total") or 0)
                if bid_retail > 0:
                    retail = bid_retail
                    op = _op_from_retail(retail)
                wholesale = float(matching_bid.get("wholesale_total") or 0)
            else:
                wholesale = 0.0

            ins = ins_by_tag.get(tag, {})
            ins_rcv = ins.get("rcv", 0.0)
            ins_dep = ins.get("dep", 0.0)
            ins_nrd = ins.get("nrd", 0.0)
            ins_op  = ins.get("ins_op", 0.0)

            existing_card = _find_bid_card(existing_bid_cards, tag, scope)
            action       = "update" if existing_card else "create"
            flow_card_id = existing_card["id"] if existing_card else None

            how_far_off = round(retail - ins_rcv, 2) if ins_rcv and retail else None
            card_key = f"{tag}|{scope[:40]}"

            card_drafts.append({
                "key": card_key, "tag": tag, "scope": scope,
                "retail": retail, "op": op, "wholesale": wholesale,
                "ins_rcv": ins_rcv, "ins_dep": ins_dep, "ins_nrd": ins_nrd, "ins_op": ins_op,
                "action": action, "flow_card_id": flow_card_id, "how_far_off": how_far_off,
            })

    # ── Phase 2: Batch supplement notes (single AI call) ──────────────────────
    print(f"[flow_package] Generating supplement notes for {len(card_drafts)} trades (batched)...")
    notes_input = [
        {"key": d["key"], "tag": d["tag"],
         "scope": d["scope"] or d["tag"].lstrip("@").replace("_", " ").title(),
         "retail": d["retail"], "ins_rcv": d["ins_rcv"],
         "ins_nrd": d["ins_nrd"], "ins_op": d["ins_op"]}
        for d in card_drafts
    ]
    notes_map = _generate_supplement_notes_batch(notes_input, supp_context, mom_context)

    # ── Phase 3: Build cards ──────────────────────────────────────────────────
    for d in card_drafts:
        # Match by exact key first, then try tag-only (AI may strip the pipe+scope)
        supp_note = (notes_map.get(d["key"])
                     or notes_map.get(d["tag"])
                     or notes_map.get(d["tag"].lstrip("@"))
                     or "Supplement submitted.")

        payload: dict = {}
        if d["retail"]:
            payload["retail_exactimate_bid"]   = d["retail"]
            payload["op_from_ifc_supplement"]  = d["op"]
        if d["wholesale"]:
            payload["original_sub_bid_price"]  = d["wholesale"]
        if d["ins_rcv"]:
            payload["latest_rcv_rcv"]          = d["ins_rcv"]
        if d["ins_op"]:
            payload["latest_rcv_op"]           = d["ins_op"]
        payload["latest_rcv_non_recoverable_depreciation"] = d["ins_nrd"]
        if d["how_far_off"] is not None:
            payload["how_far_are_we_off"]      = d["how_far_off"]
        if supp_note:
            payload["supplement_notes"]        = supp_note

        if d["ins_nrd"] > 0:
            warnings.append(f"{d['tag']}: ⚠️ NRD ${d['ins_nrd']:,.2f} — flag for rebuttal")

        card = {
            "action":       d["action"],
            "project_id":   project_id,
            "action_type":  "bid",
            "tag":          d["tag"],
            "flow_card_id": d["flow_card_id"],
            "payload":      payload,
        }
        if d["scope"] and d["tag"] in ("@other", "@shed", "@other_structure"):
            card["disambiguator"] = d["scope"]

        cards.append(card)
        status = "✅ update" if d["action"] == "update" else "🆕 create"
        print(f"[flow_package] {status} {d['tag']}{' (' + d['scope'] + ')' if d['scope'] else ''} — "
              f"retail ${d['retail']:,.2f} | INS ${d['ins_rcv']:,.2f} | NRD ${d['ins_nrd']:,.2f}")

    # ── Pricelist card ─────────────────────────────────────────────────────────
    our_pl  = estimate.get("price_list", "")
    ins_pl  = ins_data.get("price_list") or ins_data.get("totals", {}).get("price_list") or ""
    existing_pl = cards_by_type["pricelist"]
    if our_pl or ins_pl:
        pl_payload = {}
        if our_pl:
            pl_payload["our_price_list"] = our_pl
        if ins_pl:
            pl_payload["ins_price_list"] = ins_pl
        if pl_payload:
            cards.append({
                "action":       "update" if existing_pl else "create",
                "project_id":   project_id,
                "action_type":  "pricelist",
                "tag":          None,
                "flow_card_id": existing_pl["id"] if existing_pl else None,
                "payload":      pl_payload,
            })

    package = {
        "project_id":   project_id,
        "project_name": project_name,
        "rcv_total":    estimate.get("rcv_total", 0),
        "cards":        cards,
        "warnings":     warnings,
        "skipped":      skipped,
    }
    return package


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_flow_summary(package: dict):
    print("\n" + "=" * 65)
    print("📋 FLOW CARD PACKAGE — CLARITY HANDOFF")
    print(f"   Project:  {package['project_name']} (ID: {package['project_id']})")
    print(f"   RCV:      ${package['rcv_total']:,.2f}")
    n_up = sum(1 for c in package["cards"] if c["action"] == "update")
    n_cr = sum(1 for c in package["cards"] if c["action"] == "create")
    print(f"   Cards:    {len(package['cards'])} ({n_up} update, {n_cr} create)")
    print("=" * 65)

    for c in package["cards"]:
        atype  = c["action_type"]
        tag    = c.get("tag") or f"[{atype}]"
        scope  = c.get("disambiguator", "")
        action = c["action"].upper()
        p      = c.get("payload", {})

        print(f"\n  [{action}] {tag}{' — ' + scope if scope else ''}")
        if atype == "bid":
            retail = p.get("retail_exactimate_bid", 0) or 0
            op     = p.get("op_from_ifc_supplement", 0) or 0
            ins    = p.get("latest_rcv_rcv", 0) or 0
            nrd    = p.get("latest_rcv_non_recoverable_depreciation", 0) or 0
            off    = p.get("how_far_are_we_off")
            print(f"     Our request:  ${retail:>12,.2f}  (O&P: ${op:,.2f})")
            if ins:
                print(f"     INS paying:   ${ins:>12,.2f}")
            if off is not None:
                print(f"     Delta:        ${off:>+12,.2f}  {'⚠️' if abs(off) > 100 else ''}")
            if nrd:
                print(f"     ⚠️  NRD:      ${nrd:>12,.2f}")
            note = p.get("supplement_notes", "")
            if note:
                print(f"     Note: {note}")
        elif atype == "pricelist":
            print(f"     Our: {p.get('our_price_list', '')}")
            print(f"     INS: {p.get('ins_price_list', '')}")

    warnings = package.get("warnings", [])
    if warnings:
        print(f"\n  ⚠️  {len(warnings)} WARNING(S):")
        for w in warnings:
            print(f"     - {w}")

    print("\n" + "=" * 65)
    print("  Hand the JSON to Clarity to execute.")
    print("=" * 65 + "\n")


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_flow_package(package: dict, output_dir: Path, lastname: str) -> tuple:
    """
    Save two files:
    - {lastname}_flow_package.json  → full debug JSON (internal)
    - {lastname}_clarity.json       → cards only, ready to hand to Clarity

    Returns (full_path, clarity_path)
    """
    full_path = output_dir / f"{lastname}_flow_package.json"
    with open(full_path, "w") as f:
        json.dump(package, f, indent=2)

    clarity_path = output_dir / f"{lastname}_clarity.json"
    with open(clarity_path, "w") as f:
        json.dump(package["cards"], f, indent=2)

    return full_path, clarity_path
