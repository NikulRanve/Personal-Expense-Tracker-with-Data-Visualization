"""
tests/test_report_generator.py — Unit & Integration Tests for ReportLab PDF Generation
====================================================================================
Tests cover:
  - Monthly PDF financial report generation.
  - Custom date range report generation.
  - Transaction listing report generation.
  - Multi-page pagination and NumberedCanvas page numbering.
  - Empty database graceful handling.
  - Error handling for invalid months and dates.
  - ReportGenerator OOP class wrapper.
  - Content inspection via pypdf text extraction.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from pypdf import PdfReader

from budget_manager import set_budget
from database import initialise_database, seed_categories
from expense_manager import add_transaction
from report_generator import (
    ReportGenerator,
    generate_custom_period_report,
    generate_monthly_report,
    generate_transaction_report,
)


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """Fixture providing a temporary database populated with realistic records."""
    db_file = tmp_path / "test_reports.db"
    initialise_database(db_file)
    seed_categories(db_file)

    # Seed transactions — only use categories from seed_categories()
    add_transaction("2026-11-01", "Salary", 50000.0, "Bank Transfer", "Monthly Salary", "Income", db_path=db_file)
    add_transaction("2026-11-05", "Food", 1200.0, "UPI", "Groceries", "Expense", db_path=db_file)
    add_transaction("2026-11-10", "Transportation", 450.0, "Credit Card", "Fuel", "Expense", db_path=db_file)
    add_transaction("2026-11-15", "Shopping", 800.0, "Debit Card", "Clothing", "Expense", db_path=db_file)
    add_transaction("2026-11-20", "Food", 650.0, "Cash", "Dinner", "Expense", db_path=db_file)

    # Seed budget
    set_budget("Food", "2026-11", 5000.0, db_path=db_file)
    set_budget("Transportation", "2026-11", 2000.0, db_path=db_file)

    return db_file


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Fixture providing a clean database with only categories."""
    db_file = tmp_path / "test_empty.db"
    initialise_database(db_file)
    seed_categories(db_file)
    return db_file


class TestMonthlyReport:
    """Tests for generate_monthly_report."""

    def test_generate_monthly_report_creates_valid_pdf(self, populated_db: Path, tmp_path: Path):
        output_pdf = tmp_path / "monthly_report.pdf"
        result_path = generate_monthly_report("2026-11", db_path=populated_db, output_path=output_pdf)

        assert result_path == output_pdf
        assert output_pdf.exists()
        assert output_pdf.stat().st_size > 0

        # Verify PDF structure using pypdf
        reader = PdfReader(str(output_pdf))
        assert len(reader.pages) >= 1

        full_text = " ".join(page.extract_text() for page in reader.pages)
        assert "Monthly Financial Statement" in full_text
        assert "2026-11" in full_text
        assert "50,000.00" in full_text  # Total Income
        assert "3,100.00" in full_text   # Total Expenses (1200+450+800+650)
        assert "Page 1 of" in full_text

    def test_monthly_report_empty_database(self, empty_db: Path, tmp_path: Path):
        output_pdf = tmp_path / "empty_monthly.pdf"
        result_path = generate_monthly_report("2026-11", db_path=empty_db, output_path=output_pdf)

        assert result_path.exists()
        reader = PdfReader(str(output_pdf))
        full_text = " ".join(page.extract_text() for page in reader.pages)
        assert "Monthly Financial Statement" in full_text
        assert "0.00" in full_text

    def test_monthly_report_invalid_month_raises_error(self, populated_db: Path):
        with pytest.raises(ValueError, match="Invalid month"):
            generate_monthly_report("2026-13", db_path=populated_db)

        with pytest.raises(ValueError, match="Invalid month"):
            generate_monthly_report("invalid", db_path=populated_db)

    def test_monthly_report_default_output_path(self, populated_db: Path):
        result_path = generate_monthly_report("2026-11", db_path=populated_db)
        assert result_path.exists()
        assert result_path.suffix == ".pdf"
        # Cleanup temp file
        if result_path.exists():
            os.remove(result_path)


