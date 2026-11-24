"""
src/import_service.py — Transaction Import Service
===================================================
Coordinates loading, validation, duplicate re-checking, atomic persistence,
batch audit logging, and history retrieval for transaction imports.

Public API
----------
  - preview_import(file_path, db_path=None) -> CleaningResult
  - import_transactions(cleaning_result, filename, db_path=None, ...) -> ImportSummary
  - get_import_history(db_path=None) -> list[dict[str, Any]]
  - get_import_batch(batch_id, db_path=None) -> Optional[dict[str, Any]]
  - get_batch_transactions(batch_id, db_path=None) -> pd.DataFrame
  - export_rejected_transactions(df, filename, export_dir=None) -> Path
  - export_duplicate_candidates(df, filename, export_dir=None) -> Path
  - ImportSummary (dataclass)
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

from database import (
    DEFAULT_DB_PATH,
    get_connection,
)
from data_cleaner import (
    CleaningResult,
    clean_transactions,
)
from data_loader import (
    load_csv,
)

logger = logging.getLogger(__name__)

# Default export directory: outputs/exports/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXPORT_DIR = _PROJECT_ROOT / "outputs" / "exports"


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ImportSummary:
    """
    Structured outcome of an atomic transaction import operation.

    Invariants
    ----------
    total_rows == successful_rows + rejected_rows + duplicate_rows
    """

    batch_id: int
    filename: str
    total_rows: int
    successful_rows: int
    rejected_rows: int
    duplicate_rows: int
    imported_transactions: pd.DataFrame
    rejected_transactions: pd.DataFrame
    duplicate_candidates: pd.DataFrame
    rejected_export_path: Optional[str] = None
    duplicate_export_path: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        """Support dictionary-style access (e.g. summary['batch_id'])."""
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(f"ImportSummary has no attribute {item!r}")

    def to_dict(self) -> dict[str, Any]:
        """Convert summary metadata into a dictionary."""
        return {
            "batch_id": self.batch_id,
            "filename": self.filename,
            "total_rows": self.total_rows,
            "successful_rows": self.successful_rows,
            "rejected_rows": self.rejected_rows,
            "duplicate_rows": self.duplicate_rows,
            "rejected_export_path": self.rejected_export_path,
            "duplicate_export_path": self.duplicate_export_path,
        }

    def summary(self) -> str:
        """Human-readable summary string."""
        return (
            f"Import Batch #{self.batch_id} ('{self.filename}'): "
            f"Total={self.total_rows} | "
            f"Imported={self.successful_rows} | "
            f"Rejected={self.rejected_rows} | "
            f"Duplicates={self.duplicate_rows}"
        )


# ---------------------------------------------------------------------------
# Preview Operation (Read-only)
# ---------------------------------------------------------------------------

def preview_import(
    file_path: Union[str, Path, io.IOBase, io.BytesIO, io.StringIO],
    db_path: Optional[Union[Path, str]] = None,
) -> CleaningResult:
    """
    Load a CSV and produce a full preview of valid, rejected, and duplicate rows.

    This function performs NO database mutations (no transactions inserted,
    no import_batches created).

    Parameters
    ----------
    file_path : str | Path | file-like
        Path to CSV or open buffer.
    db_path : Path | str, optional
        Database to check for existing duplicates and category lookups.

    Returns
    -------
    CleaningResult
        Result containing categorized DataFrames and counts.
    """
    df_raw = load_csv(file_path)
    return clean_transactions(df_raw, db_path=db_path, check_db_duplicates=True)


# ---------------------------------------------------------------------------
# Atomic Persistence Operation
# ---------------------------------------------------------------------------

def import_transactions(
    cleaning_result: CleaningResult,
    filename: str,
    db_path: Optional[Union[Path, str]] = None,
    export_rejected: bool = False,
    export_duplicates: bool = False,
    export_dir: Optional[Union[Path, str]] = None,
) -> ImportSummary:
    """
    Persist valid transactions into SQLite inside a single atomic transaction.

    Workflow:
      1. Re-check valid rows against existing database records to guard against
         concurrent inserts between preview and confirmation.
      2. Resolve category names to integer category IDs.
      3. Create an import_batches row with strict row accounting:
           total_rows = successful_rows + rejected_rows + duplicate_rows
      4. Insert all valid, non-duplicate transactions linked to the batch ID.
      5. Commit atomically. If any error occurs, rolls back cleanly.

    Parameters
    ----------
    cleaning_result : CleaningResult
        Previously validated cleaning result (from preview_import or clean_transactions).
    filename : str
        Source filename for the import batch record.
    db_path : Path | str, optional
        Target SQLite database path.
    export_rejected : bool, default False
        Whether to export rejected rows to outputs/exports/<filename>_rejected_<timestamp>.csv.
    export_duplicates : bool, default False
        Whether to export duplicate candidate rows to CSV.
    export_dir : Path | str, optional
        Custom export folder override.

    Returns
    -------
    ImportSummary
        Structured summary of the import outcome.

    Raises
    ------
    ValueError
        If cleaning_result is invalid, or if category resolution fails.
    Exception
        Any unexpected database error (which triggers an automatic rollback).
    """
    if cleaning_result is None or not isinstance(cleaning_result, CleaningResult):
        raise ValueError("A valid CleaningResult instance must be provided to import_transactions.")

    target_db = db_path if db_path is not None else DEFAULT_DB_PATH

    valid_df = cleaning_result.valid_transactions.copy()
    rejected_df = cleaning_result.rejected_transactions.copy()
    initial_dupes_df = cleaning_result.duplicate_candidates.copy()

    # Pre-parse duplicate candidates into a working list of dicts
    final_dupe_rows: list[dict[str, Any]] = (
        initial_dupes_df.to_dict(orient="records") if not initial_dupes_df.empty else []
    )
    rows_to_insert: list[dict[str, Any]] = []

    # All DB writes take place inside a single context-managed transaction
    with get_connection(target_db) as conn:
        # 1. Fetch categories for resolution: map lowercase name -> (id, canonical_name, type)
        cat_rows = conn.execute("SELECT id, name, type FROM categories;").fetchall()
        category_map: dict[str, tuple[int, str, str]] = {
            r["name"].strip().lower(): (r["id"], r["name"], r["type"]) for r in cat_rows
        }

        # 2. Fetch current existing transactions from DB for the atomic re-check
        db_signatures: set[tuple[str, str, float, str, Optional[str], Optional[str]]] = set()
        cursor = conn.execute(
            """
            SELECT t.date, c.name AS category, t.amount, t.type,
                   t.payment_method, t.description
            FROM transactions t
            JOIN categories c ON t.category_id = c.id;
            """
        )
        for r in cursor.fetchall():
            sig = (
                str(r["date"]).strip(),
                str(r["category"]).strip().lower(),
                round(float(r["amount"]), 2),
                str(r["type"]).strip().lower(),
                str(r["payment_method"]).strip().lower() if r["payment_method"] else None,
                str(r["description"]).strip().lower() if r["description"] else None,
            )
            db_signatures.add(sig)

        # 3. Categorize candidates into rows_to_insert vs recheck-duplicates
        for _, row in valid_df.iterrows():
            rec = dict(row)
            d_val = str(rec["date"]).strip()
            cat_name = str(rec["category"]).strip()
            amt_val = round(float(rec["amount"]), 2)
            type_val = str(rec["type"]).strip()
            pm_val = str(rec["payment_method"]).strip() if rec.get("payment_method") else None
            desc_val = str(rec["description"]).strip() if rec.get("description") else None

            sig = (
                d_val,
                cat_name.lower(),
                amt_val,
                type_val.lower(),
                pm_val.lower() if pm_val else None,
                desc_val.lower() if desc_val else None,
            )

            # Check if record was inserted into DB concurrently between preview and import
            if sig in db_signatures:
                rec["duplicate_source"] = "database"
                rec["duplicate_reason"] = "Identified as duplicate during persistence recheck"
                final_dupe_rows.append(rec)
                continue

            # Resolve category ID
            cat_info = category_map.get(cat_name.lower())
            if not cat_info:
                raise ValueError(
                    f"Unknown category '{cat_name}' during import persistence. "
                    "Categories must exist in the database."
                )

            cat_id, canonical_name, cat_type = cat_info
            if cat_type.lower() != type_val.lower():
                raise ValueError(
                    f"Category type mismatch: category '{canonical_name}' is {cat_type}, "
                    f"but transaction type is {type_val}."
                )

            rec["resolved_category_id"] = cat_id
            rec["category"] = canonical_name
            rec["payment_method"] = pm_val
            rec["description"] = desc_val
            rows_to_insert.append(rec)

        # 4. Finalize counts and verify strict row accounting invariant
        successful_rows = len(rows_to_insert)
        rejected_rows = cleaning_result.rejected_count
        duplicate_rows = len(final_dupe_rows)
        total_rows = cleaning_result.total_rows

        if total_rows != (successful_rows + rejected_rows + duplicate_rows):
            raise ValueError(
                f"Batch accounting invariant violated: total ({total_rows}) != "
                f"successful ({successful_rows}) + rejected ({rejected_rows}) + duplicate ({duplicate_rows})"
            )

        # 5. Insert the import batch record
        cur = conn.execute(
            """
            INSERT INTO import_batches
                (filename, total_rows, successful_rows, rejected_rows, duplicate_rows)
            VALUES (?, ?, ?, ?, ?);
            """,
            (filename, total_rows, successful_rows, rejected_rows, duplicate_rows),
        )
        batch_id: int = cur.lastrowid

        # 6. Insert all valid transactions linking to batch_id
        for txn in rows_to_insert:
            conn.execute(
                """
                INSERT INTO transactions
                    (date, category_id, amount, payment_method, description, type, import_batch_id)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    txn["date"],
                    txn["resolved_category_id"],
                    txn["amount"],
                    txn["payment_method"],
                    txn["description"],
                    txn["type"],
                    batch_id,
                ),
            )

    # 7. Post-commit export generation (optional, never blocks persistence)
    final_dupes_df = pd.DataFrame(final_dupe_rows) if final_dupe_rows else pd.DataFrame()
    imported_df = pd.DataFrame(rows_to_insert) if rows_to_insert else pd.DataFrame()

    rej_path: Optional[str] = None
    dupe_path: Optional[str] = None

    if export_rejected and not rejected_df.empty:
        try:
            path_obj = export_rejected_transactions(rejected_df, filename, export_dir=export_dir)
            rej_path = str(path_obj)
        except Exception as exc:
            logger.warning("Could not export rejected transactions: %s", exc)

    if export_duplicates and not final_dupes_df.empty:
        try:
            path_obj = export_duplicate_candidates(final_dupes_df, filename, export_dir=export_dir)
            dupe_path = str(path_obj)
        except Exception as exc:
            logger.warning("Could not export duplicate candidates: %s", exc)

    logger.info(
        "Successfully committed Import Batch #%d ('%s'): %d imported, %d rejected, %d duplicates.",
        batch_id,
        filename,
        successful_rows,
        rejected_rows,
        duplicate_rows,
    )

    return ImportSummary(
        batch_id=batch_id,
        filename=filename,
        total_rows=total_rows,
        successful_rows=successful_rows,
        rejected_rows=rejected_rows,
        duplicate_rows=duplicate_rows,
        imported_transactions=imported_df,
        rejected_transactions=rejected_df,
        duplicate_candidates=final_dupes_df,
        rejected_export_path=rej_path,
        duplicate_export_path=dupe_path,
    )


