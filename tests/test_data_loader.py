"""
tests/test_data_loader.py — Tests for CSV Data Loading
=======================================================
Covers:
  - Valid CSV loading
  - UTF-8 with BOM support
  - Missing required columns (validation info and error raising)
  - Empty CSV files and empty buffers
  - Missing file handling (FileNotFoundError)
  - Column name normalization (case-insensitivity, whitespace, spaces vs underscores)
  - Extra columns identification and preservation
  - Preview helper (get_csv_preview)
  - DataLoader class methods
"""

from __future__ import annotations

import io
from pathlib import Path
import sys

import pandas as pd
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_loader import (
    REQUIRED_COLUMNS,
    DataLoader,
    get_csv_preview,
    load_csv,
    normalize_column_name,
    validate_csv_columns,
)


@pytest.fixture
def sample_csv_content() -> str:
    return (
        "date,category,amount,payment_method,description,type\n"
        "2026-11-01,Food,250.00,UPI,Lunch,Expense\n"
        "2026-11-02,Salary,25000,Bank Transfer,Monthly salary,Income\n"
    )


class TestColumnNormalization:
    """Test column name normalization logic."""

    def test_strip_and_lowercase(self):
        assert normalize_column_name("  Date  ") == "date"
        assert normalize_column_name("CATEGORY") == "category"

    def test_spaces_and_hyphens_to_underscores(self):
        assert normalize_column_name("Payment Method") == "payment_method"
        assert normalize_column_name("payment-method") == "payment_method"
        assert normalize_column_name("  PAYMENT METHOD  ") == "payment_method"

    def test_none_handling(self):
        assert normalize_column_name(None) == ""


class TestValidateCSVColumns:
    """Test column validation on DataFrames."""

    def test_valid_standard_columns(self):
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        info = validate_csv_columns(df)
        assert info["is_valid"] is True
        assert len(info["missing_columns"]) == 0
        assert set(info["present_columns"]) == set(REQUIRED_COLUMNS)

    def test_case_and_whitespace_in_columns(self):
        raw_cols = [" Date ", "CATEGORY", "Amount", "Payment Method", "Description", "Type"]
        df = pd.DataFrame(columns=raw_cols)
        info = validate_csv_columns(df)
        assert info["is_valid"] is True
        assert len(info["missing_columns"]) == 0

    def test_missing_required_column(self):
        df = pd.DataFrame(columns=["date", "category", "amount", "type"])
        info = validate_csv_columns(df)
        assert info["is_valid"] is False
        assert "payment_method" in info["missing_columns"]
        assert "description" in info["missing_columns"]

    def test_extra_columns_preserved_and_reported(self):
        cols = REQUIRED_COLUMNS + ["notes", "tax_deductible"]
        df = pd.DataFrame(columns=cols)
        info = validate_csv_columns(df)
        assert info["is_valid"] is True
        assert "notes" in info["extra_columns"]
        assert "tax_deductible" in info["extra_columns"]

    def test_none_dataframe(self):
        info = validate_csv_columns(None)  # type: ignore[arg-type]
        assert info["is_valid"] is False
        assert len(info["missing_columns"]) == len(REQUIRED_COLUMNS)


class TestLoadCSV:
    """Test CSV file loading behavior."""

    def test_valid_csv_loading(self, tmp_path: Path, sample_csv_content: str):
        csv_file = tmp_path / "valid.csv"
        csv_file.write_text(sample_csv_content, encoding="utf-8")

        df = load_csv(csv_file)
        assert len(df) == 2
        assert list(df.columns) == REQUIRED_COLUMNS
        assert df.iloc[0]["category"] == "Food"
        assert df.iloc[1]["type"] == "Income"

    def test_utf8_bom_support(self, tmp_path: Path, sample_csv_content: str):
        csv_file = tmp_path / "bom.csv"
        csv_file.write_text(sample_csv_content, encoding="utf-8-sig")

        df = load_csv(csv_file)
        assert len(df) == 2
        # First column must not contain BOM character
        assert df.columns[0] == "date"

    def test_missing_file_raises_filenotfound(self, tmp_path: Path):
        non_existent = tmp_path / "does_not_exist.csv"
        with pytest.raises(FileNotFoundError):
            load_csv(non_existent)

    def test_empty_file_raises_value_error(self, tmp_path: Path):
        empty_file = tmp_path / "empty.csv"
        empty_file.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            load_csv(empty_file)

    def test_empty_stringio_raises_value_error(self):
        buf = io.StringIO("")
        with pytest.raises(ValueError, match="empty"):
            load_csv(buf)

    def test_validate_schema_flag_missing_columns(self, tmp_path: Path):
        csv_file = tmp_path / "bad_schema.csv"
        csv_file.write_text("date,amount\n2026-11-01,100\n", encoding="utf-8")

        with pytest.raises(ValueError, match="missing required column"):
            load_csv(csv_file, validate_schema=True)

    def test_incorrect_column_capitalization_loads_successfully(self, tmp_path: Path):
        content = "DATE,Category,AMOUNT,Payment_Method,Description,TYPE\n2026-11-01,Food,100,Cash,Snack,Expense\n"
        csv_file = tmp_path / "caps.csv"
        csv_file.write_text(content, encoding="utf-8")

        df = load_csv(csv_file, validate_schema=True)
        assert len(df) == 1

    def test_extra_columns_loaded_without_dropping(self, tmp_path: Path):
        content = (
            "date,category,amount,payment_method,description,type,tags,reference_id\n"
            "2026-11-01,Food,100,Cash,Snack,Expense,groceries,TXN12345\n"
        )
        csv_file = tmp_path / "extra_cols.csv"
        csv_file.write_text(content, encoding="utf-8")

        df = load_csv(csv_file, validate_schema=True)
        assert "tags" in df.columns
        assert "reference_id" in df.columns
        assert df.iloc[0]["tags"] == "groceries"


class TestCSVPreview:
    """Test preview helper."""

    def test_preview_returns_first_n_rows(self):
        data = {"date": [f"2026-11-{i:02d}" for i in range(1, 20)]}
        df = pd.DataFrame(data)
        preview = get_csv_preview(df, rows=5)
        assert len(preview) == 5
        # Preview must be a copy, not a slice view that mutates df
        assert preview is not df

    def test_preview_none_df(self):
        preview = get_csv_preview(None)  # type: ignore[arg-type]
        assert isinstance(preview, pd.DataFrame)
        assert preview.empty


class TestDataLoaderClass:
    """Test DataLoader class wrapper."""

    def test_import_from_csv_delegation(self, tmp_path: Path, sample_csv_content: str):
        loader = DataLoader()
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(sample_csv_content, encoding="utf-8")

        df = loader.import_from_csv(csv_file)
        assert len(df) == 2

    def test_get_preview_delegation(self):
        loader = DataLoader()
        df = pd.DataFrame({"a": [1, 2, 3, 4, 5]})
        preview = loader.get_preview(df, rows=2)
        assert len(preview) == 2

    def test_validate_columns_delegation(self):
        loader = DataLoader()
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        info = loader.validate_columns(df)
        assert info["is_valid"] is True
