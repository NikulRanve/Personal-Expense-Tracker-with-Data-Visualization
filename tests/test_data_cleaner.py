"""
tests/test_data_cleaner.py — Tests for Transaction Cleaning & Validation
========================================================================
Covers:
  - Valid income and expense records
  - Missing and invalid calendar dates (2026-02-30, 23-11-2026, 2026-99-45)
  - Amount validation: missing, zero, negative, non-numeric, infinite, NaN
  - Category validation: missing, unknown, category/type mismatch
  - Transaction type validation: normalization, invalid types
  - Whitespace normalization across fields
  - Missing optional fields handling (payment_method, description)
  - Multi-error reporting per rejected row
  - Duplicate detection within CSV (in-file duplicates)
  - Duplicate candidate detection against existing SQLite database records
  - CleaningResult output contract and row-accounting invariant:
      total_rows == valid_count + rejected_count + duplicate_count
  - validate_single_expense helper
  - DataCleaner class wrapper
"""

from __future__ import annotations

import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database import (
    create_tables,
    get_connection,
    initialise_database,
)
from data_cleaner import (
    CleaningResult,
    DataCleaner,
    clean_transactions,
    validate_amount_field,
    validate_category_field,
    validate_date_field,
    validate_single_expense,
    validate_type_field,
)


