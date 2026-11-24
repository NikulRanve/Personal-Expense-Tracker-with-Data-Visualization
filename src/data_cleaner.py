"""
src/data_cleaner.py — Transaction Data Cleaner & Validator
===========================================================
Cleans, normalizes, and validates transaction DataFrames prior to analysis or
database insertion.

Core Capabilities
-----------------
  1. Column standardisation (case-insensitive, whitespace-trimmed, spaces -> underscores).
  2. Strict calendar date validation (reusing validate_transaction_date from src.database).
  3. Positive amount validation (rejects NaN, inf, <= 0, and non-numerics).
  4. Transaction type normalisation and validation (Income or Expense).
  5. Category existence and type matching against the SQLite database.
  6. Optional fields whitespace trimming and consistent representation (None for missing).
  7. Multi-error capture per rejected row with original values preserved.
  8. Conservative duplicate-candidate detection (within CSV and against existing DB records).
  9. Structured CleaningResult output contract with guaranteed row accounting:
       total_rows = valid_count + rejected_count + duplicate_count

Output Contract
---------------
  CleaningResult:
    - valid_transactions: pd.DataFrame
    - rejected_transactions: pd.DataFrame
    - duplicate_candidates: pd.DataFrame
    - total_rows: int
    - valid_count: int
    - rejected_count: int
    - duplicate_count: int
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

from database import (
    DEFAULT_DB_PATH,
    get_connection,
    validate_transaction_date,
)
from data_loader import (
    REQUIRED_COLUMNS,
    normalize_column_name,
    validate_csv_columns,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output Contract: CleaningResult
# ---------------------------------------------------------------------------

@dataclass
class CleaningResult:
    """
    Structured outcome of the transaction data cleaning process.

    Invariants
    ----------
    total_rows == valid_count + rejected_count + duplicate_count
    """

    valid_transactions: pd.DataFrame
    rejected_transactions: pd.DataFrame
    duplicate_candidates: pd.DataFrame
    total_rows: int
    valid_count: int
    rejected_count: int
    duplicate_count: int

    def __getitem__(self, item: str) -> Any:
        """Allow dictionary-style access (e.g. result['valid_transactions'])."""
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(f"CleaningResult has no attribute {item!r}")

    def to_dict(self) -> dict[str, Any]:
        """Convert result metadata to a summary dictionary."""
        return {
            "total_rows": self.total_rows,
            "valid_count": self.valid_count,
            "rejected_count": self.rejected_count,
            "duplicate_count": self.duplicate_count,
        }

    def summary(self) -> str:
        """Human-readable summary of the cleaning execution."""
        return (
            f"Cleaning Summary: Total={self.total_rows} | "
            f"Valid={self.valid_count} | "
            f"Rejected={self.rejected_count} | "
            f"Duplicates={self.duplicate_count}"
        )


# ---------------------------------------------------------------------------
# Category & Database Inspection Helpers
# ---------------------------------------------------------------------------

def get_known_categories(db_path: Optional[Union[Path, str]] = None) -> dict[str, str]:
    """
    Fetch all active category names and their registered types from SQLite.

    Returns
    -------
    dict[str, str]
        Mapping of category name (exact case) -> type ('Income' or 'Expense').
        Also accessible case-insensitively via normalization.
    """
    categories: dict[str, str] = {}
    try:
        with get_connection(db_path) as conn:
            cursor = conn.execute("SELECT name, type FROM categories;")
            for row in cursor.fetchall():
                categories[row["name"]] = row["type"]
    except Exception as exc:
        logger.warning("Could not fetch categories from database (%s): %s", db_path, exc)
    return categories


def get_existing_transactions_signatures(
    db_path: Optional[Union[Path, str]] = None,
) -> set[tuple[str, str, float, str, Optional[str], Optional[str]]]:
    """
    Fetch normalized signatures of existing transactions from the database for
    conservative duplicate matching.

    Returns
    -------
    set of tuples: (date, category_name_lower, amount_rounded, type_lower, pm_lower, desc_lower)
    """
    signatures = set()
    try:
        with get_connection(db_path) as conn:
            # Check if transactions table exists
            table_check = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='transactions';"
            ).fetchone()
            if not table_check:
                return signatures

            cursor = conn.execute(
                """
                SELECT t.date, c.name AS category, t.amount, t.type,
                       t.payment_method, t.description
                FROM transactions t
                JOIN categories c ON t.category_id = c.id;
                """
            )
            for row in cursor.fetchall():
                date_str = str(row["date"]).strip()
                cat_str = str(row["category"]).strip().lower()
                amount_val = round(float(row["amount"]), 2)
                type_str = str(row["type"]).strip().lower()
                pm_str = (
                    str(row["payment_method"]).strip().lower()
                    if row["payment_method"] is not None and str(row["payment_method"]).strip() != ""
                    else None
                )
                desc_str = (
                    str(row["description"]).strip().lower()
                    if row["description"] is not None and str(row["description"]).strip() != ""
                    else None
                )
                signatures.add((date_str, cat_str, amount_val, type_str, pm_str, desc_str))
    except Exception as exc:
        logger.warning(
            "Could not fetch existing transactions for duplicate detection (%s): %s",
            db_path,
            exc,
        )
    return signatures


# ---------------------------------------------------------------------------
# Individual Field Validators
# ---------------------------------------------------------------------------

def validate_date_field(val: Any) -> tuple[Optional[str], Optional[str]]:
    """
    Strict calendar date validator.

    Returns
    -------
    tuple of (normalized_date_str, error_message)
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None, "Missing date"
    date_str = str(val).strip()
    if not date_str:
        return None, "Missing date"

    try:
        parsed_date = validate_transaction_date(date_str)
        return parsed_date.strftime("%Y-%m-%d"), None
    except ValueError as exc:
        return None, f"Invalid calendar date '{date_str}': {exc}"


