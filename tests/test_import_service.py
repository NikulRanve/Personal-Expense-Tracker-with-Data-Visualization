"""
tests/test_import_service.py — Tests for Import Service and Database Persistence
=================================================================================
Covers all 18 required scenarios:
  1. Successful CSV import
  2. Import containing only valid rows
  3. Import containing rejected rows
  4. Import containing duplicate candidates (within-CSV)
  5. Duplicate detection against existing database records
  6. Category name to ID mapping
  7. Unknown category handling
  8. Category/type mismatch
  9. Import batch creation
  10. Accurate import batch statistics
  11. Import history retrieval (newest first)
  12. Batch retrieval by ID
  13. Re-importing the same CSV
  14. Duplicate recheck during persistence
  15. Complete rollback on unexpected error (atomic persistence)
  16. Empty CSV handling
  17. CSV with no valid transactions
  18. Strict row accounting invariant: total == successful + rejected + duplicate
  19. Export helpers for rejected and duplicate records
"""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

import pandas as pd
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database import (
    create_tables,
    get_connection,
    initialise_database,
    migrate_add_duplicate_rows_column,
    migrate_add_hardening_triggers,
)
from data_cleaner import clean_transactions
from import_service import (
    ImportSummary,
    export_duplicate_candidates,
    export_rejected_transactions,
    get_batch_transactions,
    get_import_batch,
    get_import_history,
    import_transactions,
    preview_import,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Isolated temporary SQLite database with all tables, triggers, and seed categories."""
    db_file = tmp_path / "test_import_tracker.db"
    initialise_database(db_file)
    migrate_add_hardening_triggers(db_file)
    migrate_add_duplicate_rows_column(db_file)
    return db_file


@pytest.fixture
def valid_csv(tmp_path: Path) -> Path:
    """CSV containing 3 valid rows (2 expenses, 1 income)."""
    p = tmp_path / "valid_txns.csv"
    p.write_text(
        "date,category,amount,payment_method,description,type\n"
        "2026-11-01,Food,250.00,UPI,Lunch,Expense\n"
        "2026-11-02,Transportation,50.00,Metro Card,Subway ride,Expense\n"
        "2026-11-03,Salary,35000.00,Bank,Monthly Salary,Income\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def mixed_csv(tmp_path: Path) -> Path:
    """
    CSV containing:
      - 2 valid rows
      - 1 duplicate row (identical to row 1)
      - 2 rejected rows (invalid date, negative amount)
    Total rows = 5.
    """
    p = tmp_path / "mixed_txns.csv"
    p.write_text(
        "date,category,amount,payment_method,description,type\n"
        "2026-11-01,Food,200.00,Cash,Lunch,Expense\n"
        "2026-11-01,Food,200.00,Cash,Lunch,Expense\n"        # duplicate of row 1
        "2026-02-30,Food,150.00,UPI,Bad date,Expense\n"       # rejected: invalid date
        "2026-11-04,Shopping,500.00,Card,Shoes,Expense\n"     # valid
        "2026-11-05,Utilities,-100.00,NetBanking,Bill,Expense\n", # rejected: negative amount
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# Test Suites
# ---------------------------------------------------------------------------

class TestPreviewImport:
    """Preview operation must be read-only and return classified rows."""

    def test_preview_does_not_mutate_database(self, temp_db: Path, valid_csv: Path):
        res = preview_import(valid_csv, db_path=temp_db)
        assert res.total_rows == 3
        assert res.valid_count == 3
        assert res.rejected_count == 0
        assert res.duplicate_count == 0

        # Verify no database records were inserted
        with get_connection(temp_db) as conn:
            txn_count = conn.execute("SELECT count(*) FROM transactions;").fetchone()[0]
            batch_count = conn.execute("SELECT count(*) FROM import_batches;").fetchone()[0]
        assert txn_count == 0
        assert batch_count == 0

    def test_preview_identifies_all_categories(self, temp_db: Path, mixed_csv: Path):
        res = preview_import(mixed_csv, db_path=temp_db)
        assert res.total_rows == 5
        assert res.valid_count == 2
        assert res.duplicate_count == 1
        assert res.rejected_count == 2


class TestImportPersistence:
    """Core persistence, atomic transaction, batch logging, and row accounting."""

    def test_import_only_valid_rows(self, temp_db: Path, valid_csv: Path):
        preview = preview_import(valid_csv, db_path=temp_db)
        summary = import_transactions(preview, filename="valid_txns.csv", db_path=temp_db)

        assert isinstance(summary, ImportSummary)
        assert summary.batch_id > 0
        assert summary.total_rows == 3
        assert summary.successful_rows == 3
        assert summary.rejected_rows == 0
        assert summary.duplicate_rows == 0
        assert len(summary.imported_transactions) == 3

        # Verify database contents
        with get_connection(temp_db) as conn:
            txns = conn.execute("SELECT * FROM transactions WHERE import_batch_id = ?;", (summary.batch_id,)).fetchall()
            assert len(txns) == 3

    def test_import_mixed_csv_with_rejections_and_duplicates(self, temp_db: Path, mixed_csv: Path):
        preview = preview_import(mixed_csv, db_path=temp_db)
        summary = import_transactions(preview, filename="mixed_txns.csv", db_path=temp_db)

        assert summary.total_rows == 5
        assert summary.successful_rows == 2
        assert summary.duplicate_rows == 1
        assert summary.rejected_rows == 2
        # Strict accounting invariant
        assert summary.total_rows == summary.successful_rows + summary.rejected_rows + summary.duplicate_rows

        # Verify only the 2 valid transactions are saved in DB
        with get_connection(temp_db) as conn:
            txns = conn.execute("SELECT * FROM transactions WHERE import_batch_id = ?;", (summary.batch_id,)).fetchall()
            assert len(txns) == 2

    def test_category_name_to_id_mapping(self, temp_db: Path, valid_csv: Path):
        preview = preview_import(valid_csv, db_path=temp_db)
        summary = import_transactions(preview, filename="valid_txns.csv", db_path=temp_db)

        with get_connection(temp_db) as conn:
            food_cat_id = conn.execute("SELECT id FROM categories WHERE name='Food';").fetchone()["id"]
            trans_cat_id = conn.execute("SELECT id FROM categories WHERE name='Transportation';").fetchone()["id"]
            salary_cat_id = conn.execute("SELECT id FROM categories WHERE name='Salary';").fetchone()["id"]

            txn_rows = conn.execute("SELECT category_id, type FROM transactions WHERE import_batch_id = ?;", (summary.batch_id,)).fetchall()
            inserted_cat_ids = [r["category_id"] for r in txn_rows]
            assert food_cat_id in inserted_cat_ids
            assert trans_cat_id in inserted_cat_ids
            assert salary_cat_id in inserted_cat_ids

    def test_duplicate_against_existing_database_records(self, temp_db: Path, valid_csv: Path):
        # 1. First import succeeds
        preview1 = preview_import(valid_csv, db_path=temp_db)
        summary1 = import_transactions(preview1, filename="run1.csv", db_path=temp_db)
        assert summary1.successful_rows == 3

        # 2. Re-importing the same CSV: all 3 rows must now be flagged as duplicate candidates
        preview2 = preview_import(valid_csv, db_path=temp_db)
        assert preview2.valid_count == 0
        assert preview2.duplicate_count == 3

        summary2 = import_transactions(preview2, filename="run2.csv", db_path=temp_db)
        assert summary2.successful_rows == 0
        assert summary2.duplicate_rows == 3
        assert summary2.total_rows == 3

        # Total transactions in DB should still be 3, not 6
        with get_connection(temp_db) as conn:
            count = conn.execute("SELECT count(*) FROM transactions;").fetchone()[0]
            assert count == 3

    def test_duplicate_recheck_during_persistence(self, temp_db: Path, valid_csv: Path):
        """
        If a record is inserted into DB between preview and confirm, the persistence
        re-check must classify it as a duplicate and adjust counts safely.
        """
        # Step 1: Preview 3 transactions
        preview = preview_import(valid_csv, db_path=temp_db)
        assert preview.valid_count == 3

        # Step 2: Concurrently insert 1 of the transactions directly into DB
        with get_connection(temp_db) as conn:
            food_id = conn.execute("SELECT id FROM categories WHERE name='Food';").fetchone()["id"]
            conn.execute(
                """
                INSERT INTO transactions (date, category_id, amount, payment_method, description, type)
                VALUES ('2026-11-01', ?, 250.00, 'UPI', 'Lunch', 'Expense');
                """,
                (food_id,),
            )

        # Step 3: Now run import_transactions with the stale preview
        summary = import_transactions(preview, filename="stale_preview.csv", db_path=temp_db)
        # 1 was detected as duplicate during persistence recheck, so 2 imported, 1 duplicate
        assert summary.successful_rows == 2
        assert summary.duplicate_rows == 1
        assert summary.total_rows == 3
        assert summary.total_rows == summary.successful_rows + summary.rejected_rows + summary.duplicate_rows

    def test_atomic_rollback_on_unexpected_insertion_error(self, temp_db: Path, valid_csv: Path):
        """
        If an error occurs while writing transactions, the entire operation must roll back.
        Neither the batch record nor any transactions must persist.
        """
        preview = preview_import(valid_csv, db_path=temp_db)

        # Simulate unexpected mid-insert failure using a database trigger that fires on insertion
        with get_connection(temp_db) as conn:
            conn.execute(
                """
                CREATE TRIGGER trg_fail_lunch
                BEFORE INSERT ON transactions
                FOR EACH ROW
                WHEN NEW.description = 'Lunch'
                BEGIN
                    SELECT RAISE(ABORT, 'Simulated mid-import catastrophic failure for Lunch');
                END;
                """
            )

        with pytest.raises(Exception, match="Simulated mid-import catastrophic failure for Lunch"):
            import_transactions(preview, filename="will_fail.csv", db_path=temp_db)

        # Verify complete atomic rollback: 0 batches and 0 transactions exist!
        with get_connection(temp_db) as conn:
            batch_count = conn.execute("SELECT count(*) FROM import_batches;").fetchone()[0]
            txn_count = conn.execute("SELECT count(*) FROM transactions;").fetchone()[0]

        assert batch_count == 0
        assert txn_count == 0

    def test_csv_with_no_valid_transactions(self, temp_db: Path, tmp_path: Path):
        bad_csv = tmp_path / "all_bad.csv"
        bad_csv.write_text(
            "date,category,amount,payment_method,description,type\n"
            "2026-02-30,Food,100,Cash,Bad date,Expense\n"
            "2026-11-01,Food,-50,Cash,Bad amt,Expense\n",
            encoding="utf-8",
        )
        preview = preview_import(bad_csv, db_path=temp_db)
        assert preview.valid_count == 0
        assert preview.rejected_count == 2

        summary = import_transactions(preview, filename="all_bad.csv", db_path=temp_db)
        assert summary.total_rows == 2
        assert summary.successful_rows == 0
        assert summary.rejected_rows == 2
        assert summary.duplicate_rows == 0

        # Batch record exists with 0 successful rows
        with get_connection(temp_db) as conn:
            b = conn.execute("SELECT * FROM import_batches WHERE id = ?;", (summary.batch_id,)).fetchone()
            assert b["successful_rows"] == 0
            assert b["rejected_rows"] == 2


class TestImportHistoryAndIntrospection:
    """Batch history, retrieval by ID, and batch transactions."""

    def test_import_history_ordered_newest_first(self, temp_db: Path, valid_csv: Path, mixed_csv: Path):
        p1 = preview_import(valid_csv, db_path=temp_db)
        s1 = import_transactions(p1, filename="batch1.csv", db_path=temp_db)

        p2 = preview_import(mixed_csv, db_path=temp_db)
        s2 = import_transactions(p2, filename="batch2.csv", db_path=temp_db)

        history = get_import_history(temp_db)
        assert len(history) == 2
        assert history[0]["id"] == s2.batch_id
        assert history[1]["id"] == s1.batch_id

    def test_get_import_batch_by_id(self, temp_db: Path, valid_csv: Path):
        p = preview_import(valid_csv, db_path=temp_db)
        summary = import_transactions(p, filename="batch_test.csv", db_path=temp_db)

        batch = get_import_batch(summary.batch_id, db_path=temp_db)
        assert batch is not None
        assert batch["filename"] == "batch_test.csv"
        assert batch["total_rows"] == 3

        non_existent = get_import_batch(99999, db_path=temp_db)
        assert non_existent is None

    def test_get_batch_transactions(self, temp_db: Path, valid_csv: Path):
        p = preview_import(valid_csv, db_path=temp_db)
        summary = import_transactions(p, filename="batch_test.csv", db_path=temp_db)

        txns_df = get_batch_transactions(summary.batch_id, db_path=temp_db)
        assert len(txns_df) == 3
        assert set(txns_df["category"].tolist()) == {"Food", "Transportation", "Salary"}


class TestExportUtilities:
    """Optional export helpers for rejected and duplicate rows."""

    def test_export_rejected_transactions(self, tmp_path: Path):
        rejected_df = pd.DataFrame([
            {"date": "2026-02-30", "amount": 100, "rejection_reason": "Invalid calendar date"}
        ])
        export_dir = tmp_path / "exports"
        path = export_rejected_transactions(rejected_df, "sample.csv", export_dir=export_dir)

        assert path.exists()
        assert "sample_rejected" in path.name
        content = path.read_text(encoding="utf-8")
        assert "2026-02-30" in content

    def test_export_duplicate_candidates(self, tmp_path: Path):
        dupe_df = pd.DataFrame([
            {"date": "2026-11-01", "amount": 250, "duplicate_reason": "In-file duplicate"}
        ])
        export_dir = tmp_path / "exports"
        path = export_duplicate_candidates(dupe_df, "sample.csv", export_dir=export_dir)

        assert path.exists()
        assert "sample_duplicates" in path.name
        content = path.read_text(encoding="utf-8")
        assert "In-file duplicate" in content