class TestCustomPeriodReport:
    """Tests for generate_custom_period_report."""

    def test_generate_custom_period_report(self, populated_db: Path, tmp_path: Path):
        output_pdf = tmp_path / "custom_report.pdf"
        result_path = generate_custom_period_report(
            "2026-11-01", "2026-11-15", db_path=populated_db, output_path=output_pdf
        )

        assert result_path.exists()
        reader = PdfReader(str(output_pdf))
        assert len(reader.pages) >= 1

        full_text = " ".join(page.extract_text() for page in reader.pages)
        assert "Financial Period Report" in full_text
        assert "2026-11-01 to" in full_text
        assert "2026-11-15" in full_text
        assert "Income" in full_text
        assert "Expenses" in full_text

    def test_custom_period_report_invalid_dates(self, populated_db: Path):
        # start > end
        with pytest.raises(ValueError, match="cannot be after end date"):
            generate_custom_period_report("2026-11-20", "2026-11-10", db_path=populated_db)

        # bad format
        with pytest.raises(ValueError, match="Invalid date"):
            generate_custom_period_report("invalid", "2026-11-10", db_path=populated_db)


class TestTransactionListingReport:
    """Tests for generate_transaction_report."""

    def test_transaction_report_all(self, populated_db: Path, tmp_path: Path):
        output_pdf = tmp_path / "all_trans.pdf"
        result_path = generate_transaction_report(db_path=populated_db, output_path=output_pdf)

        assert result_path.exists()
        reader = PdfReader(str(output_pdf))
        full_text = " ".join(page.extract_text() for page in reader.pages)
        assert "Transaction Detail Report" in full_text
        assert "Groceries" in full_text
        assert "Monthly Salary" in full_text

    def test_transaction_report_filtered(self, populated_db: Path, tmp_path: Path):
        output_pdf = tmp_path / "filtered_trans.pdf"
        result_path = generate_transaction_report(
            category="Food",
            transaction_type="Expense",
            db_path=populated_db,
            output_path=output_pdf,
        )

        assert result_path.exists()
        reader = PdfReader(str(output_pdf))
        full_text = " ".join(page.extract_text() for page in reader.pages)
        assert "Groceries" in full_text
        assert "Monthly Salary" not in full_text

    def test_multipage_pagination(self, tmp_path: Path):
        """Verify pagination handles large datasets cleanly across multiple pages."""
        db_file = tmp_path / "large_trans.db"
        initialise_database(db_file)
        seed_categories(db_file)

        # Insert 60 transactions to force multiple pages
        for i in range(1, 61):
            add_transaction(
                "2026-11-01",
                "Food",
                100.0 + i,
                "UPI",
                f"Item purchase {i:03d} with extra descriptive detail",
                "Expense",
                db_path=db_file,
            )

        output_pdf = tmp_path / "large_report.pdf"
        result_path = generate_transaction_report(db_path=db_file, output_path=output_pdf)

        assert result_path.exists()
        reader = PdfReader(str(output_pdf))
        # 60 rows plus header table should span 2 or 3 pages
        assert len(reader.pages) > 1

        page_texts = [page.extract_text() for page in reader.pages]
        assert f"Page {len(reader.pages)} of {len(reader.pages)}" in page_texts[-1]


class TestReportGeneratorClass:
    """Test ReportGenerator OOP class interface."""

    def test_report_generator_class(self, populated_db: Path, tmp_path: Path):
        rg = ReportGenerator(db_path=populated_db)
        out_m = tmp_path / "rg_monthly.pdf"
        out_c = tmp_path / "rg_custom.pdf"
        out_t = tmp_path / "rg_trans.pdf"

        res_m = rg.monthly_report("2026-11", output_path=out_m)
        res_c = rg.custom_period_report("2026-11-01", "2026-11-10", output_path=out_c)
        res_t = rg.transaction_report(output_path=out_t)

        assert res_m.exists()
        assert res_c.exists()
        assert res_t.exists()