def validate_amount_field(val: Any) -> tuple[Optional[float], Optional[str]]:
    """
    Positive numeric amount validator.

    Returns
    -------
    tuple of (normalized_float, error_message)
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None, "Missing amount"
    if isinstance(val, str):
        val_str = val.strip().replace(",", "")
        if not val_str:
            return None, "Missing amount"
        try:
            num = float(val_str)
        except ValueError:
            return None, f"Non-numeric amount: '{val}'"
    elif isinstance(val, (int, float)):
        num = float(val)
    else:
        return None, f"Non-numeric amount of type {type(val).__name__}"

    if math.isnan(num):
        return None, "Missing amount (NaN)"
    if math.isinf(num):
        return None, "Amount cannot be infinite"
    if num < 0:
        return None, f"Negative amount ({num}): amount must be greater than zero"
    if num == 0:
        return None, "Zero amount: amount must be greater than zero"

    return round(num, 2), None


def validate_type_field(val: Any) -> tuple[Optional[str], Optional[str]]:
    """
    Transaction type normalizer and validator.

    Returns
    -------
    tuple of (normalized_type, error_message)
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None, "Missing transaction type"
    type_str = str(val).strip()
    if not type_str:
        return None, "Missing transaction type"

    lower = type_str.lower()
    if lower == "income":
        return "Income", None
    elif lower == "expense":
        return "Expense", None
    else:
        return None, f"Invalid transaction type: '{type_str}' (expected 'Income' or 'Expense')"


def validate_category_field(
    val: Any,
    normalized_type: Optional[str],
    known_categories: Optional[dict[str, str]],
) -> tuple[Optional[str], Optional[str]]:
    """
    Category validator: verifies existence and type compatibility.

    Returns
    -------
    tuple of (canonical_category_name, error_message)
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None, "Missing category"
    cat_str = str(val).strip()
    if not cat_str:
        return None, "Missing category"

    if known_categories is None:
        # No category catalog provided; accept stripped string
        return cat_str, None

    # Case-insensitive lookup against known categories
    cat_lookup = {k.lower(): (k, v) for k, v in known_categories.items()}
    match = cat_lookup.get(cat_str.lower())

    if not match:
        return None, f"Unknown category: '{cat_str}' does not exist in the database"

    canonical_name, category_type = match

    # If the transaction type itself was successfully resolved, verify type matching
    if normalized_type and normalized_type in ("Income", "Expense"):
        if category_type.lower() != normalized_type.lower():
            return None, (
                f"Category type mismatch: category '{canonical_name}' is of type "
                f"'{category_type}', but transaction type is '{normalized_type}'"
            )

    return canonical_name, None


def normalize_optional_field(val: Any) -> Optional[str]:
    """Normalize optional text fields: strip whitespace, return None if empty/null."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s if s else None


# ---------------------------------------------------------------------------
# Main Cleaning Pipeline: clean_transactions
# ---------------------------------------------------------------------------