# ---------------------------------------------------------------------------
# Import History & Batch Introspection
# ---------------------------------------------------------------------------

def get_import_history(
    db_path: Optional[Union[Path, str]] = None,
) -> list[dict[str, Any]]:
    """
    Retrieve audit history of all import batches, ordered newest first.

    Returns
    -------
    list of dict
        Each dict represents an import batch with id, filename, imported_at,
        total_rows, successful_rows, rejected_rows, and duplicate_rows.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, filename, imported_at, total_rows, successful_rows,
                   rejected_rows, duplicate_rows
            FROM import_batches
            ORDER BY imported_at DESC, id DESC;
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def get_import_batch(
    batch_id: int,
    db_path: Optional[Union[Path, str]] = None,
) -> Optional[dict[str, Any]]:
    """
    Retrieve details for a specific import batch by ID.

    Returns
    -------
    dict or None
        Batch details dict if found, or None if no batch with that ID exists.
    """
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, filename, imported_at, total_rows, successful_rows,
                   rejected_rows, duplicate_rows
            FROM import_batches
            WHERE id = ?;
            """,
            (batch_id,),
        ).fetchone()
        return dict(row) if row else None


def get_batch_transactions(
    batch_id: int,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Retrieve all transactions inserted under a specific import batch ID.

    Returns
    -------
    pd.DataFrame
        DataFrame of transactions for the specified batch.
    """
    with get_connection(db_path) as conn:
        query = """
            SELECT t.id, t.date, c.name AS category, t.amount,
                   t.payment_method, t.description, t.type,
                   t.import_batch_id, t.created_at
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.import_batch_id = ?
            ORDER BY t.date ASC, t.id ASC;
        """
        return pd.read_sql_query(query, conn, params=[batch_id])


# ---------------------------------------------------------------------------
# Export Utilities
# ---------------------------------------------------------------------------

def export_rejected_transactions(
    rejected_df: pd.DataFrame,
    source_filename: str,
    export_dir: Optional[Union[Path, str]] = None,
) -> Path:
    """
    Export rejected rows to a CSV file in outputs/exports/.

    Filename format: <source_stem>_rejected_<timestamp>.csv
    """
    target_dir = Path(export_dir) if export_dir else DEFAULT_EXPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(source_filename).stem.replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = target_dir / f"{stem}_rejected_{timestamp}.csv"

    rejected_df.to_csv(out_file, index=False, encoding="utf-8")
    logger.info("Exported rejected transactions to %s", out_file)
    return out_file


def export_duplicate_candidates(
    duplicates_df: pd.DataFrame,
    source_filename: str,
    export_dir: Optional[Union[Path, str]] = None,
) -> Path:
    """
    Export duplicate candidates to a CSV file in outputs/exports/.

    Filename format: <source_stem>_duplicates_<timestamp>.csv
    """
    target_dir = Path(export_dir) if export_dir else DEFAULT_EXPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(source_filename).stem.replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = target_dir / f"{stem}_duplicates_{timestamp}.csv"

    duplicates_df.to_csv(out_file, index=False, encoding="utf-8")
    logger.info("Exported duplicate candidates to %s", out_file)
    return out_file
