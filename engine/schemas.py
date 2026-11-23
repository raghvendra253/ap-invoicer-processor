"""Pydantic schemas for extracted invoices, stage outcomes, and pipeline reports."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class LineItem(BaseModel):
    """Line item on an invoice."""
    description: str = Field(..., description="Description of the product or service billed.")
    amount: float = Field(..., description="Total line item amount.")


class ExtractedInvoice(BaseModel):
    """Structured fields extracted from an invoice PDF."""
    vendor_name: Optional[str] = Field(default=None, description="Name of the vendor/supplier.")
    invoice_number: Optional[str] = Field(default=None, description="Invoice identifier / number.")
    invoice_date: Optional[str] = Field(default=None, description="Date of the invoice (YYYY-MM-DD or formatted).")
    po_reference: Optional[str] = Field(default=None, description="Explicit Purchase Order number referenced on invoice.")
    subtotal: Optional[float] = Field(default=None, description="Subtotal before taxes.")
    tax_amount: Optional[float] = Field(default=None, description="Explicit tax amount if separated.")
    tax_mode: Literal["separated", "embedded", "unknown"] = Field(
        default="unknown",
        description="Whether taxes are itemized separately or embedded/tax-inclusive."
    )
    total_amount: Optional[float] = Field(default=None, description="Total invoice amount due.")
    line_items: List[LineItem] = Field(default_factory=list, description="List of itemized invoice lines.")
    missing_fields: List[str] = Field(default_factory=list, description="List of expected invoice fields that were not found.")
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0.")


class StageResult(BaseModel):
    """Structured output for each verification stage."""
    stage_number: int = Field(..., description="Stage sequence number (1 through 6).")
    name: str = Field(..., description="Human-readable title of the stage.")
    status: Literal["passed", "warning", "failed"] = Field(
        ...,
        description="Status indicator: passed (green), warning (amber), failed (red)."
    )
    summary: str = Field(..., description="Short single-sentence executive summary.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary stage-specific metrics and data.")


class PipelineReport(BaseModel):
    """Comprehensive final report produced by the AP pipeline."""
    filename: str
    file_hash: str
    doc_type: str
    stages: List[StageResult] = Field(default_factory=list)
    extracted_invoice: Optional[ExtractedInvoice] = None
    decision: Literal["AUTO-APPROVED", "NEEDS REVIEW", "REJECTED"]
    reasoning: List[str] = Field(default_factory=list)
    next_action: Dict[str, Any] = Field(default_factory=dict)
