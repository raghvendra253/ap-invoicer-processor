"""Verification script for AP Invoice Processing Pipeline.

Resets the store, runs all 5 test invoices through run_invoice_pipeline,
and prints a formatted summary table of stage results and decisions.
"""

from pathlib import Path
from typing import List

from data.db import reset_db
from engine.pipeline import run_invoice_pipeline
from engine.schemas import PipelineReport, StageResult

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = BASE_DIR / "sample_invoices"


def run_tests() -> None:
    print("=" * 105)
    print("AP INVOICE PROCESSOR - PIPELINE VERIFICATION RUN")
    print("=" * 105)

    # 1. Reset database to clean seed state
    print("[1/3] Resetting persistence layer to pristine seed state...")
    clean_state = reset_db()
    print(f"      Initial POs: {len(clean_state['purchase_orders'])} | History: {len(clean_state['run_history'])}")

    # 2. Check sample invoices
    pdf_files = sorted(list(SAMPLE_DIR.glob("*.pdf")))
    if not pdf_files:
        raise FileNotFoundError(f"No test PDFs found in {SAMPLE_DIR}. Run generate_test_pdfs.py first.")
    print(f"[2/3] Found {len(pdf_files)} test invoices to evaluate.\n")

    # 3. Process each invoice
    results = []
    print("[3/3] Executing 6-Stage Pipeline for each invoice:")
    print("-" * 105)

    for pdf_path in pdf_files:
        filename = pdf_path.name
        print(f"\n>>> Processing: {filename}")
        pdf_bytes = pdf_path.read_bytes()

        final_report: PipelineReport = None
        for update in run_invoice_pipeline(pdf_bytes, filename):
            if isinstance(update, StageResult):
                status_icon = "[PASS]" if update.status == "passed" else ("[WARN]" if update.status == "warning" else "[FAIL]")
                print(f"    Stage {update.stage_number} ({update.name[:32]}): {status_icon} - {update.summary}")
            elif isinstance(update, PipelineReport):
                final_report = update

        if final_report:
            # Check Stage 4 details for resolved PO (explicit or implicit)
            s4 = next((s for s in final_report.stages if s.stage_number == 4), None)
            s4_po = s4.details.get("po_number") if s4 else None
            s4_type = s4.details.get("match_type") if s4 else ""
            if s4_po and s4_type == "implicit":
                po_display = f"{s4_po} (impl)"
            elif s4_po:
                po_display = s4_po
            else:
                po_display = "None"

            key_reason = final_report.reasoning[0] if final_report.reasoning else "N/A"
            results.append({
                "filename": filename,
                "doc_type": final_report.doc_type,
                "matched_po": po_display,
                "decision": final_report.decision,
                "key_reason": key_reason,
            })

    # Summary Table
    print("\n" + "=" * 115)
    print("PIPELINE EXECUTION SUMMARY TABLE")
    print("=" * 115)
    header = f"{'Filename':<36} | {'Doc Type':<14} | {'Matched PO':<18} | {'Decision':<14} | {'Key Reason'}"
    print(header)
    print("-" * 115)
    for r in results:
        print(f"{r['filename']:<36} | {r['doc_type']:<14} | {r['matched_po']:<18} | {r['decision']:<14} | {r['key_reason']}")
    print("=" * 115)


if __name__ == "__main__":
    run_tests()
