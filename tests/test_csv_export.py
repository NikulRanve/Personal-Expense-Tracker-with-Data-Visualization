"""
tests/test_csv_export.py — Tests for Sanitized CSV Transaction Export
====================================================================
Tests cover:
  - Full CSV export and filtered CSV export.
  - Column consistency with standard schema.
  - Formula Injection (CSV injection) security:
      Values starting with =, +, -, @, \\t, \\r are prefixed with '
      SQLite database records remain completely unaffected.
  - UTF-8 with BOM (utf-8-sig) encoding verification.
  - Empty database export handling.
  - Return as file Path or string.
"""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
import pytest

from database import initialise_database, seed_categories
from expense_manager import add_transaction, get_transaction
from report_generator import (
    ReportGenerator,
    export_all_transactions_csv,
    export_transactions_csv,
    sanitize_csv_value,
    sanitize_dataframe_for_csv,
)


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """Fixture providing a temporary database with varied transactions."""
    db_file = tmp_path / "test_csv.db"
    initialise_database(db_file)
    seed_categories(db_file)

    add_transaction("2026-11-01", "Salary", 40000.0, "Bank Transfer", "Monthly Income", "Income", db_path=db_file)
    add_transaction("2026-11-02", "Food", 350.0, "UPI", "Coffee and Snacks", "Expense", db_path=db_file)
    add_transaction("2026-11-03", "Transportation", 200.0, "Cash", "Metro card", "Expense", db_path=db_file)
    add_transaction("2026-11-04", "Food", 1200.0, "Credit Card", "Dinner", "Expense", db_path=db_file)

    return db_file


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Fixture providing a clean database with only categories."""
    db_file = tmp_path / "test_empty_csv.db"
    initialise_database(db_file)
    seed_categories(db_file)
    return db_file


class TestSanitizeCsvValue:
    """Tests for formula injection sanitizer."""

    @pytest.mark.parametrize(
        "dangerous_input,expected_output",
        [
            ("=1+1", "'=1+1"),
            ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
            ("-5+2", "'-5+2"),
            ("@SUM(A1:A10)", "'@SUM(A1:A10)"),
            ("\tcalc", "'\tcalc"),
            ("\rpayload", "'\rpayload"),
            ("   =1+1", "'=1+1"),  # leading spaces then formula char
        ],
    )
    def test_dangerous_characters_prefixed(self, dangerous_input: str, expected_output: str):
        assert sanitize_csv_value(dangerous_input) == expected_output

    @pytest.mark.parametrize(
        "safe_input",
        [
            "Normal Description",
            "Lunch at cafe",
            "12345",
            "",
            None,
            42,
            3.14,
        ],
    )
    def test_safe_values_unmodified(self, safe_input):
        assert sanitize_csv_value(safe_input) == safe_input


class TestCsvExport:
    """Tests for export_transactions_csv and export_all_transactions_csv."""

    def test_export_all_transactions_returns_csv_string(self, populated_db: Path):
        csv_str = export_all_transactions_csv(db_path=populated_db)
        assert isinstance(csv_str, str)

        lines = [line.strip() for line in csv_str.strip().split("\n") if line.strip()]
        assert len(lines) == 5  # Header + 4 transactions
        assert lines[0] == "id,date,category,type,amount,payment_method,description"

    def test_export_transactions_to_file_with_bom(self, populated_db: Path, tmp_path: Path):
        out_file = tmp_path / "transactions.csv"
        result_path = export_transactions_csv(output_path=out_file, db_path=populated_db)

        assert result_path == out_file
        assert out_file.exists()

        raw_bytes = out_file.read_bytes()
        # Verify UTF-8 with BOM prefix
        assert raw_bytes.startswith(b"\xef\xbb\xbf")

        # Parse with pandas
        df = pd.read_csv(out_file, encoding="utf-8-sig")
        assert list(df.columns) == ["id", "date", "category", "type", "amount", "payment_method", "description"]
        assert len(df) == 4

    def test_export_filtered_transactions(self, populated_db: Path):
        csv_str = export_transactions_csv(
            category="Food",
            transaction_type="Expense",
            db_path=populated_db,
        )
        assert isinstance(csv_str, str)
        assert "Coffee and Snacks" in csv_str
        assert "Dinner" in csv_str
        assert "Monthly Income" not in csv_str
        assert "Metro card" not in csv_str

    def test_formula_injection_prevention_in_csv_export(self, tmp_path: Path):
        """Ensure formula injection strings are neutralized in CSV while DB remains unchanged."""
        db_file = tmp_path / "injection_test.db"
        initialise_database(db_file)
        seed_categories(db_file)

        raw_desc = "=1+1"
        t_id = add_transaction("2026-11-01", "Food", 100.0, "UPI", raw_desc, "Expense", db_path=db_file)

        # Export CSV
        csv_str = export_all_transactions_csv(db_path=db_file)
        assert "'=1+1" in csv_str

        # Verify DB transaction is untouched (no apostrophe stored in database)
        db_record = get_transaction(t_id, db_path=db_file)
        assert db_record is not None
        assert db_record["description"] == "=1+1"

    def test_empty_database_csv_export(self, empty_db: Path, tmp_path: Path):
        out_file = tmp_path / "empty.csv"
        result_path = export_all_transactions_csv(output_path=out_file, db_path=empty_db)

        assert result_path.exists()
        df = pd.read_csv(out_file, encoding="utf-8-sig")
        assert len(df) == 0
        assert list(df.columns) == ["id", "date", "category", "type", "amount", "payment_method", "description"]

    def test_report_generator_class_csv_methods(self, populated_db: Path, tmp_path: Path):
        rg = ReportGenerator(db_path=populated_db)
        out_all = tmp_path / "rg_all.csv"
        res_all = rg.export_all_transactions(output_path=out_all)

        assert res_all.exists()
        csv_str = rg.export_transactions(category="Food")
        assert "Coffee and Snacks" in csv_str
