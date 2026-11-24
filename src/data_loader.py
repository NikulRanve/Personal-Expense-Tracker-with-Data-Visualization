"""
src/data_loader.py — CSV Data Loader
=====================================
Responsible for loading and inspecting CSV files containing financial transaction data.

Standard CSV Schema (case-insensitive column names, whitespace-trimmed):
  - date
  - category
  - amount
  - payment_method
  - description
  - type

Public API
----------
  - REQUIRED_COLUMNS                  — list of standard column names
  - normalize_column_name(col)        — helper to normalize a column name
  - validate_csv_columns(df)          — check required columns, return details
  - load_csv(file_path, ...)          — read CSV with UTF-8 / UTF-8-BOM support
  - get_csv_preview(df, rows=10)      — safe preview of first N rows
  - DataLoader                        — class wrapper for loading from CSV / DB
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

# Standard required columns in canonical order
REQUIRED_COLUMNS: list[str] = [
    "date",
    "category",
    "amount",
    "payment_method",
    "description",
    "type",
]


def normalize_column_name(col: Any) -> str:
    """
    Normalize a column header name to a standard snake_case lowercase token.

    Examples
    --------
    >>> normalize_column_name("  Date  ")
    'date'
    >>> normalize_column_name("Payment Method")
    'payment_method'
    >>> normalize_column_name("PAYMENT_METHOD")
    'payment_method'
    """
    if col is None:
        return ""
    text = str(col).strip().lower()
    # Replace spaces and hyphens with underscores
    text = text.replace(" ", "_").replace("-", "_")
    return text


def validate_csv_columns(df: pd.DataFrame) -> dict[str, Any]:
    """
    Verify whether the required six columns are present in the DataFrame.

    Matches column names case-insensitively and ignores surrounding whitespace
    and internal spaces/underscores (e.g. 'Payment Method' matches 'payment_method').
    Extra columns are identified and preserved, never silently dropped.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to validate.

    Returns
    -------
    dict
        {
            "is_valid": bool,
            "missing_columns": list[str],
            "present_columns": list[str],
            "extra_columns": list[str],
            "column_mapping": dict[str, str],  # original_col -> canonical_name
        }
    """
    if df is None:
        return {
            "is_valid": False,
            "missing_columns": list(REQUIRED_COLUMNS),
            "present_columns": [],
            "extra_columns": [],
            "column_mapping": {},
        }

    column_mapping: dict[str, str] = {}
    present_canonicals: set[str] = set()
    extra_columns: list[str] = []

    for raw_col in df.columns:
        norm = normalize_column_name(raw_col)
        if norm in REQUIRED_COLUMNS and norm not in present_canonicals:
            column_mapping[str(raw_col)] = norm
            present_canonicals.add(norm)
        else:
            extra_columns.append(str(raw_col))

    missing = [c for c in REQUIRED_COLUMNS if c not in present_canonicals]
    is_valid = len(missing) == 0

    return {
        "is_valid": is_valid,
        "missing_columns": missing,
        "present_columns": [c for c in REQUIRED_COLUMNS if c in present_canonicals],
        "extra_columns": extra_columns,
        "column_mapping": column_mapping,
    }


def load_csv(
    file_path: Union[str, Path, io.IOBase, io.BytesIO, io.StringIO],
    validate_schema: bool = False,
) -> pd.DataFrame:
    """
    Read a CSV file or file-like object using Pandas.

    Features:
      - Supports UTF-8 and UTF-8 with BOM ('utf-8-sig').
      - Handles empty files by raising a descriptive ValueError.
      - Handles missing files by raising FileNotFoundError.
      - Never modifies the original source file.
      - Preserves all rows and columns as string-like raw data initially.
      - Optionally validates the required column schema.

    Parameters
    ----------
    file_path : str | Path | file-like
        Path to the CSV file or an open file-like buffer.
    validate_schema : bool, default False
        If True, raises ValueError if any of the 6 required columns are missing.

    Returns
    -------
    pd.DataFrame
        Loaded DataFrame.

    Raises
    ------
    FileNotFoundError
        If file_path is a path string/Path that does not exist.
    ValueError
        If file is empty, malformed, or missing required columns (when validate_schema=True).
    """
    # 1. Path existence and empty file checks for filesystem paths
    if isinstance(file_path, (str, Path)):
        resolved = Path(file_path)
        if not resolved.exists():
            raise FileNotFoundError(f"CSV file not found: {resolved}")
        if resolved.is_file() and resolved.stat().st_size == 0:
            raise ValueError(f"CSV file is empty (0 bytes): {resolved}")
        target = resolved
    elif hasattr(file_path, "seek") and hasattr(file_path, "tell"):
        # File-like object: check if empty
        cur_pos = file_path.tell()
        file_path.seek(0, io.SEEK_END)
        size = file_path.tell()
        file_path.seek(cur_pos)
        if size == 0:
            raise ValueError("CSV file-like buffer is empty (0 bytes)")
        target = file_path
    else:
        target = file_path

    # 2. Read with pandas using 'utf-8-sig' to seamlessly handle UTF-8 and UTF-8 BOM
    try:
        df = pd.read_csv(
            target,
            encoding="utf-8-sig",
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        )
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"CSV file contains no readable data: {exc}") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"Malformed CSV file syntax: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"CSV file encoding error: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Failed to read CSV file: {exc}") from exc

    if df.empty and len(df.columns) == 0:
        raise ValueError("CSV file contains no columns or data")

    # 3. Optional schema validation
    if validate_schema:
        validation = validate_csv_columns(df)
        if not validation["is_valid"]:
            missing_str = ", ".join(validation["missing_columns"])
            raise ValueError(
                f"CSV file is missing required column(s): {missing_str}. "
                f"Required columns are: {', '.join(REQUIRED_COLUMNS)}"
            )

    return df


def get_csv_preview(df: pd.DataFrame, rows: int = 10) -> pd.DataFrame:
    """
    Return a safe preview of the first specified number of records.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to preview.
    rows : int, default 10
        Number of leading rows to return.

    Returns
    -------
    pd.DataFrame
        A defensive copy of the head of the DataFrame.
    """
    if df is None:
        return pd.DataFrame()
    return df.head(rows).copy()


# ---------------------------------------------------------------------------
# DataLoader Class
# ---------------------------------------------------------------------------

class DataLoader:
    """
    High-level data loader interface for CSV import and SQLite queries.

    Accepts an optional database manager or db_path.
    """

    def __init__(self, db_manager: Any = None):
        self.db = db_manager

    def import_from_csv(
        self, path: Union[str, Path], validate_schema: bool = False
    ) -> pd.DataFrame:
        """Read a CSV file and return a DataFrame for further processing."""
        return load_csv(path, validate_schema=validate_schema)

    def get_preview(self, df: pd.DataFrame, rows: int = 10) -> pd.DataFrame:
        """Return a safe preview of the first N rows of a DataFrame."""
        return get_csv_preview(df, rows=rows)

    def validate_columns(self, df: pd.DataFrame) -> dict[str, Any]:
        """Validate DataFrame columns against standard schema."""
        return validate_csv_columns(df)

    def load_expenses(self) -> pd.DataFrame:
        """Load all expense records from the database."""
        from database import get_connection

        db_path = getattr(self.db, "db_path", None) if self.db else None
        with get_connection(db_path) as conn:
            query = """
                SELECT t.id, t.date, c.name AS category, t.amount,
                       t.payment_method, t.description, t.type, t.created_at
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.type = 'Expense'
                ORDER BY t.date DESC, t.id DESC;
            """
            return pd.read_sql_query(query, conn)

    def load_incomes(self) -> pd.DataFrame:
        """Load all income records from the database."""
        from database import get_connection

        db_path = getattr(self.db, "db_path", None) if self.db else None
        with get_connection(db_path) as conn:
            query = """
                SELECT t.id, t.date, c.name AS category, t.amount,
                       t.payment_method, t.description, t.type, t.created_at
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.type = 'Income'
                ORDER BY t.date DESC, t.id DESC;
            """
            return pd.read_sql_query(query, conn)

    def load_categories(self) -> pd.DataFrame:
        """Load all categories from the database."""
        from database import get_connection

        db_path = getattr(self.db, "db_path", None) if self.db else None
        with get_connection(db_path) as conn:
            query = "SELECT id, name, type, created_at FROM categories ORDER BY type, name;"
            return pd.read_sql_query(query, conn)

    def load_monthly(self, year: int, month: int) -> pd.DataFrame:
        """Load transactions for a specific year-month as a DataFrame."""
        from database import get_connection

        month_str = f"{year:04d}-{month:02d}"
        db_path = getattr(self.db, "db_path", None) if self.db else None
        with get_connection(db_path) as conn:
            query = """
                SELECT t.id, t.date, c.name AS category, t.amount,
                       t.payment_method, t.description, t.type
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.date LIKE ?
                ORDER BY t.date ASC, t.id ASC;
            """
            return pd.read_sql_query(query, conn, params=[f"{month_str}%"])
