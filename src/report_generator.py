"""
src/report_generator.py — Financial Reporting and Export Module
================================================================
Generates professional A4 PDF financial reports using ReportLab and
provides secure CSV transaction exports with formula injection protection.

Functions:
  1. generate_monthly_report: Generates a complete monthly PDF report.
  2. generate_custom_period_report: Generates a date-range financial PDF report.
  3. generate_transaction_report: Generates a detailed transaction listing PDF.
  4. export_transactions_csv: Exports transactions to CSV with UTF-8 BOM and formula sanitization.
  5. export_all_transactions_csv: Convenience wrapper for exporting the full database.
  6. ReportGenerator: Object-oriented interface wrapper.
"""

from __future__ import annotations

import datetime
import io
import logging
import os
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.analytics import (
    get_category_wise_expenses,
    get_financial_overview,
    get_payment_method_summary,
)
from src.budget_manager import get_budget_status
from src.database import validate_budget_month, validate_transaction_date
from src.expense_manager import get_filtered_transactions

logger = logging.getLogger(__name__)

# Report Directories
BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
OUTPUTS_DIR = BASE_DIR / "outputs" / "exports"

# Styling constants
COLOR_PRIMARY = colors.HexColor("#1A365D")    # Deep Navy
COLOR_SECONDARY = colors.HexColor("#2B6CB0")  # Slate Blue
COLOR_ACCENT = colors.HexColor("#2C5282")
COLOR_TEXT = colors.HexColor("#2D3748")
COLOR_MUTED = colors.HexColor("#718096")
COLOR_BG_LIGHT = colors.HexColor("#F7FAFC")
COLOR_BORDER = colors.HexColor("#E2E8F0")
COLOR_SUCCESS = colors.HexColor("#276749")
COLOR_DANGER = colors.HexColor("#9B2C2C")
COLOR_WARNING = colors.HexColor("#C05621")


# ---------------------------------------------------------------------------
# Numbered Canvas for Page Numbers & Headers/Footers
# ---------------------------------------------------------------------------

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas that accurately renders 'Page X of Y' on all pages."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(COLOR_MUTED)

        # Running Header
        self.drawString(36, 808, "Personal Expense Tracker — Financial Report")
        self.setStrokeColor(COLOR_BORDER)
        self.setLineWidth(0.5)
        self.line(36, 802, 559, 802)

        # Running Footer
        self.line(36, 45, 559, 45)
        self.drawString(36, 32, "Confidential — Generated for Personal Finance Management")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(559, 32, page_text)

        self.restoreState()


# ---------------------------------------------------------------------------
# PDF Formatting Helpers
# ---------------------------------------------------------------------------

def _format_currency_pdf(amount: Union[float, int]) -> str:
    """Format currency safely for PDF fonts without unicode symbol issues."""
    try:
        val = float(amount)
        return f"Rs. {val:,.2f}"
    except (ValueError, TypeError):
        return "Rs. 0.00"


def _format_pct_pdf(pct: Optional[Union[float, int]]) -> str:
    """Format percentage value or return N/A."""
    if pct is None:
        return "N/A"
    return f"{float(pct):.1f}%"


def _create_report_styles() -> dict[str, ParagraphStyle]:
    """Build consistent typography styles for ReportLab flowables."""
    base = getSampleStyleSheet()

    styles = {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=COLOR_PRIMARY,
            alignment=0,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=COLOR_MUTED,
            spaceAfter=15,
        ),
        "heading": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=COLOR_PRIMARY,
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=COLOR_TEXT,
        ),
        "body_bold": ParagraphStyle(
            "ReportBodyBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=COLOR_TEXT,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=colors.white,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=COLOR_TEXT,
        ),
        "table_cell_right": ParagraphStyle(
            "TableCellRight",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=COLOR_TEXT,
            alignment=2,
        ),
        "table_cell_bold": ParagraphStyle(
            "TableCellBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=COLOR_TEXT,
        ),
        "empty_msg": ParagraphStyle(
            "EmptyMessage",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=13,
            textColor=COLOR_MUTED,
            spaceAfter=8,
        ),
    }
    return styles


# ---------------------------------------------------------------------------
# CSV Formula Sanitization
# ---------------------------------------------------------------------------

