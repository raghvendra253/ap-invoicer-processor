"""Streamlit Web Application for AP Invoice Processor."""

import io
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pymupdf
import streamlit as st
from dotenv import load_dotenv

from data.db import add_run_record, get_state, reset_db, save_state, update_po_billed
from engine.pipeline import run_invoice_pipeline
from engine.schemas import PipelineReport, StageResult

# Load environment variables
load_dotenv()

# Setup paths
BASE_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = BASE_DIR / "sample_invoices"

# Page configuration
st.set_page_config(
    page_title="AP Invoice Processor",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Helper function for currency formatting (handles negative values cleanly)
def fmt_currency(val: Optional[float]) -> str:
    """Formats numeric float into standard USD string (e.g. -$4,500.00)."""
    if val is None:
        return "$0.00"
    if val < 0:
        return f"-${abs(val):,.2f}"
    return f"${val:,.2f}"


# Custom CSS for modern enterprise styling and metric responsiveness
st.markdown(
    """
    <style>
    /* Metric Typography - Prevent truncation in 4-column layouts */
    [data-testid="stMetricValue"] {
        font-size: 1.25rem !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.85rem !important;
        color: #64748B !important;
        font-weight: 600 !important;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.8rem !important;
    }

    /* Decision Badges */
    .badge-approved {
        display: inline-block;
        background-color: #DCFCE7;
        color: #166534;
        border: 1px solid #86EFAC;
        padding: 4px 14px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.88rem;
        letter-spacing: 0.03em;
    }
    .badge-review {
        display: inline-block;
        background-color: #FEF3C7;
        color: #92400E;
        border: 1px solid #FCD34D;
        padding: 4px 14px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.88rem;
        letter-spacing: 0.03em;
    }
    .badge-rejected {
        display: inline-block;
        background-color: #FEE2E2;
        color: #991B1B;
        border: 1px solid #FCA5A5;
        padding: 4px 14px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.88rem;
        letter-spacing: 0.03em;
    }
    .badge-override {
        display: inline-block;
        background-color: #E0F2FE;
        color: #075985;
        border: 1px solid #7DD3FC;
        padding: 4px 14px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.88rem;
        letter-spacing: 0.03em;
    }

    /* Custom Cards */
    .card-box {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    .kpi-card {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_pdf_to_png_bytes(pdf_bytes: bytes, page_index: int = 0, dpi: int = 150) -> bytes:
    """Renders page 1 of a PDF into high-res PNG image bytes using PyMuPDF."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    matrix = pymupdf.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=matrix)
    return pix.tobytes("png")


def render_decision_badge_html(decision: str) -> str:
    """Returns styled HTML badge for decision status."""
    if decision == "AUTO-APPROVED":
        return '<span class="badge-approved">● AUTO-APPROVED</span>'
    elif decision == "NEEDS REVIEW":
        return '<span class="badge-review">▲ NEEDS REVIEW</span>'
    elif decision == "REJECTED":
        return '<span class="badge-rejected">✖ REJECTED</span>'
    elif decision == "MANUALLY APPROVED":
        return '<span class="badge-override">✔ MANUALLY APPROVED</span>'
    return f'<span class="badge-review">{decision}</span>'


# ==============================================================================
# SIDEBAR: Status & Admin Controls
# ==============================================================================
with st.sidebar:
    st.subheader("⚙️ System Control")

    # Read API Key from os.getenv OR st.secrets (Streamlit Cloud support)
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        try:
            groq_key = st.secrets.get("GROQ_API_KEY", "").strip()
        except Exception:
            pass

    key_configured = bool(groq_key and groq_key != "your_groq_api_key_here")
    if key_configured:
        st.success("🟢 Groq API Connected (`qwen/qwen3.8-27b`)", icon="✅")
    else:
        st.warning("🟡 Groq Key Missing (Using Deterministic Fallback)", icon="⚠️")

    # Store Stats
    current_state = get_state()
    v_count = len(current_state.get("vendors", []))
    po_count = len(current_state.get("purchase_orders", []))
    hist_count = len(current_state.get("run_history", []))

    st.markdown("---")
    st.markdown("**Local Data Store (`data/store.json`)**")
    c1, c2 = st.columns(2)
    c1.metric("Approved Vendors", v_count)
    c2.metric("Active POs", po_count)
    st.metric("Processed Invoices", hist_count)

    st.markdown("---")
    if st.button("🔄 Reset Persistence Store", help="Resets store.json back to pristine seed data"):
        reset_db()
        st.session_state.pop("current_report", None)
        st.session_state.pop("current_pdf_bytes", None)
        st.session_state.pop("current_filename", None)
        st.toast("Database reset to pristine seed state!", icon="🧹")
        st.rerun()


# ==============================================================================
# TOP-LEVEL NAVIGATION: 3 TABS
# ==============================================================================
st.title("📄 Autonomous AP Invoice Processor")
st.caption("AI-powered invoice extraction with deterministic policy compliance, 2-tier duplicate gate, and ERP integration.")

tab_run, tab_dashboard, tab_policy = st.tabs([
    "⚡ Live Invoice Run",
    "📊 AP Dashboard",
    "🗂️ Procurement & Policy",
])


# ==============================================================================
# TAB 1: LIVE INVOICE RUN
# ==============================================================================
with tab_run:
    # ---------------------------------------------------------
    # Input Section: Uploader & Quick Demo Selector
    # ---------------------------------------------------------
    st.markdown("### 1. Provide Invoice Document")

    col_up, col_demo = st.columns([1, 1], gap="medium")

    uploaded_file = None
    demo_pdf_bytes = None
    selected_filename = None

    with col_up:
        st.markdown("**Option A: Drag-and-Drop Vendor Invoice**")
        uploaded_file = st.file_uploader(
            "Upload invoice PDF",
            type=["pdf"],
            help="Upload any native digital or scanned PDF invoice.",
            label_visibility="collapsed",
        )

    with col_demo:
        st.markdown("**Option B: Quick-Load Pre-Built Scenario**")
        sample_options = {
            "01_happy_path_acme.pdf": "01. Happy Path (Acme Cloud Solutions - $4,500 Auto-Approve)",
            "02_split_po_overbill_apex.pdf": "02. Split PO Overbill (Apex Logistics - $6,200 / +8% over budget)",
            "03_scanned_missing_fields_nova.pdf": "03. Scanned Image w/ Missing Fields (Nova Creative - $3,200)",
            "04_near_duplicate_acme.pdf": "04. Near-Duplicate Check (Acme Cloud - $2,400 re-bill)",
            "05_tax_embedded_tolerance_summit.pdf": "05. Tax Embedded Tolerance (Summit Office - $5,070 / +1.4% within tol.)",
        }
        chosen_sample = st.selectbox(
            "Select test invoice scenario",
            options=list(sample_options.keys()),
            format_func=lambda x: sample_options[x],
            label_visibility="collapsed",
        )
        run_demo_btn = st.button("🚀 Run Selected Sample", use_container_width=True)

    # Determine input bytes
    pdf_bytes_to_run: Optional[bytes] = None
    filename_to_run: Optional[str] = None

    if uploaded_file is not None:
        pdf_bytes_to_run = uploaded_file.getvalue()
        filename_to_run = uploaded_file.name
    elif run_demo_btn and chosen_sample:
        sample_file_path = SAMPLE_DIR / chosen_sample
        if sample_file_path.exists():
            pdf_bytes_to_run = sample_file_path.read_bytes()
            filename_to_run = chosen_sample

    # Trigger pipeline execution when button clicked or new file selected
    if pdf_bytes_to_run is not None:
        st.session_state["current_pdf_bytes"] = pdf_bytes_to_run
        st.session_state["current_filename"] = filename_to_run
        st.session_state["trigger_run"] = True

    # Check if there is an active invoice in session state to display
    active_pdf_bytes = st.session_state.get("current_pdf_bytes")
    active_filename = st.session_state.get("current_filename")

    if active_pdf_bytes and active_filename:
        st.markdown("---")
        st.markdown("### 2. Live Execution & Document Workspace")

        col_left, col_right = st.columns([1, 1.3], gap="large")

        # ---------------------------------------------------------
        # Left Column: Document Preview via PyMuPDF PNG
        # ---------------------------------------------------------
        with col_left:
            st.markdown(f"**📄 Document Preview: `{active_filename}`**")
            try:
                png_bytes = render_pdf_to_png_bytes(active_pdf_bytes, page_index=0, dpi=160)
                st.image(png_bytes, use_container_width=True)
            except Exception as e:
                st.error(f"Error rendering PDF preview: {e}")

            f_size_kb = len(active_pdf_bytes) / 1024
            st.caption(f"File Size: {f_size_kb:.1f} KB | Rendered via PyMuPDF (160 DPI)")

        # ---------------------------------------------------------
        # Right Column: Live Stepper & Decision Output
        # ---------------------------------------------------------
        with col_right:
            # If trigger_run is True, run the pipeline with live generator updates
            if st.session_state.get("trigger_run", False):
                st.session_state["trigger_run"] = False
                completed_stages = []
                final_report: Optional[PipelineReport] = None

                with st.status("Executing 6-Stage AP Compliance Engine...", expanded=True) as status_box:
                    for update in run_invoice_pipeline(active_pdf_bytes, active_filename):
                        if isinstance(update, StageResult):
                            completed_stages.append(update)
                            icon = "✅" if update.status == "passed" else ("⚠️" if update.status == "warning" else "❌")
                            st.write(f"{icon} **Stage {update.stage_number} ({update.name})**: {update.summary}")
                            time.sleep(0.18)
                        elif isinstance(update, PipelineReport):
                            final_report = update

                    status_box.update(
                        label=f"Pipeline Completed: Decision = {final_report.decision}",
                        state="complete",
                        expanded=False,
                    )

                st.session_state["current_report"] = final_report

            # Retrieve active report
            report: Optional[PipelineReport] = st.session_state.get("current_report")

            if report:
                extracted = report.extracted_invoice
                decision = report.decision

                # -----------------------------------------------------
                # Prominent Decision Card
                # -----------------------------------------------------
                border_color = (
                    "#22C55E" if decision == "AUTO-APPROVED"
                    else ("#F59E0B" if decision == "NEEDS REVIEW"
                    else ("#3B82F6" if decision == "MANUALLY APPROVED" else "#EF4444"))
                )

                st.markdown(
                    f"""
                    <div class="card-box" style="border-left: 6px solid {border_color};">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <div>{render_decision_badge_html(decision)}</div>
                            <div style="font-size: 1.35rem; font-weight: 700; color: #0F172A;">
                                {fmt_currency(extracted.total_amount)}
                            </div>
                        </div>
                        <div style="font-size: 1.05rem; font-weight: 600; color: #1E293B;">
                            {extracted.vendor_name or "Unknown Vendor"} &nbsp;&bull;&nbsp; Inv #{extracted.invoice_number or "N/A"}
                        </div>
                        <div style="font-size: 0.85rem; color: #64748B; margin-top: 0.2rem;">
                            Date: {extracted.invoice_date or "Missing"} &nbsp;|&nbsp; 
                            PO Ref: {extracted.po_reference or "None (Implicit)"} &nbsp;|&nbsp; 
                            Tax Mode: {extracted.tax_mode.capitalize()}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # -----------------------------------------------------
                # Decision Reasoning
                # -----------------------------------------------------
                st.markdown("**Decision Factors & Policy Reasoning:**")
                for r in report.reasoning:
                    bullet_icon = "🔹"
                    if "Rejection" in r or "duplicate" in r.lower():
                        bullet_icon = "❌"
                    elif "Missing" in r or "exceeds" in r.lower() or "Implicit" in r:
                        bullet_icon = "⚠️"
                    elif "verified" in r.lower() or "matched" in r.lower() or "within" in r.lower():
                        bullet_icon = "✅"
                    st.markdown(f"{bullet_icon} {r}")

                # -----------------------------------------------------
                # Purchase Order Utilization Summary (if PO matched)
                # -----------------------------------------------------
                s4 = next((s for s in report.stages if s.stage_number == 4), None)
                if s4 and s4.details.get("matched_po"):
                    po_num = s4.details.get("po_number")
                    po_tot = s4.details.get("po_total", 0.0)
                    prev_billed = s4.details.get("previously_billed", 0.0)
                    this_inv = s4.details.get("current_invoice_amount", 0.0)
                    cumul = s4.details.get("cumulative_total", 0.0)
                    rem = s4.details.get("remaining_balance", 0.0)
                    util_pct = (cumul / po_tot) if po_tot > 0 else 0.0

                    st.markdown("---")
                    st.markdown(f"**Purchase Order Utilization ({po_num}):**")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("PO Budget", fmt_currency(po_tot))
                    m2.metric("Previously Billed", fmt_currency(prev_billed))
                    m3.metric("This Invoice", fmt_currency(this_inv))
                    m4.metric("Remaining Balance", fmt_currency(rem))

                    prog_val = min(max(util_pct, 0.0), 1.0)
                    st.progress(
                        prog_val,
                        text=f"Cumulative Spend: {fmt_currency(cumul)} of {fmt_currency(po_tot)} ({util_pct * 100:.1f}%)",
                    )

                # -----------------------------------------------------
                # Actionable Next Steps
                # -----------------------------------------------------
                st.markdown("---")
                st.markdown("**Actionable Next Steps:**")

                if decision in ("AUTO-APPROVED", "MANUALLY APPROVED"):
                    st.success("Payment voucher generated and queued for ERP disbursement.", icon="💼")
                    erp_payload = report.next_action
                    with st.expander("View ERP Payment Posting Payload (JSON)", expanded=True):
                        st.code(json.dumps(erp_payload, indent=2), language="json")

                elif decision == "NEEDS REVIEW":
                    st.warning("Action required: Invoice flagged for human review.", icon="⚠️")

                    # Human-in-the-loop override button
                    override_col, _ = st.columns([1, 1])
                    with override_col:
                        if st.button("✅ Approve & Override (Human-in-the-Loop)", type="primary", use_container_width=True):
                            # Update store record to MANUALLY APPROVED
                            st_state = get_state()
                            po_num_to_bill = s4.details.get("po_number") if s4 else None
                            total_amt = extracted.total_amount or 0.0

                            # Update run history record
                            for r_hist in st_state.get("run_history", []):
                                if r_hist.get("file_hash") == report.file_hash:
                                    r_hist["status"] = "MANUALLY APPROVED"
                                    break
                            save_state(st_state)

                            # Update PO previously billed
                            if po_num_to_bill:
                                update_po_billed(po_num_to_bill, total_amt)

                            # Update report in session state
                            report.decision = "MANUALLY APPROVED"
                            report.reasoning.append("Human-in-the-loop manual override granted by AP clerk.")
                            report.next_action = {
                                "action": "POST_PAYMENT_VOUCHER_OVERRIDE",
                                "erp_reference": f"OVERRIDE-{extracted.invoice_number}",
                                "vendor_name": extracted.vendor_name,
                                "posting_amount": total_amt,
                                "status": "APPROVED_BY_OVERRIDE",
                            }
                            st.session_state["current_report"] = report
                            st.toast("Invoice successfully approved with manual override!", icon="🎉")
                            st.rerun()

                    # Drafted Clarification Email
                    st.markdown("**Draft Vendor Clarification Email:**")
                    draft_body = report.next_action.get("body", "")
                    st.text_area(
                        "Review / edit drafted email before sending:",
                        value=draft_body,
                        height=160,
                        label_visibility="collapsed",
                    )

                elif decision == "REJECTED":
                    st.error("Invoice rejected: Compliance policy violation.", icon="🚫")
                    st.markdown("**Draft Vendor Rejection Email:**")
                    draft_body = report.next_action.get("body", "")
                    st.text_area(
                        "Review / edit drafted rejection notice:",
                        value=draft_body,
                        height=160,
                        label_visibility="collapsed",
                    )

                # -----------------------------------------------------
                # Detailed 6-Stage Audit Trail
                # -----------------------------------------------------
                st.markdown("---")
                with st.expander("🔍 View Complete 6-Stage Audit Trail"):
                    for stg in report.stages:
                        stg_icon = "✅" if stg.status == "passed" else ("⚠️" if stg.status == "warning" else "❌")
                        st.markdown(f"**{stg_icon} Stage {stg.stage_number}: {stg.name}**")
                        st.caption(stg.summary)
                        st.json(stg.details)
                        st.markdown("")


# ==============================================================================
# TAB 2: AP DASHBOARD
# ==============================================================================
with tab_dashboard:
    st.subheader("📊 Accounts Payable Operations & Audit Ledger")
    st.caption("Live operational KPIs, exception monitoring, and comprehensive invoice audit trail.")

    store_data = get_state()
    history = store_data.get("run_history", [])

    # Calculate Top KPIs
    total_runs = len(history)
    approved_runs = [r for r in history if r.get("status") in ("AUTO-APPROVED", "MANUALLY APPROVED")]
    review_runs = [r for r in history if r.get("status") == "NEEDS REVIEW"]
    rejected_runs = [r for r in history if r.get("status") == "REJECTED"]

    approval_rate = (len(approved_runs) / total_runs * 100.0) if total_runs > 0 else 0.0
    review_amount = sum(float(r.get("total_amount") or 0.0) for r in review_runs)
    rejected_amount = sum(float(r.get("total_amount") or 0.0) for r in rejected_runs)

    # Top KPI Row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Processed", str(total_runs), help="Total invoice documents evaluated by the pipeline")
    k2.metric("Approval Rate", f"{approval_rate:.1f}%", delta=f"{len(approved_runs)} approved")
    k3.metric("Flagged for Review", f"{len(review_runs)} ({fmt_currency(review_amount)})", delta="Exceptions", delta_color="inverse")
    k4.metric("Blocked / Rejected", f"{len(rejected_runs)} ({fmt_currency(rejected_amount)})", delta="Policy violations", delta_color="inverse")

    st.markdown("---")

    # Filterable Run History Table
    st.markdown("#### Processed Invoices Ledger")
    status_filter = st.radio(
        "Filter by decision status:",
        options=["All", "AUTO-APPROVED", "MANUALLY APPROVED", "NEEDS REVIEW", "REJECTED"],
        horizontal=True,
    )

    filtered_history = history
    if status_filter != "All":
        filtered_history = [r for r in history if r.get("status") == status_filter]

    # Build clean DataFrame
    table_rows = []
    for r in filtered_history:
        table_rows.append({
            "Timestamp": r.get("timestamp") or r.get("invoice_date", "N/A"),
            "Filename": r.get("filename") or "uploaded_invoice.pdf",
            "Vendor": r.get("vendor_name", "Unknown"),
            "Invoice #": r.get("invoice_number", "N/A"),
            "PO #": r.get("po_number") or "None",
            "Total Amount": fmt_currency(float(r.get("total_amount") or 0.0)),
            "Decision": r.get("status", "UNKNOWN"),
            "Key Reason": r.get("key_reason") or (r.get("reasoning", ["N/A"])[0] if r.get("reasoning") else "N/A"),
        })

    if table_rows:
        df_ledger = pd.DataFrame(table_rows)
        st.dataframe(df_ledger, use_container_width=True, hide_index=True)
    else:
        st.info("No invoice records match the selected filter.")

    st.markdown("---")

    # Audit Trail Inspector
    st.markdown("#### 🔍 Historical Run Audit Inspector")
    if history:
        # Create selectbox mapping
        def format_run_option(idx: int) -> str:
            rec = history[idx]
            inv = rec.get("invoice_number", "N/A")
            vnd = rec.get("vendor_name", "Vendor")
            amt = fmt_currency(float(rec.get("total_amount") or 0.0))
            stat = rec.get("status", "N/A")
            return f"Run #{idx + 1}: {vnd} | Inv {inv} | {amt} -> {stat}"

        selected_idx = st.selectbox(
            "Select processed invoice to audit in detail:",
            options=range(len(history)),
            format_func=format_run_option,
        )

        selected_rec = history[selected_idx]
        audit_col1, audit_col2 = st.columns([1, 1], gap="medium")

        with audit_col1:
            st.markdown("**Decision & Policy Factors:**")
            st.markdown(f"**Status:** {render_decision_badge_html(selected_rec.get('status', ''))}", unsafe_allow_html=True)
            reasons = selected_rec.get("reasoning", [selected_rec.get("key_reason", "No details")])
            for r in reasons:
                st.markdown(f"- {r}")

            st.markdown(f"**File Hash (SHA-256):** `{selected_rec.get('file_hash', 'N/A')}`")

            stage_summaries = selected_rec.get("stage_summaries", [])
            if stage_summaries:
                st.markdown("**Stage Outcomes:**")
                for stg in stage_summaries:
                    s_icon = "✅" if stg.get("status") == "passed" else ("⚠️" if stg.get("status") == "warning" else "❌")
                    st.write(f"{s_icon} **Stage {stg.get('stage_number')} ({stg.get('name')})**: {stg.get('summary')}")

        with audit_col2:
            st.markdown("**Extracted Fields Data:**")
            extracted_data = selected_rec.get("extracted_fields")
            if extracted_data:
                st.json(extracted_data)
            else:
                st.json({
                    "vendor_name": selected_rec.get("vendor_name"),
                    "invoice_number": selected_rec.get("invoice_number"),
                    "invoice_date": selected_rec.get("invoice_date"),
                    "total_amount": selected_rec.get("total_amount"),
                    "po_number": selected_rec.get("po_number"),
                })

        # Human Review Action Box for ANY run whose verdict contains 'REVIEW'
        rec_verdict = str(selected_rec.get("status") or selected_rec.get("decision") or "")
        if "review" in rec_verdict.lower():
            st.markdown("---")
            st.markdown("### ✍️ Human Review Action (Exception Resolution)")
            st.warning(
                f"This invoice is currently in **{rec_verdict}** status and requires human evaluation.",
                icon="⚠️",
            )

            # 1. Drafted vendor email
            draft_body = (
                selected_rec.get("next_action", {}).get("body")
                or selected_rec.get("draft_email")
            )
            if not draft_body:
                reasons_list = selected_rec.get("reasoning") or [selected_rec.get("key_reason", "Policy clarification required.")]
                vnd_name = selected_rec.get("vendor_name") or "Vendor"
                inv_num = selected_rec.get("invoice_number") or "Submitted Invoice"
                draft_body = (
                    f"Dear {vnd_name},\n\n"
                    f"We are currently reviewing your invoice {inv_num}.\n"
                    f"Our automated Accounts Payable system has flagged the following items requiring clarification:\n"
                    + "\n".join(f"- {r}" for r in reasons_list) + "\n\n"
                    f"Please provide an amended invoice or confirm PO reference at your earliest convenience.\n\n"
                    f"Sincerely,\nAccounts Payable Operations"
                )

            st.markdown("**Draft Vendor Clarification Email:**")
            st.text_area(
                "Review / edit drafted email before sending:",
                value=draft_body,
                height=140,
                key=f"audit_email_area_{selected_idx}",
                label_visibility="collapsed",
            )

            # 2. Reviewer Note & Action Buttons
            reviewer_note = st.text_input(
                "Reviewer Note / Justification (Optional):",
                placeholder="e.g., Verified delivery with warehouse; approved over-PO variance.",
                key=f"audit_reviewer_note_{selected_idx}",
            )

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("✅ Approve & Override", type="primary", use_container_width=True, key=f"btn_audit_appr_{selected_idx}"):
                    fresh_state = get_state()
                    rec_hash = selected_rec.get("file_hash")
                    rec_inv = selected_rec.get("invoice_number")
                    target = None

                    # Find exact matching record in store
                    for r in fresh_state.get("run_history", []):
                        if (rec_hash and r.get("file_hash") == rec_hash) or (rec_inv and r.get("invoice_number") == rec_inv):
                            target = r
                            break
                    if not target and selected_idx < len(fresh_state.get("run_history", [])):
                        target = fresh_state["run_history"][selected_idx]

                    if target:
                        target["status"] = "MANUALLY APPROVED"
                        if "decision" in target:
                            target["decision"] = "MANUALLY APPROVED"

                        note_clean = reviewer_note.strip()
                        append_msg = f"Human-in-the-loop manual override granted: {note_clean}" if note_clean else "Human-in-the-loop manual override granted by AP reviewer."
                        if "reasoning" not in target or not isinstance(target["reasoning"], list):
                            target["reasoning"] = []
                        target["reasoning"].append(append_msg)
                        target["key_reason"] = append_msg

                        save_state(fresh_state)

                        # Update matched PO's previously_billed amount
                        po_num_to_bill = target.get("po_number")
                        amt_to_bill = float(target.get("total_amount") or 0.0)
                        if po_num_to_bill and po_num_to_bill != "None" and amt_to_bill > 0:
                            update_po_billed(po_num_to_bill, amt_to_bill)

                        st.toast(f"Invoice {target.get('invoice_number', '')} successfully approved with manual override!", icon="🎉")
                        time.sleep(0.5)
                        st.rerun()

            with btn_col2:
                if st.button("❌ Reject Invoice", type="secondary", use_container_width=True, key=f"btn_audit_rej_{selected_idx}"):
                    fresh_state = get_state()
                    rec_hash = selected_rec.get("file_hash")
                    rec_inv = selected_rec.get("invoice_number")
                    target = None

                    for r in fresh_state.get("run_history", []):
                        if (rec_hash and r.get("file_hash") == rec_hash) or (rec_inv and r.get("invoice_number") == rec_inv):
                            target = r
                            break
                    if not target and selected_idx < len(fresh_state.get("run_history", [])):
                        target = fresh_state["run_history"][selected_idx]

                    if target:
                        target["status"] = "REJECTED"
                        if "decision" in target:
                            target["decision"] = "REJECTED"

                        note_clean = reviewer_note.strip()
                        append_msg = f"Manual rejection by reviewer: {note_clean}" if note_clean else "Invoice manually rejected during human review."
                        if "reasoning" not in target or not isinstance(target["reasoning"], list):
                            target["reasoning"] = []
                        target["reasoning"].append(append_msg)
                        target["key_reason"] = append_msg

                        save_state(fresh_state)

                        st.toast(f"Invoice {target.get('invoice_number', '')} marked as REJECTED.", icon="🚫")
                        time.sleep(0.5)
                        st.rerun()
    else:
        st.write("No processed invoices in ledger yet.")


# ==============================================================================
# TAB 3: PROCUREMENT & POLICY
# ==============================================================================
with tab_policy:
    st.subheader("🗂️ Procurement Master Data & Compliance Policy")
    st.caption("Live configuration of approval tolerance thresholds, approved vendors, and purchase order balances.")

    store_state = get_state()

    # Section A: Open Purchase Orders (Live Balances)
    st.markdown("### Section A: Open Purchase Orders (Live Balances)")
    pos = store_state.get("purchase_orders", [])
    po_table_data = []
    for po in pos:
        tot = float(po.get("total_amount", 0.0))
        billed = float(po.get("previously_billed", 0.0))
        rem = round(tot - billed, 2)
        util_pct = (billed / tot * 100.0) if tot > 0 else 0.0
        po_table_data.append({
            "PO Number": po.get("po_number"),
            "Vendor Name": po.get("vendor_name"),
            "Description": po.get("description"),
            "Total Budget": fmt_currency(tot),
            "Previously Billed": fmt_currency(billed),
            "Remaining Balance": fmt_currency(rem),
            "Utilization": f"{util_pct:.1f}%",
        })
    df_pos = pd.DataFrame(po_table_data)
    st.dataframe(df_pos, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Section B: Approved Vendor Master
    st.markdown("### Section B: Approved Vendor Master (AVM)")
    vendors = store_state.get("vendors", [])
    vendor_table_data = [
        {
            "Vendor ID": v.get("vendor_id"),
            "Legal Vendor Name": v.get("name"),
            "Master Status": v.get("status"),
        }
        for v in vendors
    ]
    df_vendors = pd.DataFrame(vendor_table_data)
    st.dataframe(df_vendors, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Section C: Live Policy Rules (Editable for Live Demo)
    st.markdown("### Section C: Live Compliance Policy Rules (Editable)")
    st.caption("Tune tolerance thresholds and duplicate windows below. Changes persist to `data/store.json` immediately.")

    curr_rules = store_state.get("policy_rules", {})
    init_pct = float(curr_rules.get("tolerance_percent", 2.0))
    init_max_amt = float(curr_rules.get("tolerance_max_amount", 250.0))
    init_window = int(curr_rules.get("duplicate_window_days", 14))

    with st.form("policy_rules_form"):
        r_col1, r_col2, r_col3 = st.columns(3)
        with r_col1:
            new_pct = st.number_input(
                "Variance Tolerance (%)",
                min_value=0.0,
                max_value=25.0,
                value=init_pct,
                step=0.5,
                help="Auto-approve variance up to this percentage over PO limit.",
            )
        with r_col2:
            new_max_amt = st.number_input(
                "Variance Cap ($ USD)",
                min_value=0.0,
                max_value=5000.0,
                value=init_max_amt,
                step=25.0,
                help="Absolute dollar cap for auto-approving over-PO variance.",
            )
        with r_col3:
            new_window = st.number_input(
                "Duplicate Window (Days)",
                min_value=1,
                max_value=90,
                value=init_window,
                step=1,
                help="Lookback window for detecting identical amount near-duplicates.",
            )

        save_policy_btn = st.form_submit_button("💾 Save Policy Rules", type="primary")

    if save_policy_btn:
        store_state["policy_rules"] = {
            "tolerance_percent": float(new_pct),
            "tolerance_max_amount": float(new_max_amt),
            "duplicate_window_days": int(new_window),
        }
        save_state(store_state)
        st.toast(
            f"Policy rules updated: Tolerance {new_pct:.1f}% / ${new_max_amt:,.2f}, Window {new_window} days!",
            icon="💾",
        )
        time.sleep(0.5)
        st.rerun()
