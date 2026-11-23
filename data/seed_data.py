"""Seed data for AP Invoice Processor."""

from typing import Any, Dict, List

POLICY_RULES: Dict[str, Any] = {
    "tolerance_percent": 2.0,
    "tolerance_max_amount": 250.0,
    "duplicate_window_days": 14,
}

VENDORS: List[Dict[str, Any]] = [
    {
        "vendor_id": "V-101",
        "name": "Acme Cloud Solutions Inc.",
        "status": "APPROVED",
    },
    {
        "vendor_id": "V-102",
        "name": "Apex Logistics Group",
        "status": "APPROVED",
    },
    {
        "vendor_id": "V-103",
        "name": "Nova Creative Studio",
        "status": "APPROVED",
    },
    {
        "vendor_id": "V-104",
        "name": "Summit Office Systems",
        "status": "APPROVED",
    },
]

PURCHASE_ORDERS: List[Dict[str, Any]] = [
    {
        "po_number": "PO-2026-101",
        "vendor_name": "Acme Cloud Solutions Inc.",
        "total_amount": 4500.00,
        "previously_billed": 0.00,
        "description": "Q3 Cloud Infrastructure & Support",
    },
    {
        "po_number": "PO-2026-102",
        "vendor_name": "Apex Logistics Group",
        "total_amount": 15000.00,
        "previously_billed": 10000.00,
        "description": "Regional Freight & Warehousing",
    },
    {
        "po_number": "PO-2026-103",
        "vendor_name": "Nova Creative Studio",
        "total_amount": 3200.00,
        "previously_billed": 0.00,
        "description": "Brand Refresh & Website Graphics",
    },
    {
        "po_number": "PO-2026-104",
        "vendor_name": "Summit Office Systems",
        "total_amount": 5000.00,
        "previously_billed": 0.00,
        "description": "Annual Ergonomic Hardware Bundle",
    },
]

INITIAL_RUN_HISTORY: List[Dict[str, Any]] = [
    {
        "timestamp": "2026-10-15 09:30:00",
        "filename": "seed_invoice_882.pdf",
        "invoice_number": "INV-882",
        "vendor_name": "Acme Cloud Solutions Inc.",
        "invoice_date": "2026-10-15",
        "total_amount": 2400.00,
        "po_number": "PO-2026-099",
        "status": "AUTO-APPROVED",
        "file_hash": "seed_hash_882",
        "key_reason": "Pre-seeded baseline invoice for duplicate & near-duplicate validation.",
        "reasoning": [
            "Pre-seeded historical baseline invoice.",
            "Used to test 14-day duplicate window detection.",
        ],
        "extracted_fields": {
            "vendor_name": "Acme Cloud Solutions Inc.",
            "invoice_number": "INV-882",
            "invoice_date": "2026-10-15",
            "po_reference": "PO-2026-099",
            "total_amount": 2400.00,
            "tax_mode": "embedded",
            "line_items": [
                {"description": "Historical Cloud Infrastructure Billing", "amount": 2400.00}
            ],
            "missing_fields": [],
            "extraction_confidence": 1.0,
        },
        "stage_summaries": [
            {"stage_number": 1, "name": "PDF Inspection", "status": "passed", "summary": "Baseline PDF."},
            {"stage_number": 2, "name": "AI Extraction", "status": "passed", "summary": "Extracted $2,400."},
            {"stage_number": 3, "name": "Vendor Gate", "status": "passed", "summary": "Approved vendor."},
            {"stage_number": 4, "name": "PO Matching", "status": "passed", "summary": "Matched PO-2026-099."},
            {"stage_number": 5, "name": "Math Validation", "status": "passed", "summary": "Math valid."},
            {"stage_number": 6, "name": "Decision", "status": "passed", "summary": "Auto-approved baseline."},
        ],
    }
]


def get_seed_data() -> Dict[str, Any]:
    """Returns a deep copy-ready dictionary of clean seed data."""
    return {
        "policy_rules": dict(POLICY_RULES),
        "vendors": [dict(v) for v in VENDORS],
        "purchase_orders": [dict(po) for po in PURCHASE_ORDERS],
        "run_history": [dict(r) for r in INITIAL_RUN_HISTORY],
    }
