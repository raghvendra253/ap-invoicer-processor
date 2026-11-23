"""Test PDF Invoice Generator for AP Invoice Processor.

Generates 5 realistic test invoice PDFs for evaluating extraction and policy matching:
1. 01_happy_path_acme.pdf: Clean machine-readable PDF matching PO-2026-101.
2. 02_split_po_overbill_apex.pdf: Clean machine-readable PDF that exceeds PO-2026-102.
3. 03_scanned_missing_fields_nova.pdf: Scanned raster image PDF without text layer,
   omitting Invoice Date and PO Number, allowing implicit matching to PO-2026-103.
4. 04_near_duplicate_acme.pdf: Clean machine-readable PDF (INV-882-R) near-duplicate of INV-882.
5. 05_tax_embedded_tolerance_summit.pdf: Clean machine-readable PDF with tax-inclusive pricing
   within the 2% / $250 variance tolerance of PO-2026-104.
"""

import io
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

try:
    from .db import init_db
except ImportError:
    from db import init_db

DATA_DIR = Path(__file__).resolve().parent
BASE_DIR = DATA_DIR.parent
SAMPLE_DIR = BASE_DIR / "sample_invoices"

# Enterprise Client Details
CLIENT_INFO = [
    "Enterprise Operations Inc.",
    "Accounts Payable Department",
    "100 Innovation Way, Suite 400",
    "San Francisco, CA 94105",
    "ap@enterpriseops.internal",
]