def clean_transactions(
    df: pd.DataFrame,
    db_path: Optional[Union[Path, str]] = None,
    categories: Optional[dict[str, str]] = None,
    check_db_duplicates: bool = True,
) -> CleaningResult:
    """
    Clean, validate, and deduplicate a DataFrame of raw transactions.

    Parameters
    ----------
    df : pd.DataFrame
        Raw transaction DataFrame loaded from CSV.
    db_path : Path | str, optional
        Path to the SQLite database. If None and categories is None, attempts to
        use DEFAULT_DB_PATH if it exists.
    categories : dict[str, str], optional
        Pre-loaded category name -> type mapping. If provided, overrides db lookup.
    check_db_duplicates : bool, default True
        Whether to check candidate transactions against existing database transactions.

    Returns
    -------
    CleaningResult
        Structured result with valid, rejected, and duplicate DataFrames,
        and respective counts.

    Raises
    ------
    ValueError
        If required standard columns are missing from the input DataFrame.
    """
    if df is None or (df.empty and len(df.columns) == 0):
        empty_valid = pd.DataFrame(columns=REQUIRED_COLUMNS)
        empty_rejected = pd.DataFrame(
            columns=["row_index", "csv_row_number", "rejection_reason", "rejection_reasons"]
        )
        empty_dupes = pd.DataFrame(
            columns=REQUIRED_COLUMNS + ["row_index", "csv_row_number", "duplicate_source", "duplicate_reason"]
        )
        return CleaningResult(
            valid_transactions=empty_valid,
            rejected_transactions=empty_rejected,
            duplicate_candidates=empty_dupes,
            total_rows=0,
            valid_count=0,
            rejected_count=0,
            duplicate_count=0,
        )

    # 1. Validate required columns exist
    val_info = validate_csv_columns(df)
    if not val_info["is_valid"]:
        missing_str = ", ".join(val_info["missing_columns"])
        raise ValueError(
            f"Input DataFrame is missing required column(s): {missing_str}. "
            f"Expected columns: {', '.join(REQUIRED_COLUMNS)}"
        )

    # 2. Build column mapping for raw -> canonical required column
    col_map = val_info["column_mapping"]  # raw_col -> canonical
    # Invert to map canonical -> raw_col (guaranteed to contain all 6)
    canonical_to_raw = {v: k for k, v in col_map.items()}

    # 3. Resolve known categories and existing DB transaction signatures
    if categories is not None:
        known_cats = categories
    else:
        # Load from DB if db_path provided or default exists
        target_db = db_path if db_path is not None else DEFAULT_DB_PATH
        known_cats = get_known_categories(target_db) if target_db else {}

    existing_db_signatures = (
        get_existing_transactions_signatures(db_path if db_path is not None else DEFAULT_DB_PATH)
        if check_db_duplicates
        else set()
    )

    # 4. Containers for categorizing rows
    valid_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    duplicate_rows: list[dict[str, Any]] = []

    seen_csv_signatures: set[tuple[str, str, float, str, Optional[str], Optional[str]]] = set()

    # Track all extra columns to preserve them
    raw_columns = list(df.columns)
    extra_raw_cols = [c for c in raw_columns if c not in col_map]

    total_rows = len(df)

    # 5. Row-by-row comprehensive validation
    for row_idx, (_, row) in enumerate(df.iterrows()):
        csv_row_num = row_idx + 2  # CSV line number (accounting for 1 header row)
        reasons: list[str] = []

        # Extract raw values for the 6 required columns
        raw_date = row[canonical_to_raw["date"]]
        raw_cat = row[canonical_to_raw["category"]]
        raw_amount = row[canonical_to_raw["amount"]]
        raw_pm = row[canonical_to_raw["payment_method"]]
        raw_desc = row[canonical_to_raw["description"]]
        raw_type = row[canonical_to_raw["type"]]

        # a. Date validation
        norm_date, date_err = validate_date_field(raw_date)
        if date_err:
            reasons.append(date_err)

        # b. Amount validation
        norm_amount, amount_err = validate_amount_field(raw_amount)
        if amount_err:
            reasons.append(amount_err)

        # c. Type validation
        norm_type, type_err = validate_type_field(raw_type)
        if type_err:
            reasons.append(type_err)

        # d. Category validation
        norm_cat, cat_err = validate_category_field(raw_cat, norm_type, known_cats)
        if cat_err:
            reasons.append(cat_err)

        # e. Optional fields normalization
        norm_pm = normalize_optional_field(raw_pm)
        norm_desc = normalize_optional_field(raw_desc)

        # If any validation errors exist -> REJECTED
        if reasons:
            rej_record = dict(row)  # preserve all original values
            rej_record["row_index"] = row_idx
            rej_record["csv_row_number"] = csv_row_num
            rej_record["rejection_reason"] = "; ".join(reasons)
            rej_record["rejection_reasons"] = reasons
            rejected_rows.append(rej_record)
            continue

        # If all fields valid -> Check for duplicates
        # Build normalized signature tuple:
        # (date, category_lower, amount, type_lower, pm_lower, desc_lower)
        sig = (
            norm_date,  # type: ignore[arg-type]
            norm_cat.lower(),  # type: ignore[union-attr]
            norm_amount,  # type: ignore[arg-type]
            norm_type.lower(),  # type: ignore[union-attr]
            norm_pm.lower() if norm_pm is not None else None,
            norm_desc.lower() if norm_desc is not None else None,
        )

        base_clean_record: dict[str, Any] = {
            "date": norm_date,
            "category": norm_cat,
            "amount": norm_amount,
            "payment_method": norm_pm,
            "description": norm_desc,
            "type": norm_type,
            "row_index": row_idx,
            "csv_row_number": csv_row_num,
        }
        # Preserve extra columns
        for extra_col in extra_raw_cols:
            base_clean_record[extra_col] = row[extra_col]

        # Duplicate check 1: Seen earlier in this CSV
        if sig in seen_csv_signatures:
            dupe_record = dict(base_clean_record)
            dupe_record["duplicate_source"] = "csv"
            dupe_record["duplicate_reason"] = "Duplicate of an earlier record in this CSV"
            duplicate_rows.append(dupe_record)
            continue

        # Duplicate check 2: Matches an existing transaction in the database
        if sig in existing_db_signatures:
            dupe_record = dict(base_clean_record)
            dupe_record["duplicate_source"] = "database"
            dupe_record["duplicate_reason"] = "Matches an existing transaction in the database"
            duplicate_rows.append(dupe_record)
            continue

        # Unique & valid
        seen_csv_signatures.add(sig)
        valid_rows.append(base_clean_record)

    # 6. Convert lists to DataFrames
    valid_df = pd.DataFrame(valid_rows) if valid_rows else pd.DataFrame(columns=REQUIRED_COLUMNS)
    rejected_df = (
        pd.DataFrame(rejected_rows)
        if rejected_rows
        else pd.DataFrame(
            columns=list(df.columns)
            + ["row_index", "csv_row_number", "rejection_reason", "rejection_reasons"]
        )
    )
    duplicate_df = (
        pd.DataFrame(duplicate_rows)
        if duplicate_rows
        else pd.DataFrame(
            columns=REQUIRED_COLUMNS
            + ["row_index", "csv_row_number", "duplicate_source", "duplicate_reason"]
        )
    )

    valid_count = len(valid_df)
    rejected_count = len(rejected_df)
    duplicate_count = len(duplicate_df)

    # Invariant verification
    assert (
        valid_count + rejected_count + duplicate_count == total_rows
    ), f"Row accounting error: {valid_count} + {rejected_count} + {duplicate_count} != {total_rows}"

    return CleaningResult(
        valid_transactions=valid_df,
        rejected_transactions=rejected_df,
        duplicate_candidates=duplicate_df,
        total_rows=total_rows,
        valid_count=valid_count,
        rejected_count=rejected_count,
        duplicate_count=duplicate_count,
    )