@pytest.fixture
def mock_categories() -> dict[str, str]:
    """Standard seeded categories for pure unit tests without disk DB."""
    return {
        "Food": "Expense",
        "Transportation": "Expense",
        "Utilities": "Expense",
        "Entertainment": "Expense",
        "Healthcare": "Expense",
        "Shopping": "Expense",
        "Salary": "Income",
        "Other Income": "Income",
    }


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Provide a fresh initialized temporary SQLite database."""
    db_file = tmp_path / "temp_expense_tracker.db"
    initialise_database(db_file)
    return db_file


# ---------------------------------------------------------------------------
# Individual Field Validator Tests
# ---------------------------------------------------------------------------

class TestDateFieldValidation:
    def test_valid_calendar_date(self):
        d, err = validate_date_field("2026-11-23")
        assert err is None
        assert d == "2026-11-23"

    def test_whitespace_padded_date(self):
        d, err = validate_date_field("  2026-11-23  ")
        assert err is None
        assert d == "2026-11-23"

    def test_missing_date(self):
        _, err1 = validate_date_field(None)
        assert "Missing date" in err1
        _, err2 = validate_date_field("   ")
        assert "Missing date" in err2
        _, err3 = validate_date_field(float("nan"))
        assert "Missing date" in err3

    def test_invalid_calendar_date_feb_30(self):
        _, err = validate_date_field("2026-02-30")
        assert err is not None
        assert "Invalid calendar date" in err

    def test_reversed_format_date(self):
        _, err = validate_date_field("23-11-2026")
        assert err is not None
        assert "Invalid calendar date" in err

    def test_out_of_range_month(self):
        _, err = validate_date_field("2026-99-45")
        assert err is not None
        assert "Invalid calendar date" in err


class TestAmountFieldValidation:
    def test_valid_numeric_amounts(self):
        val, err = validate_amount_field("250.50")
        assert err is None
        assert val == 250.50

        val2, err2 = validate_amount_field(1000)
        assert err2 is None
        assert val2 == 1000.0

        val3, err3 = validate_amount_field(" 1,234.56 ")
        assert err3 is None
        assert val3 == 1234.56

    def test_missing_amount(self):
        _, err1 = validate_amount_field(None)
        assert "Missing amount" in err1
        _, err2 = validate_amount_field("")
        assert "Missing amount" in err2
        _, err3 = validate_amount_field(float("nan"))
        assert "Missing amount" in err3

    def test_zero_amount_rejected(self):
        _, err = validate_amount_field("0")
        assert "Zero amount" in err
        _, err2 = validate_amount_field(0.0)
        assert "Zero amount" in err2

    def test_negative_amount_rejected(self):
        _, err = validate_amount_field("-50.00")
        assert "Negative amount" in err
        _, err2 = validate_amount_field(-10)
        assert "Negative amount" in err2

    def test_non_numeric_amount_rejected(self):
        _, err = validate_amount_field("abc")
        assert "Non-numeric amount" in err

    def test_infinite_amount_rejected(self):
        _, err = validate_amount_field(float("inf"))
        assert "infinite" in err
        _, err2 = validate_amount_field(float("-inf"))
        assert "infinite" in err2


class TestTypeFieldValidation:
    def test_valid_types_and_case_normalization(self):
        t1, err1 = validate_type_field("income")
        assert err1 is None
        assert t1 == "Income"

        t2, err2 = validate_type_field("  EXPENSE  ")
        assert err2 is None
        assert t2 == "Expense"

    def test_missing_type(self):
        _, err = validate_type_field(None)
        assert "Missing transaction type" in err
        _, err2 = validate_type_field("   ")
        assert "Missing transaction type" in err2

    def test_invalid_type_rejected(self):
        _, err = validate_type_field("Transfer")
        assert "Invalid transaction type" in err


class TestCategoryFieldValidation:
    def test_valid_category_matching(self, mock_categories: dict[str, str]):
        cat, err = validate_category_field("food", "Expense", mock_categories)
        assert err is None
        assert cat == "Food"  # canonical casing

    def test_missing_category(self, mock_categories: dict[str, str]):
        _, err = validate_category_field("", "Expense", mock_categories)
        assert "Missing category" in err
        _, err2 = validate_category_field(None, "Expense", mock_categories)
        assert "Missing category" in err2

    def test_unknown_category(self, mock_categories: dict[str, str]):
        _, err = validate_category_field("Cryptocurrency", "Expense", mock_categories)
        assert "Unknown category" in err

    def test_category_type_mismatch(self, mock_categories: dict[str, str]):
        # 'Food' is an Expense category; pairing it with Income type must fail
        _, err = validate_category_field("Food", "Income", mock_categories)
        assert "Category type mismatch" in err

        # 'Salary' is an Income category; pairing it with Expense type must fail
        _, err2 = validate_category_field("Salary", "Expense", mock_categories)
        assert "Category type mismatch" in err2


# ---------------------------------------------------------------------------
# Full Pipeline: clean_transactions Tests
# ---------------------------------------------------------------------------

class TestCleanTransactionsPipeline:
    def test_valid_expense_record(self, mock_categories: dict[str, str]):
        data = {
            "date": ["2026-11-01"],
            "category": ["Food"],
            "amount": ["150.00"],
            "payment_method": ["UPI"],
            "description": ["Lunch"],
            "type": ["Expense"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.total_rows == 1
        assert result.valid_count == 1
        assert result.rejected_count == 0
        assert result.duplicate_count == 0

        row = result.valid_transactions.iloc[0]
        assert row["date"] == "2026-11-01"
        assert row["category"] == "Food"
        assert row["amount"] == 150.00
        assert row["type"] == "Expense"

    def test_valid_income_record(self, mock_categories: dict[str, str]):
        data = {
            "date": ["2026-11-02"],
            "category": ["Salary"],
            "amount": ["50000"],
            "payment_method": ["Bank Transfer"],
            "description": ["November Salary"],
            "type": ["Income"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.valid_count == 1
        assert result.rejected_count == 0
        row = result.valid_transactions.iloc[0]
        assert row["type"] == "Income"
        assert row["amount"] == 50000.0

    def test_whitespace_normalization_across_all_fields(self, mock_categories: dict[str, str]):
        data = {
            " Date ": ["  2026-11-05  "],
            " Category ": ["  food  "],
            " Amount ": ["  250.75  "],
            " Payment Method ": ["  credit card  "],
            " Description ": ["  dinner with team  "],
            " Type ": ["  expense  "],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.valid_count == 1
        row = result.valid_transactions.iloc[0]
        assert row["date"] == "2026-11-05"
        assert row["category"] == "Food"
        assert row["amount"] == 250.75
        assert row["payment_method"] == "credit card"
        assert row["description"] == "dinner with team"
        assert row["type"] == "Expense"

    def test_missing_optional_fields_represented_as_none(self, mock_categories: dict[str, str]):
        data = {
            "date": ["2026-11-01"],
            "category": ["Food"],
            "amount": ["50"],
            "payment_method": [""],
            "description": [None],
            "type": ["Expense"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.valid_count == 1
        row = result.valid_transactions.iloc[0]
        assert row["payment_method"] is None
        assert row["description"] is None

    def test_missing_required_column_raises_value_error(self):
        data = {"date": ["2026-11-01"], "amount": [100]}
        df = pd.DataFrame(data)
        with pytest.raises(ValueError, match="missing required column"):
            clean_transactions(df)

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = clean_transactions(df)
        assert result.total_rows == 0
        assert result.valid_count == 0
        assert result.rejected_count == 0
        assert result.duplicate_count == 0


class TestRejectionReporting:
    """Test invalid row rejection details and multi-error capturing."""

    def test_invalid_calendar_date_rejected(self, mock_categories: dict[str, str]):
        data = {
            "date": ["2026-02-30"],
            "category": ["Food"],
            "amount": [100],
            "payment_method": ["Cash"],
            "description": ["Invalid date test"],
            "type": ["Expense"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.valid_count == 0
        assert result.rejected_count == 1
        rej = result.rejected_transactions.iloc[0]
        assert "Invalid calendar date" in rej["rejection_reason"]
        assert rej["csv_row_number"] == 2

    def test_multiple_errors_captured_for_single_row(self, mock_categories: dict[str, str]):
        # Row has: invalid date + negative amount + unknown category + invalid type
        data = {
            "date": ["2026-99-45"],
            "category": ["BitcoinMining"],
            "amount": ["-150.00"],
            "payment_method": ["Crypto"],
            "description": ["Bad row"],
            "type": ["Transfer"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.valid_count == 0
        assert result.rejected_count == 1
        rej = result.rejected_transactions.iloc[0]

        reasons = rej["rejection_reasons"]
        assert len(reasons) >= 3
        reason_str = rej["rejection_reason"]
        assert "Invalid calendar date" in reason_str
        assert "Negative amount" in reason_str
        assert "Invalid transaction type" in reason_str
        assert "Unknown category" in reason_str

    def test_original_values_preserved_in_rejected_dataframe(self, mock_categories: dict[str, str]):
        data = {
            "date": ["bad_date"],
            "category": ["Food"],
            "amount": ["zero"],
            "payment_method": ["Cash"],
            "description": ["Test"],
            "type": ["Expense"],
            "extra_note": ["important note"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.rejected_count == 1
        rej = result.rejected_transactions.iloc[0]
        assert rej["date"] == "bad_date"
        assert rej["amount"] == "zero"
        assert rej["extra_note"] == "important note"


class TestDuplicateDetection:
    """Test in-file and database duplicate candidate detection."""

    def test_in_file_duplicate_detected(self, mock_categories: dict[str, str]):
        data = {
            "date": ["2026-11-01", "2026-11-01"],
            "category": ["Food", "Food"],
            "amount": [100.0, 100.0],
            "payment_method": ["Cash", "Cash"],
            "description": ["Lunch", "Lunch"],
            "type": ["Expense", "Expense"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.total_rows == 2
        assert result.valid_count == 1
        assert result.duplicate_count == 1
        assert result.rejected_count == 0

        dupe = result.duplicate_candidates.iloc[0]
        assert dupe["duplicate_source"] == "csv"
        assert dupe["csv_row_number"] == 3

    def test_different_description_not_flagged_as_duplicate(self, mock_categories: dict[str, str]):
        # Same date, amount, category, but different descriptions -> legitimate separate txns
        data = {
            "date": ["2026-11-01", "2026-11-01"],
            "category": ["Food", "Food"],
            "amount": [100.0, 100.0],
            "payment_method": ["Cash", "Cash"],
            "description": ["Lunch at Cafe", "Dinner at Restaurant"],
            "type": ["Expense", "Expense"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.total_rows == 2
        assert result.valid_count == 2
        assert result.duplicate_count == 0

    def test_duplicate_against_existing_database_records(self, temp_db: Path):
        # 1. Insert a transaction directly into temp_db
        with get_connection(temp_db) as conn:
            cat_id = conn.execute("SELECT id FROM categories WHERE name='Food';").fetchone()["id"]
            conn.execute(
                """
                INSERT INTO transactions (date, category_id, amount, payment_method, description, type)
                VALUES ('2026-11-10', ?, 500.0, 'Card', 'Groceries', 'Expense');
                """,
                (cat_id,),
            )

        # 2. Upload a CSV containing the exact same transaction
        data = {
            "date": ["2026-11-10"],
            "category": ["Food"],
            "amount": [500.0],
            "payment_method": ["Card"],
            "description": ["Groceries"],
            "type": ["Expense"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, db_path=temp_db, check_db_duplicates=True)

        assert result.total_rows == 1
        assert result.valid_count == 0
        assert result.duplicate_count == 1
        dupe = result.duplicate_candidates.iloc[0]
        assert dupe["duplicate_source"] == "database"
        assert "existing transaction in the database" in dupe["duplicate_reason"]

    def test_row_accounting_invariant_with_all_three_categories(self, mock_categories: dict[str, str]):
        data = {
            "date": [
                "2026-11-01",  # 1: Valid
                "2026-11-01",  # 2: Duplicate of 1
                "2026-02-30",  # 3: Invalid date
                "2026-11-02",  # 4: Valid
                "2026-11-03",  # 5: Negative amount (Invalid)
            ],
            "category": ["Food", "Food", "Food", "Salary", "Utilities"],
            "amount": [100, 100, 100, 5000, -20],
            "payment_method": ["Cash", "Cash", "Cash", "Bank", "Card"],
            "description": ["A", "A", "A", "B", "C"],
            "type": ["Expense", "Expense", "Expense", "Income", "Expense"],
        }
        df = pd.DataFrame(data)
        result = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)

        assert result.total_rows == 5
        assert result.valid_count == 2
        assert result.duplicate_count == 1
        assert result.rejected_count == 2
        assert result.valid_count + result.duplicate_count + result.rejected_count == result.total_rows


class TestSingleRecordAndClassWrapper:
    """Test validate_single_expense and DataCleaner class wrapper."""

    def test_validate_single_expense_valid(self, mock_categories: dict[str, str]):
        record = {
            "date": "2026-11-01",
            "category": "Food",
            "amount": "120.50",
            "payment_method": "UPI",
            "description": "Snack",
            "type": "Expense",
        }
        clean_rec = validate_single_expense(record, categories=mock_categories)
        assert clean_rec["category"] == "Food"
        assert clean_rec["amount"] == 120.50
        assert clean_rec["type"] == "Expense"

    def test_validate_single_expense_invalid_raises_value_error(self, mock_categories: dict[str, str]):
        record = {
            "date": "2026-11-01",
            "category": "UnknownCat",
            "amount": "-50",
            "type": "Expense",
            "payment_method": "Cash",
            "description": "Test",
        }
        with pytest.raises(ValueError, match="Transaction validation failed"):
            validate_single_expense(record, categories=mock_categories)

    def test_data_cleaner_class_clean(self, mock_categories: dict[str, str]):
        cleaner = DataCleaner(categories=mock_categories)
        df = pd.DataFrame({
            "date": ["2026-11-01"],
            "category": ["Food"],
            "amount": [50],
            "payment_method": ["UPI"],
            "description": ["Tea"],
            "type": ["Expense"],
        })
        res = cleaner.clean(df)
        assert isinstance(res, CleaningResult)
        assert res.valid_count == 1

    def test_data_cleaner_dict_access(self, mock_categories: dict[str, str]):
        df = pd.DataFrame({
            "date": ["2026-11-01"],
            "category": ["Food"],
            "amount": [50],
            "payment_method": ["UPI"],
            "description": ["Tea"],
            "type": ["Expense"],
        })
        res = clean_transactions(df, categories=mock_categories, check_db_duplicates=False)
        assert len(res["valid_transactions"]) == 1
        assert res["valid_count"] == 1
        assert "Total=1" in res.summary()