def sanitize_csv_value(val: Any) -> Any:
    """
    Sanitize text values against spreadsheet formula injection (CSV Injection).

    If a text field begins with '=', '+', '-', '@', '\\t', or '\\r',
    prefixes it with a single quote (') so spreadsheet applications
    treat it strictly as a string literal.
    Does not modify numbers, dates, or database records.
    """
    if isinstance(val, str):
        # Check raw first char for tab/CR injection
        if val and val[0] in ("\t", "\r"):
            return f"'{val}"
        # Strip leading spaces before checking formula chars
        stripped = val.lstrip(" ")
        if stripped and stripped[0] in ("=", "+", "-", "@"):
            return f"'{stripped}"
    return val


def sanitize_dataframe_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Create a sanitized copy of a DataFrame safe for CSV export."""
    sanitized = df.copy()
    for col in sanitized.columns:
        if sanitized[col].dtype == object or isinstance(sanitized[col].dtype, pd.StringDtype):
            sanitized[col] = sanitized[col].apply(sanitize_csv_value)
    return sanitized


# ---------------------------------------------------------------------------
# 1. Monthly PDF Report
# ---------------------------------------------------------------------------

def generate_monthly_report(
    month: str,
    db_path: Optional[Union[Path, str]] = None,
    output_path: Optional[Union[Path, str]] = None,
) -> Path:
    """
    Generate an authoritative monthly financial report in PDF format.

    Parameters
    ----------
    month : str
        Target month in YYYY-MM format.
    db_path : Optional[Path | str]
        Database path.
    output_path : Optional[Path | str]
        Optional custom output PDF path.

    Returns
    -------
    Path
        Path to the generated PDF document.
    """
    validate_budget_month(month)

    if output_path is None:
        target_dir = REPORTS_DIR / "monthly_reports"
        target_dir.mkdir(parents=True, exist_ok=True)
        out_file = target_dir / f"expense_report_{month.replace('-', '_')}.pdf"
    else:
        out_file = Path(output_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Gather analytics data — use last day of month robustly
    year_int, month_int = int(month.split("-")[0]), int(month.split("-")[1])
    import calendar as _calendar
    last_day = _calendar.monthrange(year_int, month_int)[1]
    start_date = f"{month}-01"
    end_date = f"{month}-{last_day:02d}"
    overview = get_financial_overview(start_date=start_date, end_date=end_date, db_path=db_path)
    cat_df = get_category_wise_expenses(start_date=start_date, end_date=end_date, db_path=db_path)
    pm_df = get_payment_method_summary(start_date=start_date, end_date=end_date, db_path=db_path)
    budget_df = get_budget_status(month=month, db_path=db_path)
    txns_df = get_filtered_transactions(month=month, db_path=db_path)

    # 2. Build PDF Document
    doc = SimpleDocTemplate(
        str(out_file),
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=42,
        bottomMargin=42,
    )

    styles = _create_report_styles()
    story: list[Any] = []

    # Title & Metadata
    gen_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    story.append(Paragraph(f"Monthly Financial Statement — {month}", styles["title"]))
    story.append(Paragraph(f"Generated on {gen_time} | Currency: INR (Rs.)", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=COLOR_PRIMARY, spaceAfter=14))

    # KPI Summary Cards Table
    story.append(Paragraph("1. Executive Financial Summary", styles["heading"]))
    kpi_data = [
        [
            Paragraph("Total Income", styles["table_header"]),
            Paragraph("Total Expenses", styles["table_header"]),
            Paragraph("Net Savings", styles["table_header"]),
            Paragraph("Savings Rate", styles["table_header"]),
            Paragraph("Transactions", styles["table_header"]),
        ],
        [
            Paragraph(_format_currency_pdf(overview["total_income"]), styles["table_cell_bold"]),
            Paragraph(_format_currency_pdf(overview["total_expenses"]), styles["table_cell_bold"]),
            Paragraph(_format_currency_pdf(overview["net_savings"]), styles["table_cell_bold"]),
            Paragraph(_format_pct_pdf(overview["savings_rate"]), styles["table_cell_bold"]),
            Paragraph(str(overview["transaction_count"]), styles["table_cell_bold"]),
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[104, 104, 104, 104, 107])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("BACKGROUND", (0, 1), (-1, 1), COLOR_BG_LIGHT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 12))

    # Category Spending Breakdown
    story.append(Paragraph("2. Expense Breakdown by Category", styles["heading"]))
    if cat_df.empty:
        story.append(Paragraph("No expense transactions recorded for this month.", styles["empty_msg"]))
    else:
        cat_rows = [
            [
                Paragraph("Category", styles["table_header"]),
                Paragraph("Total Spent", styles["table_header"]),
                Paragraph("Transactions", styles["table_header"]),
                Paragraph("Share of Expenses", styles["table_header"]),
            ]
        ]
        for _, r in cat_df.iterrows():
            cat_rows.append([
                Paragraph(str(r["category"]), styles["table_cell"]),
                Paragraph(_format_currency_pdf(r["total_expenses"]), styles["table_cell_right"]),
                Paragraph(str(int(r["transaction_count"])), styles["table_cell_right"]),
                Paragraph(_format_pct_pdf(r["percentage_of_total"]), styles["table_cell_right"]),
            ])
        cat_table = Table(cat_rows, colWidths=[180, 120, 100, 123])
        cat_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECONDARY),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_BG_LIGHT]),
        ]))
        story.append(cat_table)
    story.append(Spacer(1, 12))

    # Payment Method Breakdown
    story.append(Paragraph("3. Payment Method Distribution", styles["heading"]))
    if pm_df.empty:
        story.append(Paragraph("No payment method data available for this month.", styles["empty_msg"]))
    else:
        pm_rows = [
            [
                Paragraph("Payment Method", styles["table_header"]),
                Paragraph("Total Spent", styles["table_header"]),
                Paragraph("Transactions", styles["table_header"]),
                Paragraph("% Share", styles["table_header"]),
            ]
        ]
        for _, r in pm_df.iterrows():
            pm_rows.append([
                Paragraph(str(r["payment_method"]), styles["table_cell"]),
                Paragraph(_format_currency_pdf(r["total_expenses"]), styles["table_cell_right"]),
                Paragraph(str(int(r["transaction_count"])), styles["table_cell_right"]),
                Paragraph(_format_pct_pdf(r["percentage_of_total"]), styles["table_cell_right"]),
            ])
        pm_table = Table(pm_rows, colWidths=[180, 120, 100, 123])
        pm_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECONDARY),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_BG_LIGHT]),
        ]))
        story.append(pm_table)
    story.append(Spacer(1, 12))

    # Budget Performance
    story.append(Paragraph("4. Budget Utilization & Targets", styles["heading"]))
    if budget_df.empty:
        story.append(Paragraph("No category budgets were configured for this month.", styles["empty_msg"]))
    else:
        budget_rows = [
            [
                Paragraph("Category", styles["table_header"]),
                Paragraph("Budget Limit", styles["table_header"]),
                Paragraph("Actual Spent", styles["table_header"]),
                Paragraph("Remaining", styles["table_header"]),
                Paragraph("Utilization", styles["table_header"]),
                Paragraph("Status", styles["table_header"]),
            ]
        ]
        for _, r in budget_df.iterrows():
            st_color = COLOR_SUCCESS if r["status"] == "Normal" else (COLOR_WARNING if r["status"] == "Warning" else COLOR_DANGER)
            st_style = ParagraphStyle("StatStyle", parent=styles["table_cell_bold"], textColor=st_color)
            budget_rows.append([
                Paragraph(str(r["category"]), styles["table_cell"]),
                Paragraph(_format_currency_pdf(r["budget_limit"]), styles["table_cell_right"]),
                Paragraph(_format_currency_pdf(r["actual_expenses"]), styles["table_cell_right"]),
                Paragraph(_format_currency_pdf(r["remaining_budget"]), styles["table_cell_right"]),
                Paragraph(_format_pct_pdf(r["utilization_percentage"]), styles["table_cell_right"]),
                Paragraph(str(r["status"]), st_style),
            ])
        budget_table = Table(budget_rows, colWidths=[110, 85, 85, 85, 75, 83])
        budget_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECONDARY),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_BG_LIGHT]),
        ]))
        story.append(budget_table)
    story.append(Spacer(1, 12))

    # Detailed Transactions List
    story.append(Paragraph("5. Detailed Transaction Log", styles["heading"]))
    if txns_df.empty:
        story.append(Paragraph("No individual transactions found for this month.", styles["empty_msg"]))
    else:
        txn_rows = [
            [
                Paragraph("Date", styles["table_header"]),
                Paragraph("Category", styles["table_header"]),
                Paragraph("Type", styles["table_header"]),
                Paragraph("Amount", styles["table_header"]),
                Paragraph("Method", styles["table_header"]),
                Paragraph("Description", styles["table_header"]),
            ]
        ]
        for _, r in txns_df.iterrows():
            txn_rows.append([
                Paragraph(str(r["date"]), styles["table_cell"]),
                Paragraph(str(r["category"]), styles["table_cell"]),
                Paragraph(str(r["type"]), styles["table_cell"]),
                Paragraph(_format_currency_pdf(r["amount"]), styles["table_cell_right"]),
                Paragraph(str(r["payment_method"] or "-"), styles["table_cell"]),
                Paragraph(str(r["description"] or "-"), styles["table_cell"]),
            ])
        txn_table = Table(txn_rows, colWidths=[65, 85, 55, 75, 75, 168], repeatRows=1)
        txn_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_BG_LIGHT]),
        ]))
        story.append(txn_table)

    # Build document with custom canvas
    doc.build(story, canvasmaker=NumberedCanvas)
    logger.info("Generated monthly PDF report: %s", out_file)
    return out_file


# ---------------------------------------------------------------------------
# 2. Custom Period PDF Report
# ---------------------------------------------------------------------------

def generate_custom_period_report(
    start_date: str,
    end_date: str,
    db_path: Optional[Union[Path, str]] = None,
    output_path: Optional[Union[Path, str]] = None,
) -> Path:
    """
    Generate a comprehensive financial PDF report for a customized date range.

    Parameters
    ----------
    start_date : str
        Start date (YYYY-MM-DD).
    end_date : str
        End date (YYYY-MM-DD).
    db_path : Optional[Path | str]
        Database path.
    output_path : Optional[Path | str]
        Optional custom output path.

    Returns
    -------
    Path
        Path to the generated PDF document.
    """
    validate_transaction_date(start_date)
    validate_transaction_date(end_date)
    if start_date > end_date:
        raise ValueError(f"Start date '{start_date}' cannot be after end date '{end_date}'")

    if output_path is None:
        target_dir = REPORTS_DIR / "custom_reports"
        target_dir.mkdir(parents=True, exist_ok=True)
        out_file = target_dir / f"expense_report_{start_date}_to_{end_date}.pdf"
    else:
        out_file = Path(output_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)

    overview = get_financial_overview(start_date=start_date, end_date=end_date, db_path=db_path)
    cat_df = get_category_wise_expenses(start_date=start_date, end_date=end_date, db_path=db_path)
    pm_df = get_payment_method_summary(start_date=start_date, end_date=end_date, db_path=db_path)
    txns_df = get_filtered_transactions(start_date=start_date, end_date=end_date, db_path=db_path)

    doc = SimpleDocTemplate(
        str(out_file),
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=42,
        bottomMargin=42,
    )
    styles = _create_report_styles()
    story: list[Any] = []

    gen_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    story.append(Paragraph(f"Financial Period Report ({start_date} to {end_date})", styles["title"]))
    story.append(Paragraph(f"Generated on {gen_time} | Currency: INR (Rs.)", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=COLOR_PRIMARY, spaceAfter=14))

    # Executive Summary
    story.append(Paragraph("1. Executive Summary", styles["heading"]))
    kpi_data = [
        [
            Paragraph("Total Income", styles["table_header"]),
            Paragraph("Total Expenses", styles["table_header"]),
            Paragraph("Net Savings", styles["table_header"]),
            Paragraph("Savings Rate", styles["table_header"]),
            Paragraph("Transactions", styles["table_header"]),
        ],
        [
            Paragraph(_format_currency_pdf(overview["total_income"]), styles["table_cell_bold"]),
            Paragraph(_format_currency_pdf(overview["total_expenses"]), styles["table_cell_bold"]),
            Paragraph(_format_currency_pdf(overview["net_savings"]), styles["table_cell_bold"]),
            Paragraph(_format_pct_pdf(overview["savings_rate"]), styles["table_cell_bold"]),
            Paragraph(str(overview["transaction_count"]), styles["table_cell_bold"]),
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[104, 104, 104, 104, 107])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("BACKGROUND", (0, 1), (-1, 1), COLOR_BG_LIGHT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 12))

    # Category Expenses
    story.append(Paragraph("2. Category Expenses", styles["heading"]))
    if cat_df.empty:
        story.append(Paragraph("No expenses recorded for this date range.", styles["empty_msg"]))
    else:
        cat_rows = [
            [
                Paragraph("Category", styles["table_header"]),
                Paragraph("Total Spent", styles["table_header"]),
                Paragraph("Transactions", styles["table_header"]),
                Paragraph("% Share", styles["table_header"]),
            ]
        ]
        for _, r in cat_df.iterrows():
            cat_rows.append([
                Paragraph(str(r["category"]), styles["table_cell"]),
                Paragraph(_format_currency_pdf(r["total_expenses"]), styles["table_cell_right"]),
                Paragraph(str(int(r["transaction_count"])), styles["table_cell_right"]),
                Paragraph(_format_pct_pdf(r["percentage_of_total"]), styles["table_cell_right"]),
            ])
        cat_table = Table(cat_rows, colWidths=[180, 120, 100, 123])
        cat_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECONDARY),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_BG_LIGHT]),
        ]))
        story.append(cat_table)
    story.append(Spacer(1, 12))

    # Payment Methods
    story.append(Paragraph("3. Payment Method Distribution", styles["heading"]))
    if pm_df.empty:
        story.append(Paragraph("No payment method data recorded for this date range.", styles["empty_msg"]))
    else:
        pm_rows = [
            [
                Paragraph("Payment Method", styles["table_header"]),
                Paragraph("Total Spent", styles["table_header"]),
                Paragraph("Transactions", styles["table_header"]),
                Paragraph("% Share", styles["table_header"]),
            ]
        ]
        for _, r in pm_df.iterrows():
            pm_rows.append([
                Paragraph(str(r["payment_method"]), styles["table_cell"]),
                Paragraph(_format_currency_pdf(r["total_expenses"]), styles["table_cell_right"]),
                Paragraph(str(int(r["transaction_count"])), styles["table_cell_right"]),
                Paragraph(_format_pct_pdf(r["percentage_of_total"]), styles["table_cell_right"]),
            ])
        pm_table = Table(pm_rows, colWidths=[180, 120, 100, 123])
        pm_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECONDARY),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_BG_LIGHT]),
        ]))
        story.append(pm_table)
    story.append(Spacer(1, 12))

    # Detailed Transactions List
    story.append(Paragraph("4. Transaction Details", styles["heading"]))
    if txns_df.empty:
        story.append(Paragraph("No transactions recorded for this period.", styles["empty_msg"]))
    else:
        txn_rows = [
            [
                Paragraph("Date", styles["table_header"]),
                Paragraph("Category", styles["table_header"]),
                Paragraph("Type", styles["table_header"]),
                Paragraph("Amount", styles["table_header"]),
                Paragraph("Method", styles["table_header"]),
                Paragraph("Description", styles["table_header"]),
            ]
        ]
        for _, r in txns_df.iterrows():
            txn_rows.append([
                Paragraph(str(r["date"]), styles["table_cell"]),
                Paragraph(str(r["category"]), styles["table_cell"]),
                Paragraph(str(r["type"]), styles["table_cell"]),
                Paragraph(_format_currency_pdf(r["amount"]), styles["table_cell_right"]),
                Paragraph(str(r["payment_method"] or "-"), styles["table_cell"]),
                Paragraph(str(r["description"] or "-"), styles["table_cell"]),
            ])
        txn_table = Table(txn_rows, colWidths=[65, 85, 55, 75, 75, 168], repeatRows=1)
        txn_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_BG_LIGHT]),
        ]))
        story.append(txn_table)

    doc.build(story, canvasmaker=NumberedCanvas)
    logger.info("Generated custom period PDF report: %s", out_file)
    return out_file


# ---------------------------------------------------------------------------
# 3. Transaction PDF Report
# ---------------------------------------------------------------------------

def generate_transaction_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    payment_method: Optional[str] = None,
    search_term: Optional[str] = None,
    month: Optional[Union[int, str]] = None,
    year: Optional[Union[int, str]] = None,
    db_path: Optional[Union[Path, str]] = None,
    output_path: Optional[Union[Path, str]] = None,
) -> Path:
    """
    Generate a detailed PDF listing of transactions matching optional filters.

    Parameters
    ----------
    db_path : Optional[Path | str]
        Database path.
    output_path : Optional[Path | str]
        Optional custom output path.

    Returns
    -------
    Path
        Path to the generated PDF.
    """
    if output_path is None:
        target_dir = REPORTS_DIR / "transaction_reports"
        target_dir.mkdir(parents=True, exist_ok=True)
        t_stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = target_dir / f"transactions_report_{t_stamp}.pdf"
    else:
        out_file = Path(output_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)

    txns_df = get_filtered_transactions(
        start_date=start_date,
        end_date=end_date,
        month=month,
        year=year,
        category=category,
        transaction_type=transaction_type,
        payment_method=payment_method,
        search_term=search_term,
        db_path=db_path,
    )

    doc = SimpleDocTemplate(
        str(out_file),
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=42,
        bottomMargin=42,
    )
    styles = _create_report_styles()
    story: list[Any] = []

    gen_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    story.append(Paragraph("Transaction Detail Report", styles["title"]))
    story.append(Paragraph(f"Generated on {gen_time} | Matching Records: {len(txns_df)}", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=COLOR_PRIMARY, spaceAfter=14))

    if txns_df.empty:
        story.append(Paragraph("No transactions match the selected criteria.", styles["empty_msg"]))
    else:
        rows = [
            [
                Paragraph("ID", styles["table_header"]),
                Paragraph("Date", styles["table_header"]),
                Paragraph("Category", styles["table_header"]),
                Paragraph("Type", styles["table_header"]),
                Paragraph("Amount", styles["table_header"]),
                Paragraph("Method", styles["table_header"]),
                Paragraph("Description", styles["table_header"]),
            ]
        ]
        for _, r in txns_df.iterrows():
            rows.append([
                Paragraph(str(r["id"]), styles["table_cell"]),
                Paragraph(str(r["date"]), styles["table_cell"]),
                Paragraph(str(r["category"]), styles["table_cell"]),
                Paragraph(str(r["type"]), styles["table_cell"]),
                Paragraph(_format_currency_pdf(r["amount"]), styles["table_cell_right"]),
                Paragraph(str(r["payment_method"] or "-"), styles["table_cell"]),
                Paragraph(str(r["description"] or "-"), styles["table_cell"]),
            ])
        txn_table = Table(rows, colWidths=[35, 65, 80, 50, 75, 75, 143], repeatRows=1)
        txn_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_BG_LIGHT]),
        ]))
        story.append(txn_table)

    doc.build(story, canvasmaker=NumberedCanvas)
    logger.info("Generated transaction detail PDF report: %s", out_file)
    return out_file


# ---------------------------------------------------------------------------
# 4. CSV Export with Formula Injection Protection
# ---------------------------------------------------------------------------

EXPORT_COLUMNS = ["id", "date", "category", "type", "amount", "payment_method", "description"]


def export_transactions_csv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    payment_method: Optional[str] = None,
    search_term: Optional[str] = None,
    month: Optional[Union[int, str]] = None,
    year: Optional[Union[int, str]] = None,
    db_path: Optional[Union[Path, str]] = None,
    output_path: Optional[Union[Path, str]] = None,
) -> str:
    """
    Export transactions to CSV with UTF-8 BOM encoding and formula injection protection.

    Formula characters (=, +, -, @) at the beginning of text columns are safely
    escaped with a leading single quote (') to protect spreadsheet users.
    Original database records are never modified.

    Parameters
    ----------
    output_path : Optional[Path | str]
        If provided, writes the CSV to this file path.
    db_path : Optional[Path | str]
        Database path.

    Returns
    -------
    str
        The serialized CSV content string (UTF-8).
    """
    txns = get_filtered_transactions(
        start_date=start_date,
        end_date=end_date,
        month=month,
        year=year,
        category=category,
        transaction_type=transaction_type,
        payment_method=payment_method,
        search_term=search_term,
        db_path=db_path,
    )

    if txns.empty:
        export_df = pd.DataFrame(columns=EXPORT_COLUMNS)
    else:
        export_df = txns[EXPORT_COLUMNS].copy()

    # Apply CSV formula injection protection to string columns
    sanitized_df = sanitize_dataframe_for_csv(export_df)

    # Serialize to CSV with UTF-8 with BOM (utf-8-sig)
    csv_bytes = sanitized_df.to_csv(index=False, encoding="utf-8-sig")

    if output_path is not None:
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(csv_bytes, encoding="utf-8-sig")
        logger.info("Exported transactions CSV to: %s", target)
        return target

    return csv_bytes


def export_all_transactions_csv(
    db_path: Optional[Union[Path, str]] = None,
    output_path: Optional[Union[Path, str]] = None,
) -> Union[Path, str]:
    """Convenience wrapper exporting all transactions without filters."""
    return export_transactions_csv(db_path=db_path, output_path=output_path)


# ---------------------------------------------------------------------------
# ReportGenerator OOP Wrapper
# ---------------------------------------------------------------------------

class ReportGenerator:
    """
    Object-oriented report generator for PDF compilation and CSV exports.

    Parameters
    ----------
    db_path : Optional[Path | str]
        Optional path to the SQLite database file.
    """

    def __init__(self, db_path: Optional[Union[Path, str]] = None) -> None:
        self.db_path = db_path

    def generate_monthly_pdf(self, month: str, output_path: Optional[Union[Path, str]] = None) -> Path:
        """Generate monthly PDF report."""
        return generate_monthly_report(month=month, db_path=self.db_path, output_path=output_path)

    def generate_custom_period_pdf(
        self, start_date: str, end_date: str, output_path: Optional[Union[Path, str]] = None
    ) -> Path:
        """Generate custom period PDF report."""
        return generate_custom_period_report(
            start_date=start_date, end_date=end_date, db_path=self.db_path, output_path=output_path
        )

    def generate_transaction_pdf(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_path: Optional[Union[Path, str]] = None,
    ) -> Path:
        """Generate transaction list PDF report."""
        return generate_transaction_report(
            start_date=start_date, end_date=end_date, db_path=self.db_path, output_path=output_path
        )

    def export_csv(
        self,
        month: Optional[Union[int, str]] = None,
        year: Optional[Union[int, str]] = None,
        output_path: Optional[Union[Path, str]] = None,
    ) -> str:
        """Export monthly or filtered transactions to CSV."""
        return export_transactions_csv(month=month, year=year, db_path=self.db_path, output_path=output_path)

    def export_all_csv(self, output_path: Optional[Union[Path, str]] = None) -> Union[Path, str]:
        """Export all transactions to CSV."""
        return export_all_transactions_csv(db_path=self.db_path, output_path=output_path)

    # Reusable method aliases
    def monthly_report(self, month: str, output_path: Optional[Union[Path, str]] = None) -> Path:
        return self.generate_monthly_pdf(month=month, output_path=output_path)

    def custom_period_report(
        self, start_date: str, end_date: str, output_path: Optional[Union[Path, str]] = None
    ) -> Path:
        return self.generate_custom_period_pdf(start_date=start_date, end_date=end_date, output_path=output_path)

    def transaction_report(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        transaction_type: Optional[str] = None,
        payment_method: Optional[str] = None,
        output_path: Optional[Union[Path, str]] = None,
    ) -> Path:
        return generate_transaction_report(
            start_date=start_date,
            end_date=end_date,
            category=category,
            transaction_type=transaction_type,
            payment_method=payment_method,
            db_path=self.db_path,
            output_path=output_path,
        )

    def export_transactions(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        transaction_type: Optional[str] = None,
        payment_method: Optional[str] = None,
        output_path: Optional[Union[Path, str]] = None,
    ) -> Union[Path, str]:
        return export_transactions_csv(
            start_date=start_date,
            end_date=end_date,
            category=category,
            transaction_type=transaction_type,
            payment_method=payment_method,
            db_path=self.db_path,
            output_path=output_path,
        )

    def export_all_transactions(self, output_path: Optional[Union[Path, str]] = None) -> Union[Path, str]:
        return self.export_all_csv(output_path=output_path)
