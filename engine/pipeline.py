"""Pipeline orchestrator for AP Invoice Processing."""

from typing import Generator, Union

from .extractor import extract_invoice_with_groq, inspect_pdf
from .rules import (
    match_po_and_spend,
    synthesize_decision,
    validate_math_and_tolerance,
    validate_vendor_and_duplicates,
)
from .schemas import PipelineReport, StageResult

try:
    from ..data.db import get_state
except ImportError:
    from data.db import get_state


def run_invoice_pipeline(
    pdf_bytes: bytes,
    filename: str,
) -> Generator[Union[StageResult, PipelineReport], None, PipelineReport]:
    """Orchestrates Stages 1 through 6 of the invoice processing pipeline.

    Yields each StageResult sequentially for real-time UI display,
    and finally yields the complete PipelineReport.
    """
    stages = []

    # ---------------------------------------------------------
    # Stage 1: PDF Inspection & Classification
    # ---------------------------------------------------------
    metadata, stage1 = inspect_pdf(pdf_bytes, filename)
    stages.append(stage1)
    yield stage1

    # ---------------------------------------------------------
    # Stage 2: AI / Multimodal Extraction
    # ---------------------------------------------------------
    extracted, stage2 = extract_invoice_with_groq(
        pdf_bytes=pdf_bytes,
        doc_type=metadata["doc_type"],
        raw_text=metadata["raw_text"],
        filename=filename,
    )
    stages.append(stage2)
    yield stage2

    # Fresh database state for rules evaluation
    store_state = get_state()

    # ---------------------------------------------------------
    # Stage 3: Vendor & Duplicate Gate
    # ---------------------------------------------------------
    matched_vendor, duplicate_info, stage3 = validate_vendor_and_duplicates(
        extracted=extracted,
        file_hash=metadata["file_hash"],
        store_state=store_state,
    )
    stages.append(stage3)
    yield stage3

    # ---------------------------------------------------------
    # Stage 4: PO Matching & Cumulative Spend
    # ---------------------------------------------------------
    po_details, stage4 = match_po_and_spend(
        extracted=extracted,
        matched_vendor=matched_vendor,
        store_state=store_state,
    )
    stages.append(stage4)
    yield stage4

    # ---------------------------------------------------------
    # Stage 5: Deterministic Math & Tolerance Validation
    # ---------------------------------------------------------
    math_details, stage5 = validate_math_and_tolerance(
        extracted=extracted,
        po_details=po_details,
        store_state=store_state,
    )
    stages.append(stage5)
    yield stage5

    # ---------------------------------------------------------
    # Stage 6: Decision Synthesis & Actions
    # ---------------------------------------------------------
    decision, reasoning, next_action, stage6 = synthesize_decision(
        stages=stages,
        extracted=extracted,
        matched_vendor=matched_vendor,
        po_details=po_details,
        math_details=math_details,
        duplicate_info=duplicate_info,
        file_hash=metadata["file_hash"],
        filename=filename,
    )
    stages.append(stage6)
    yield stage6

    # ---------------------------------------------------------
    # Final Pipeline Report
    # ---------------------------------------------------------
    report = PipelineReport(
        filename=filename,
        file_hash=metadata["file_hash"],
        doc_type=metadata["doc_type"],
        stages=stages,
        extracted_invoice=extracted,
        decision=decision,
        reasoning=reasoning,
        next_action=next_action,
    )
    yield report
    return report