# ---------------------------------------------------------------------------
# Single Record Validator Helper
# ---------------------------------------------------------------------------

def validate_single_expense(
    record: dict[str, Any],
    db_path: Optional[Union[Path, str]] = None,
    categories: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    Validate a single transaction dictionary before DB insertion.

    Returns the cleaned record or raises ValueError if validation fails.
    """
    df_single = pd.DataFrame([record])
    result = clean_transactions(
        df_single, db_path=db_path, categories=categories, check_db_duplicates=False
    )
    if result.rejected_count > 0:
        reason = result.rejected_transactions.iloc[0]["rejection_reason"]
        raise ValueError(f"Transaction validation failed: {reason}")

    clean_rec = result.valid_transactions.iloc[0].to_dict()
    # Strip internal row indexing before returning
    clean_rec.pop("row_index", None)
    clean_rec.pop("csv_row_number", None)
    return clean_rec


# ---------------------------------------------------------------------------
# DataCleaner Class Wrapper
# ---------------------------------------------------------------------------

class DataCleaner:
    """
    High-level data cleaner interface for processing DataFrames.
    """

    def __init__(
        self,
        db_path: Optional[Union[Path, str]] = None,
        categories: Optional[dict[str, str]] = None,
    ):
        self.db_path = db_path
        self.categories = categories

    def clean(self, df: pd.DataFrame) -> CleaningResult:
        """Full cleaning pipeline: validate -> deduplicate -> standardise."""
        return clean_transactions(df, db_path=self.db_path, categories=self.categories)

    def validate_amounts(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter out rows where amount is non-numeric, NaN, infinite, or <= 0."""
        valid_indices = []
        col = "amount"
        for raw_c in df.columns:
            if normalize_column_name(raw_c) == "amount":
                col = raw_c
                break

        for idx, val in df[col].items():
            num, err = validate_amount_field(val)
            if not err:
                valid_indices.append(idx)
        return df.loc[valid_indices].copy()

    def standardise_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        """Parse and standardise the date column to canonical YYYY-MM-DD strings."""
        col = "date"
        for raw_c in df.columns:
            if normalize_column_name(raw_c) == "date":
                col = raw_c
                break

        df_copy = df.copy()
        clean_dates = []
        for val in df_copy[col]:
            d_str, _ = validate_date_field(val)
            clean_dates.append(d_str)
        df_copy[col] = clean_dates
        return df_copy

    def drop_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove exact duplicate rows across all required fields."""
        res = self.clean(df)
        return res.valid_transactions