def draw_clean_invoice_pdf(
    file_path: Path,
    vendor_name: str,
    vendor_address: List[str],
    invoice_number: str,
    invoice_date: str,
    po_number: Optional[str],
    due_date: str,
    items: List[Dict[str, Any]],
    subtotal: float,
    tax: float,
    total: float,
    notes: Optional[str] = None,
    tax_label: str = "Tax (Estimated/Calculated)",
) -> None:
    """Generates a clean, vector-based, machine-readable invoice PDF using ReportLab."""
    c = canvas.Canvas(str(file_path), pagesize=letter)
    width, height = letter  # 612 x 792 pt

    # Background Top Accent Bar
    c.setFillColor(colors.HexColor("#1E293B"))
    c.rect(0, height - 12, width, 12, stroke=0, fill=1)

    # Vendor Details (Top Left)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(45, height - 48, vendor_name)

    c.setFillColor(colors.HexColor("#475569"))
    c.setFont("Helvetica", 9)
    y_pos = height - 64
    for line in vendor_address:
        c.drawString(45, y_pos, line)
        y_pos -= 13

    # Invoice Header Title & Metadata (Top Right)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 22)
    c.drawRightString(width - 45, height - 48, "INVOICE")

    # Metadata Box
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.rect(width - 240, height - 148, 195, 90, stroke=1, fill=1)

    c.setFillColor(colors.HexColor("#64748B"))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(width - 230, height - 74, "INVOICE NUMBER:")
    c.drawString(width - 230, height - 92, "INVOICE DATE:")
    c.drawString(width - 230, height - 110, "PURCHASE ORDER:")
    c.drawString(width - 230, height - 128, "PAYMENT DUE:")

    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 8.5)
    c.drawRightString(width - 55, height - 74, invoice_number)
    c.setFont("Helvetica", 8.5)
    c.drawRightString(width - 55, height - 92, invoice_date)
    c.drawRightString(width - 55, height - 110, po_number if po_number else "N/A")
    c.drawRightString(width - 55, height - 128, due_date)

    # Horizontal Divider
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.setLineWidth(0.8)
    c.line(45, height - 165, width - 45, height - 165)

    # Bill To Section
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(45, height - 185, "BILL TO:")

    c.setFillColor(colors.HexColor("#334155"))
    c.setFont("Helvetica", 9)
    y_bill = height - 200
    for line in CLIENT_INFO:
        c.drawString(45, y_bill, line)
        y_bill -= 13

    # Table Header
    table_top = height - 280
    c.setFillColor(colors.HexColor("#F1F5F9"))
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.rect(45, table_top, width - 90, 24, stroke=1, fill=1)

    c.setFillColor(colors.HexColor("#1E293B"))
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(55, table_top + 7, "ITEM DESCRIPTION")
    c.drawRightString(360, table_top + 7, "QTY")
    c.drawRightString(455, table_top + 7, "UNIT PRICE")
    c.drawRightString(width - 55, table_top + 7, "AMOUNT")

    # Table Rows
    curr_y = table_top - 20
    for idx, item in enumerate(items):
        c.setFillColor(colors.HexColor("#0F172A"))
        c.setFont("Helvetica", 9)
        c.drawString(55, curr_y, item["description"])
        c.drawRightString(360, curr_y, str(item["quantity"]))
        c.drawRightString(455, curr_y, f"${item['unit_price']:,.2f}")
        c.drawRightString(width - 55, curr_y, f"${item['amount']:,.2f}")

        # Row divider
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.setLineWidth(0.5)
        c.line(45, curr_y - 6, width - 45, curr_y - 6)
        curr_y -= 26

    # Totals Block (Right Aligned)
    totals_top = curr_y - 15

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawRightString(width - 150, totals_top, "Subtotal:")
    c.setFillColor(colors.HexColor("#0F172A"))
    c.drawRightString(width - 55, totals_top, f"${subtotal:,.2f}")

    totals_top -= 18
    c.setFillColor(colors.HexColor("#475569"))
    c.drawRightString(width - 150, totals_top, f"{tax_label}:")
    c.setFillColor(colors.HexColor("#0F172A"))
    c.drawRightString(width - 55, totals_top, f"${tax:,.2f}")

    totals_top -= 24
    # Highlight Box for Total Amount Due
    c.setFillColor(colors.HexColor("#0F172A"))
    c.rect(width - 240, totals_top - 6, 195, 26, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(width - 230, totals_top + 2, "TOTAL DUE (USD):")
    c.drawRightString(width - 55, totals_top + 2, f"${total:,.2f}")

    # Notes / Instructions
    if notes:
        c.setFillColor(colors.HexColor("#475569"))
        c.setFont("Helvetica-Bold", 8)
        c.drawString(45, totals_top + 10, "PAYMENT TERMS & NOTES:")
        c.setFont("Helvetica", 8)
        c.drawString(45, totals_top - 2, notes)

    # Footer
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.setLineWidth(0.5)
    c.line(45, 45, width - 45, 45)

    c.setFillColor(colors.HexColor("#94A3B8"))
    c.setFont("Helvetica", 7.5)
    c.drawString(45, 32, "Electronic invoice generated by vendor ERP. Remittance advice attached upon request.")
    c.drawRightString(width - 45, 32, "Page 1 of 1")

    c.save()


def generate_scanned_invoice_pdf(
    file_path: Path,
    vendor_name: str,
    vendor_address: List[str],
    invoice_number: str,
    items: List[Dict[str, Any]],
    total: float,
    notes: Optional[str] = None,
) -> None:
    """Generates an image-only, scanned-style PDF (no text layer) with rotation and sensor noise."""
    # Render at high resolution (1700x2200 ~ 200 DPI for Letter size)
    w, h = 1700, 2200
    base_color = (250, 249, 246)  # Warm paper white
    img = Image.new("RGB", (w, h), base_color)
    draw = ImageDraw.Draw(img)

    # Load TrueType Fonts if available, otherwise default
    try:
        font_large_bold = ImageFont.truetype("arialbd.ttf", 46)
        font_title_bold = ImageFont.truetype("arialbd.ttf", 58)
        font_sub_bold = ImageFont.truetype("arialbd.ttf", 28)
        font_regular = ImageFont.truetype("arial.ttf", 25)
        font_regular_small = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font_large_bold = ImageFont.load_default()
        font_title_bold = font_large_bold
        font_sub_bold = font_large_bold
        font_regular = font_large_bold
        font_regular_small = font_large_bold

    # Draw Header (Simulating a creative studio invoice)
    draw.text((120, 130), vendor_name, fill=(30, 41, 59), font=font_large_bold)
    y_hdr = 190
    for line in vendor_address:
        draw.text((120, y_hdr), line, fill=(71, 85, 105), font=font_regular)
        y_hdr += 36

    # Title & Invoice Number ONLY (Explicitly OMITTING Date and PO Number)
    draw.text((w - 520, 130), "INVOICE", fill=(15, 23, 42), font=font_title_bold)
    draw.rectangle([(w - 620, 210), (w - 120, 310)], fill=(241, 245, 249), outline=(203, 213, 225), width=2)
    draw.text((w - 600, 230), "INVOICE #:", fill=(100, 116, 139), font=font_sub_bold)
    draw.text((w - 360, 230), invoice_number, fill=(15, 23, 42), font=font_sub_bold)
    draw.text((w - 600, 270), "STATUS:", fill=(100, 116, 139), font=font_regular)
    draw.text((w - 360, 270), "PENDING REMITTANCE", fill=(15, 23, 42), font=font_regular)

    # Horizontal Rule
    draw.line([(120, 380), (w - 120, 380)], fill=(203, 213, 225), width=3)

    # Bill To Section
    draw.text((120, 420), "BILL TO:", fill=(15, 23, 42), font=font_sub_bold)
    y_bill = 465
    for line in CLIENT_INFO:
        draw.text((120, y_bill), line, fill=(71, 85, 105), font=font_regular)
        y_bill += 35

    # Line Item Table Header
    tbl_top = 740
    draw.rectangle([(120, tbl_top), (w - 120, tbl_top + 60)], fill=(226, 232, 240), outline=(148, 163, 184), width=2)
    draw.text((145, tbl_top + 16), "SERVICE / WORK DESCRIPTION", fill=(30, 41, 59), font=font_sub_bold)
    draw.text((w - 550, tbl_top + 16), "QTY", fill=(30, 41, 59), font=font_sub_bold)
    draw.text((w - 400, tbl_top + 16), "RATE", fill=(30, 41, 59), font=font_sub_bold)
    draw.text((w - 240, tbl_top + 16), "AMOUNT", fill=(30, 41, 59), font=font_sub_bold)

    # Items
    curr_y = tbl_top + 80
    for item in items:
        draw.text((145, curr_y), item["description"], fill=(15, 23, 42), font=font_regular)
        draw.text((w - 530, curr_y), str(item["quantity"]), fill=(15, 23, 42), font=font_regular)
        draw.text((w - 410, curr_y), f"${item['unit_price']:,.2f}", fill=(15, 23, 42), font=font_regular)
        draw.text((w - 250, curr_y), f"${item['amount']:,.2f}", fill=(15, 23, 42), font=font_regular)
        draw.line([(120, curr_y + 45), (w - 120, curr_y + 45)], fill=(226, 232, 240), width=2)
        curr_y += 70

    # Totals Block
    tot_y = curr_y + 40
    draw.text((w - 550, tot_y), "Subtotal:", fill=(100, 116, 139), font=font_sub_bold)
    draw.text((w - 250, tot_y), f"${total:,.2f}", fill=(15, 23, 42), font=font_sub_bold)

    tot_y += 50
    draw.text((w - 550, tot_y), "Sales Tax (0% Exempt):", fill=(100, 116, 139), font=font_sub_bold)
    draw.text((w - 250, tot_y), "$0.00", fill=(15, 23, 42), font=font_sub_bold)

    tot_y += 65
    draw.rectangle([(w - 620, tot_y - 10), (w - 120, tot_y + 60)], fill=(30, 41, 59))
    draw.text((w - 600, tot_y + 10), "TOTAL DUE (USD):", fill=(255, 255, 255), font=font_sub_bold)
    draw.text((w - 250, tot_y + 10), f"${total:,.2f}", fill=(255, 255, 255), font=font_sub_bold)

    # Remittance instructions
    if notes:
        draw.text((120, tot_y + 20), "REMITTANCE INSTRUCTIONS:", fill=(100, 116, 139), font=font_sub_bold)
        draw.text((120, tot_y + 65), notes, fill=(71, 85, 105), font=font_regular_small)

    # Convert to NumPy array to add realistic scanner noise and subtle sensor grain
    img_arr = np.array(img, dtype=np.float32)

    # Gaussian scanner noise
    rng = np.random.default_rng(seed=42)
    noise = rng.normal(0, 4.0, (h, w, 3))
    noisy_arr = np.clip(img_arr + noise, 0, 255).astype(np.uint8)
    noisy_img = Image.fromarray(noisy_arr)

    # Apply 1.5 degree rotation (simulating flatbed paper skew)
    rotated_img = noisy_img.rotate(
        1.5,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor=(245, 245, 242),
    )

    # Save to ReportLab PDF as a single embedded image (NO text layer)
    img_buffer = io.BytesIO()
    rotated_img.save(img_buffer, format="JPEG", quality=90)
    img_buffer.seek(0)

    c = canvas.Canvas(str(file_path), pagesize=letter)
    width, height = letter
    c.drawImage(ImageReader(img_buffer), 0, 0, width=width, height=height)
    c.save()


def generate_all_invoices() -> List[Path]:
    """Generates all 5 test invoice PDFs into sample_invoices/."""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    generated_files: List[Path] = []

    # -------------------------------------------------------------------------
    # 1. 01_happy_path_acme.pdf
    # -------------------------------------------------------------------------
    p1 = SAMPLE_DIR / "01_happy_path_acme.pdf"
    draw_clean_invoice_pdf(
        file_path=p1,
        vendor_name="Acme Cloud Solutions Inc.",
        vendor_address=[
            "500 Enterprise Way, Suite 800",
            "San Jose, CA 95113",
            "billing@acmecloud.example.com",
            "Tax ID: 94-2849102",
        ],
        invoice_number="INV-2026-101",
        invoice_date="2026-10-20",
        po_number="PO-2026-101",
        due_date="2026-11-19",
        items=[
            {
                "description": "Production Cloud Infrastructure Hosting - Monthly Tier",
                "quantity": 1,
                "unit_price": 3500.00,
                "amount": 3500.00,
            },
            {
                "description": "24/7 Premium Managed Systems Support & Monitoring",
                "quantity": 1,
                "unit_price": 600.00,
                "amount": 600.00,
            },
        ],
        subtotal=4100.00,
        tax=400.00,
        total=4500.00,
        notes="Net 30. Wire transfer to Acme Cloud Solutions Inc. Routing: 121000358.",
    )
    generated_files.append(p1)

    # -------------------------------------------------------------------------
    # 2. 02_split_po_overbill_apex.pdf
    # -------------------------------------------------------------------------
    p2 = SAMPLE_DIR / "02_split_po_overbill_apex.pdf"
    draw_clean_invoice_pdf(
        file_path=p2,
        vendor_name="Apex Logistics Group",
        vendor_address=[
            "1200 Logistics Pkwy, Freight Hub B",
            "Chicago, IL 60607",
            "invoicing@apexlogistics.example.com",
            "USDOT: 8829104 | Tax ID: 36-9281044",
        ],
        invoice_number="INV-502",
        invoice_date="2026-10-21",
        po_number="PO-2026-102",
        due_date="2026-11-20",
        items=[
            {
                "description": "Midwest Regional Freight Linehaul & Dedicated Hauling",
                "quantity": 1,
                "unit_price": 3700.00,
                "amount": 3700.00,
            },
            {
                "description": "Cross-Dock Warehousing, Pallet Storage & Handling",
                "quantity": 1,
                "unit_price": 2000.00,
                "amount": 2000.00,
            },
        ],
        subtotal=5700.00,
        tax=500.00,
        total=6200.00,
        tax_label="Freight Surcharges & State Transit Tax",
        notes="Partial billing #2 for PO-2026-102 (Prior billed: $10,000 on INV-501).",
    )
    generated_files.append(p2)

    # -------------------------------------------------------------------------
    # 3. 03_scanned_missing_fields_nova.pdf
    # -------------------------------------------------------------------------
    p3 = SAMPLE_DIR / "03_scanned_missing_fields_nova.pdf"
    generate_scanned_invoice_pdf(
        file_path=p3,
        vendor_name="Nova Creative Studio",
        vendor_address=[
            "742 Broadway Design Loft, 4th Floor",
            "New York, NY 10003",
            "accounts@novacreative.studio",
        ],
        invoice_number="NCS-774",
        items=[
            {
                "description": "Brand Refresh & Website Graphics Package",
                "quantity": 1,
                "unit_price": 3200.00,
                "amount": 3200.00,
            }
        ],
        total=3200.00,
        notes="Please wire remittance to Nova Creative Studio LLC. Routing 021000021 Acc #882019482.",
    )
    generated_files.append(p3)

    # -------------------------------------------------------------------------
    # 4. 04_near_duplicate_acme.pdf
    # -------------------------------------------------------------------------
    p4 = SAMPLE_DIR / "04_near_duplicate_acme.pdf"
    draw_clean_invoice_pdf(
        file_path=p4,
        vendor_name="Acme Cloud Solutions Inc.",
        vendor_address=[
            "500 Enterprise Way, Suite 800",
            "San Jose, CA 95113",
            "billing@acmecloud.example.com",
            "Tax ID: 94-2849102",
        ],
        invoice_number="INV-882-R",
        invoice_date="2026-10-18",
        po_number="PO-2026-099",
        due_date="2026-11-17",
        items=[
            {
                "description": "Q3 Enterprise Server Cluster Maintenance & Monitoring",
                "quantity": 1,
                "unit_price": 2200.00,
                "amount": 2200.00,
            },
            {
                "description": "Mission-Critical 15-Minute SLA Add-on",
                "quantity": 1,
                "unit_price": 200.00,
                "amount": 200.00,
            },
        ],
        subtotal=2400.00,
        tax=0.00,
        total=2400.00,
        tax_label="Tax (Service Exempt)",
        notes="Revision / Re-issue matching previous service billing INV-882.",
    )
    generated_files.append(p4)

    # -------------------------------------------------------------------------
    # 5. 05_tax_embedded_tolerance_summit.pdf
    # -------------------------------------------------------------------------
    p5 = SAMPLE_DIR / "05_tax_embedded_tolerance_summit.pdf"
    draw_clean_invoice_pdf(
        file_path=p5,
        vendor_name="Summit Office Systems",
        vendor_address=[
            "3400 Industrial Parkway, Suite C",
            "Denver, CO 80216",
            "orders@summitofficesys.com",
            "Tax ID: 84-1928471",
        ],
        invoice_number="SOS-309",
        invoice_date="2026-10-22",
        po_number="PO-2026-104",
        due_date="2026-11-21",
        items=[
            {
                "description": "Annual Ergonomic Hardware Bundle (Tax Inclusive)",
                "quantity": 1,
                "unit_price": 5070.00,
                "amount": 5070.00,
            }
        ],
        subtotal=5070.00,
        tax=0.00,
        total=5070.00,
        tax_label="Tax (Included in Bundle Price)",
        notes="Standard Net 30 terms. All municipal and state equipment sales taxes included.",
    )
    generated_files.append(p5)

    return generated_files


def main() -> None:
    """Initializes the database and generates all test PDFs."""
    print("=" * 60)
    print("AP Invoice Processor - Phase 1 Setup & Test PDF Generation")
    print("=" * 60)

    # 1. Initialize store.json
    db_state = init_db()
    print(f"[OK] Persistence initialized: data/store.json")
    print(f"     - Vendors: {len(db_state.get('vendors', []))}")
    print(f"     - Purchase Orders: {len(db_state.get('purchase_orders', []))}")
    print(f"     - Seed Run History: {len(db_state.get('run_history', []))}")
    print(f"     - Policy Rules: {db_state.get('policy_rules', {})}")

    # 2. Generate the 5 test PDFs
    print(f"\n[..] Generating 5 test invoices in: {SAMPLE_DIR}")
    files = generate_all_invoices()
    for f in files:
        size_kb = f.stat().st_size / 1024
        print(f"     [+] Created {f.name} ({size_kb:.1f} KB)")

    print("\n[SUCCESS] Phase 1 setup and PDF generation completed successfully!")


if __name__ == "__main__":
    main()
