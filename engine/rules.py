"""Stages 3, 4, 5, 6: Pure deterministic Python AP rules and decision engine."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .schemas import ExtractedInvoice, StageResult

try:
    from ..data.db import add_run_record, update_po_billed
except ImportError:
    from data.db import add_run_record, update_po_billed


def validate_vendor_and_duplicates(
    extracted: ExtractedInvoice,
    file_hash: str,
    store_state: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], StageResult]:
    """Stage 3: Vendor verification and 2-tier duplicate gate.

    Returns:
        matched_vendor: Vendor master record if approved, else None.
        duplicate_info: Details of any duplicate / near-duplicate match.
        stage_result: StageResult object for UI visualization.
    """
    vendors = store_state.get("vendors", [])
    run_history = store_state.get("run_history", [])
    policy_rules = store_state.get("policy_rules", {})
    duplicate_window_days = int(policy_rules.get("duplicate_window_days", 14))

    # 1. Vendor Lookup (case-insensitive fuzzy substring)
    matched_vendor: Optional[Dict[str, Any]] = None
    extracted_vendor_clean = (extracted.vendor_name or "").strip().lower()

    if extracted_vendor_clean:
        for v in vendors:
            v_name = v.get("name", "").strip().lower()
            if extracted_vendor_clean in v_name or v_name in extracted_vendor_clean:
                matched_vendor = v
                break

    vendor_approved = bool(matched_vendor and matched_vendor.get("status") == "APPROVED")

    # 2. Duplicate Detection (Tier 1: exact SHA256; Tier 2: near-duplicate)
    exact_duplicate: Optional[Dict[str, Any]] = None
    near_duplicate: Optional[Dict[str, Any]] = None

    for record in run_history:
        # Tier 1: Exact File Hash match
        if record.get("file_hash") == file_hash:
            exact_duplicate = record
            break

        # Tier 2: Near-duplicate check
        # Same vendor + identical total amount within duplicate_window_days
        rec_vendor = (record.get("vendor_name") or "").strip().lower()
        same_vendor = False
        if extracted_vendor_clean and rec_vendor:
            same_vendor = (extracted_vendor_clean in rec_vendor or rec_vendor in extracted_vendor_clean)

        rec_total = float(record.get("total_amount") or 0.0)
        curr_total = float(extracted.total_amount or 0.0)
        same_amount = abs(rec_total - curr_total) < 0.01 and curr_total > 0

        if same_vendor and same_amount:
            # Check date proximity
            rec_date_str = record.get("invoice_date")
            curr_date_str = extracted.invoice_date

            date_in_window = True
            if rec_date_str and curr_date_str:
                try:
                    d_rec = datetime.strptime(rec_date_str, "%Y-%m-%d")
                    d_curr = datetime.strptime(curr_date_str, "%Y-%m-%d")
                    delta_days = abs((d_curr - d_rec).days)
                    date_in_window = (delta_days <= duplicate_window_days)
                except ValueError:
                    date_in_window = True

            if date_in_window:
                near_duplicate = record
                break

    duplicate_info = {
        "is_exact_duplicate": bool(exact_duplicate),
        "is_near_duplicate": bool(near_duplicate),
        "duplicate_record": exact_duplicate or near_duplicate,
    }

    # Determine Stage 3 status & summary
    if exact_duplicate:
        status = "failed"
        summary = (
            f"FAILED: Exact duplicate file detected (Matches prior processed invoice "
            f"'{exact_duplicate.get('invoice_number')}')"
        )
    elif near_duplicate:
        status = "failed"
        summary = (
            f"FAILED: Suspected near-duplicate detected (Identical amount ${extracted.total_amount:,.2f} "
            f"from {near_duplicate.get('vendor_name')} matching prior invoice '{near_duplicate.get('invoice_number')}')"
        )
    elif not vendor_approved:
        status = "failed"
        summary = f"FAILED: Vendor '{extracted.vendor_name or 'Unknown'}' is not an approved vendor"
    else:
        status = "passed"
        summary = f"PASSED: Approved vendor '{matched_vendor['name']}' ({matched_vendor['vendor_id']}), no duplicates detected"

    stage_result = StageResult(
        stage_number=3,
        name="Vendor Master & Duplicate Gate",
        status=status,
        summary=summary,
        details={
            "vendor_approved": vendor_approved,
            "matched_vendor": matched_vendor,
            "duplicate_info": duplicate_info,
        },
    )

    return matched_vendor, duplicate_info, stage_result


def match_po_and_spend(
    extracted: ExtractedInvoice,
    matched_vendor: Optional[Dict[str, Any]],
    store_state: Dict[str, Any],
) -> Tuple[Dict[str, Any], StageResult]:
    """Stage 4: PO matching (explicit & implicit) and cumulative spend calculation."""
    purchase_orders = store_state.get("purchase_orders", [])
    extracted_po = (extracted.po_reference or "").strip().upper()
    vendor_name_clean = (matched_vendor.get("name") if matched_vendor else (extracted.vendor_name or "")).strip().lower()

    matched_po: Optional[Dict[str, Any]] = None
    match_type = "none"

    # 1. Explicit PO match
    if extracted_po and extracted_po != "N/A":
        for po in purchase_orders:
            if po.get("po_number", "").strip().upper() == extracted_po:
                matched_po = po
                match_type = "explicit"
                break

    # 2. Implicit PO match if po_reference was missing
    if not matched_po:
        candidate_pos = [
            po for po in purchase_orders
            if vendor_name_clean in po.get("vendor_name", "").lower()
            or po.get("vendor_name", "").lower() in vendor_name_clean
        ]

        # Score candidates based on line item description overlap and amount proximity
        best_candidate = None
        best_overlap_score = 0

        # Collect invoice keywords from line items
        inv_desc_words = set()
        for item in extracted.line_items:
            for w in item.description.lower().split():
                if len(w) > 3:
                    inv_desc_words.add(w)

        for candidate in candidate_pos:
            po_desc_words = {w for w in candidate.get("description", "").lower().split() if len(w) > 3}
            overlap = len(inv_desc_words.intersection(po_desc_words))
            amt_match = abs(float(candidate.get("total_amount", 0.0)) - float(extracted.total_amount or 0.0)) < 1.0

            if overlap > best_overlap_score or (overlap == best_overlap_score and amt_match):
                best_overlap_score = overlap
                best_candidate = candidate

        if best_candidate and (best_overlap_score >= 2 or abs(float(best_candidate.get("total_amount", 0.0)) - float(extracted.total_amount or 0.0)) < 1.0):
            matched_po = best_candidate
            match_type = "implicit"

    # 3. Spend Metrics Calculation
    if matched_po:
        po_number = matched_po.get("po_number", "")
        po_total = float(matched_po.get("total_amount", 0.0))
        previously_billed = float(matched_po.get("previously_billed", 0.0))
        current_amount = float(extracted.total_amount or 0.0)
        cumulative_total = round(previously_billed + current_amount, 2)
        remaining_balance = round(po_total - cumulative_total, 2)
    else:
        po_number = None
        po_total = 0.0
        previously_billed = 0.0
        current_amount = float(extracted.total_amount or 0.0)
        cumulative_total = current_amount
        remaining_balance = 0.0

    po_details = {
        "matched_po": matched_po,
        "match_type": match_type,
        "po_number": po_number,
        "po_total": po_total,
        "previously_billed": previously_billed,
        "current_invoice_amount": current_amount,
        "cumulative_total": cumulative_total,
        "remaining_balance": remaining_balance,
    }

    # Stage 4 status & summary
    if match_type == "explicit":
        status = "passed"
        summary = (
            f"PASSED: Explicit PO match '{po_number}' | Billed: ${previously_billed:,.2f} + Current: ${current_amount:,.2f} "
            f"= Cumulative: ${cumulative_total:,.2f} / Budget: ${po_total:,.2f}"
        )
    elif match_type == "implicit":
        status = "warning"
        summary = (
            f"WARNING: Implicit PO match to '{po_number}' ({matched_po.get('description', '')}) -- requires human confirmation"
        )
    else:
        status = "failed"
        summary = f"FAILED: No matching Purchase Order found for vendor '{extracted.vendor_name or 'Unknown'}'"

    stage_result = StageResult(
        stage_number=4,
        name="Purchase Order Matching & Cumulative Spend",
        status=status,
        summary=summary,
        details=po_details,
    )

    return po_details, stage_result


def validate_math_and_tolerance(
    extracted: ExtractedInvoice,
    po_details: Dict[str, Any],
    store_state: Dict[str, Any],
) -> Tuple[Dict[str, Any], StageResult]:
    """Stage 5: Deterministic math validation and policy tolerance check."""
    subtotal = float(extracted.subtotal or 0.0)
    tax_amount = float(extracted.tax_amount or 0.0)
    total = float(extracted.total_amount or 0.0)
    tax_mode = extracted.tax_mode

    # 1. Internal Math Validation
    if tax_mode == "separated":
        math_diff = abs((subtotal + tax_amount) - total)
        math_valid = math_diff <= 0.05
        math_summary = f"Subtotal (${subtotal:,.2f}) + Tax (${tax_amount:,.2f}) = ${subtotal + tax_amount:,.2f} vs Total (${total:,.2f})"
    elif tax_mode == "embedded":
        line_sum = sum(item.amount for item in extracted.line_items) if extracted.line_items else total
        math_diff = abs(line_sum - total)
        math_valid = math_diff <= 0.05
        math_summary = f"Sum of line items (${line_sum:,.2f}) matches Total (${total:,.2f}) [Tax-inclusive]"
    else:
        line_sum = sum(item.amount for item in extracted.line_items) if extracted.line_items else total
        math_diff = abs(line_sum - total)
        math_valid = math_diff <= 0.05 or abs((subtotal + tax_amount) - total) <= 0.05
        math_summary = f"Line totals (${line_sum:,.2f}) evaluated against Total (${total:,.2f})"

    # 2. Cumulative Spend vs PO Tolerance Check
    matched_po = po_details.get("matched_po")
    po_total = float(po_details.get("po_total", 0.0))
    cumulative_total = float(po_details.get("cumulative_total", total))

    policy = store_state.get("policy_rules", {})
    tolerance_pct = float(policy.get("tolerance_percent", 2.0))
    tolerance_max_amt = float(policy.get("tolerance_max_amount", 250.0))

    if matched_po and po_total > 0:
        variance_amount = round(cumulative_total - po_total, 2)
        variance_pct = round((variance_amount / po_total) * 100, 2)
    else:
        variance_amount = 0.0
        variance_pct = 0.0

    if variance_amount <= 0.0:
        variance_status = "passed"
        variance_note = f"Cumulative spend (${cumulative_total:,.2f}) within PO limit (${po_total:,.2f})"
    elif variance_pct <= tolerance_pct and variance_amount <= tolerance_max_amt:
        variance_status = "passed"
        variance_note = f"Within tolerance (+{variance_pct:.1f}% / +${variance_amount:,.2f} <= {tolerance_pct}% / ${tolerance_max_amt:,.2f})"
    else:
        variance_status = "failed"
        variance_note = f"PO Over-Utilization / Exceeds Tolerance (+{variance_pct:.1f}% / +${variance_amount:,.2f} > {tolerance_pct}% / ${tolerance_max_amt:,.2f})"

    math_details = {
        "math_valid": math_valid,
        "math_summary": math_summary,
        "variance_amount": variance_amount,
        "variance_pct": variance_pct,
        "variance_status": variance_status,
        "variance_note": variance_note,
    }

    # Determine Stage 5 status & summary
    if not math_valid:
        status = "failed"
        summary = f"FAILED: Arithmetic mismatch - {math_summary}"
    elif variance_status == "failed":
        status = "failed"
        summary = f"FAILED: {variance_note}"
    else:
        status = "passed"
        summary = f"PASSED: Math verified ({math_summary}). {variance_note}"

    stage_result = StageResult(
        stage_number=5,
        name="Deterministic Math & Tolerance Validation",
        status=status,
        summary=summary,
        details=math_details,
    )

    return math_details, stage_result


def synthesize_decision(
    stages: List[StageResult],
    extracted: ExtractedInvoice,
    matched_vendor: Optional[Dict[str, Any]],
    po_details: Dict[str, Any],
    math_details: Dict[str, Any],
    duplicate_info: Dict[str, Any],
    file_hash: str,
    filename: str = "",
) -> Tuple[str, List[str], Dict[str, Any], StageResult]:
    """Stage 6: Decision synthesis and structured ERP / notification action generation."""
    reasoning: List[str] = []

    # 1. Check for Hard Rejection (Duplicates or Unapproved Vendor)
    is_duplicate = duplicate_info.get("is_exact_duplicate") or duplicate_info.get("is_near_duplicate")
    vendor_approved = bool(matched_vendor and matched_vendor.get("status") == "APPROVED")

    if is_duplicate:
        decision = "REJECTED"
        dup_rec = duplicate_info.get("duplicate_record", {})
        if duplicate_info.get("is_exact_duplicate"):
            reasoning.append(f"Hard Rejection: Exact duplicate file hash detected matching prior invoice '{dup_rec.get('invoice_number')}'.")
        else:
            reasoning.append(
                f"Hard Rejection: Suspected near-duplicate billing. Vendor '{extracted.vendor_name}' submitted identical total "
                f"${extracted.total_amount:,.2f} matching prior processed invoice '{dup_rec.get('invoice_number')}' within 14 days."
            )
    elif not vendor_approved:
        decision = "REJECTED"
        reasoning.append(f"Hard Rejection: Vendor '{extracted.vendor_name or 'Unknown'}' is not active in the Approved Vendor Master.")

    # 2. Check for Needs Review
    else:
        review_reasons: List[str] = []

        # Missing mandatory fields
        mandatory_missing = [f for f in ["invoice_number", "invoice_date", "total_amount"] if f in extracted.missing_fields]
        if mandatory_missing:
            review_reasons.append(f"Missing mandatory invoice field(s): {', '.join(mandatory_missing)}.")

        # Implicit PO match
        if po_details.get("match_type") == "implicit":
            review_reasons.append(
                f"Implicit PO match to '{po_details.get('po_number')}' based on description and amount proximity; requires human confirmation."
            )
        elif po_details.get("match_type") == "none":
            review_reasons.append("No corresponding Purchase Order could be matched for this vendor.")

        # Arithmetic mismatch
        if not math_details.get("math_valid"):
            review_reasons.append(f"Internal calculation mismatch: {math_details.get('math_summary')}.")

        # Variance exceeds tolerance
        if math_details.get("variance_status") == "failed":
            review_reasons.append(f"Cumulative spend exceeds Purchase Order budget tolerance: {math_details.get('variance_note')}.")

        if review_reasons:
            decision = "NEEDS REVIEW"
            reasoning.extend(review_reasons)
        else:
            decision = "AUTO-APPROVED"
            reasoning.append(f"Vendor '{matched_vendor['name']}' ({matched_vendor['vendor_id']}) is verified and approved.")
            reasoning.append(f"Matched Purchase Order '{po_details.get('po_number')}' explicitly.")
            reasoning.append(f"Invoice math is verified: {math_details.get('math_summary')}.")
            reasoning.append(f"PO Cumulative Spend check: {math_details.get('variance_note')}.")
            reasoning.append("All mandatory invoice fields are complete and verified.")

    # 3. Next Action Payload Generation
    po_num = po_details.get("po_number")
    total_val = float(extracted.total_amount or 0.0)

    if decision == "AUTO-APPROVED":
        voucher_ref = f"VOUCH-2026-{extracted.invoice_number or 'GEN'}"
        next_action = {
            "action": "POST_PAYMENT_VOUCHER",
            "erp_reference": voucher_ref,
            "vendor_id": matched_vendor.get("vendor_id") if matched_vendor else "V-UNKNOWN",
            "vendor_name": matched_vendor.get("name") if matched_vendor else extracted.vendor_name,
            "invoice_number": extracted.invoice_number,
            "po_number": po_num,
            "posting_amount": total_val,
            "currency": "USD",
            "payment_terms": "Net 30",
            "gl_account": "2100-ACCOUNTS-PAYABLE",
            "status": "QUEUED_FOR_DISBURSEMENT",
        }
        # Update PO billed amount in data/store.json
        if po_num:
            update_po_billed(po_num, total_val)

    elif decision == "NEEDS REVIEW":
        next_action = {
            "action": "SEND_VENDOR_EMAIL",
            "recipient": f"billing@{extracted.vendor_name.lower().replace(' ', '')}.com" if extracted.vendor_name else "accounts@vendor.internal",
            "subject": f"Notice regarding Invoice {extracted.invoice_number or 'Reference'} - Action Required",
            "body": (
                f"Dear {extracted.vendor_name or 'Vendor'},\n\n"
                f"We are currently reviewing your invoice {extracted.invoice_number or 'submitted'}.\n"
                f"Our automated Accounts Payable system has flagged the following items requiring clarification:\n"
                + "\n".join(f"- {r}" for r in reasoning) + "\n\n"
                f"Please provide an amended invoice or confirm PO reference at your earliest convenience.\n\n"
                f"Sincerely,\nAccounts Payable Operations"
            ),
            "escalation_team": "AP_PROCUREMENT_REVIEW",
        }

    else:  # REJECTED
        next_action = {
            "action": "SEND_VENDOR_EMAIL",
            "recipient": f"billing@{extracted.vendor_name.lower().replace(' ', '')}.com" if extracted.vendor_name else "accounts@vendor.internal",
            "subject": f"REJECTION NOTICE: Invoice {extracted.invoice_number or 'Reference'}",
            "body": (
                f"Dear {extracted.vendor_name or 'Vendor'},\n\n"
                f"Your invoice {extracted.invoice_number or 'submission'} has been REJECTED by our Accounts Payable system.\n"
                f"Reason for rejection:\n"
                + "\n".join(f"- {r}" for r in reasoning) + "\n\n"
                f"No payment will be disbursed for this invoice. Please contact your procurement representative.\n\n"
                f"Sincerely,\nAccounts Payable Compliance Team"
            ),
            "escalation_team": "AP_DISPUTES_TEAM",
        }

    # 4. Save completed run record into data/store.json
    run_record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filename": filename or "invoice.pdf",
        "invoice_number": extracted.invoice_number or "UNKNOWN",
        "vendor_name": extracted.vendor_name or "Unknown Vendor",
        "invoice_date": extracted.invoice_date or datetime.now().strftime("%Y-%m-%d"),
        "total_amount": total_val,
        "po_number": po_num or "None",
        "status": decision,
        "file_hash": file_hash,
        "key_reason": reasoning[0] if reasoning else "All validation checks passed.",
        "reasoning": list(reasoning),
        "extracted_fields": extracted.model_dump(),
        "stage_summaries": [
            {
                "stage_number": s.stage_number,
                "name": s.name,
                "status": s.status,
                "summary": s.summary,
            }
            for s in stages
        ],
        "next_action": next_action,
    }
    add_run_record(run_record)

    # 5. Build Stage 6 Result
    stage_result = StageResult(
        stage_number=6,
        name="Decision Synthesis & Next Actions",
        status="passed" if decision == "AUTO-APPROVED" else ("warning" if decision == "NEEDS REVIEW" else "failed"),
        summary=f"Final Decision: {decision}. {len(reasoning)} factors evaluated.",
        details={
            "decision": decision,
            "reasoning": reasoning,
            "next_action": next_action,
        },
    )

    return decision, reasoning, next_action, stage_result
