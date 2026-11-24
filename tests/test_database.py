"""
tests/test_database.py — Database Layer Tests
===============================================
Comprehensive test suite for src/database.py.

Every test uses a temporary database (via pytest's tmp_path fixture) so
the real project database is NEVER touched.

Coverage
--------
 1.  Successful database connection
 2.  All four tables are created
 3.  Foreign keys are enabled on every connection
 4.  Default categories are inserted with correct names and types
 5.  Seeding is idempotent — running twice creates no duplicates
 6.  Duplicate categories are rejected (UNIQUE constraint)
 7.  Negative amounts are rejected (CHECK constraint)
 8.  Zero amounts are rejected (CHECK constraint)
 9.  Invalid transaction type values are rejected (CHECK constraint)
 10. Transaction type must match its category type (trigger)
 11. Invalid category foreign key is rejected
 12. Budgets cannot be assigned to Income categories (trigger)
 13. Duplicate monthly budgets are rejected (UNIQUE constraint)
 14. Failed transactions are rolled back cleanly
 15. Connection is closed after context-manager usage

Also preserves the original five placeholder tests in test_analytics.py.
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date_type
from pathlib import Path

import pytest

# Make sure src/ is importable when running pytest from the project root
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database import (
    create_tables,
    foreign_keys_enabled,
    get_connection,
    get_table_names,
    seed_categories,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> Path:
    """
    Provide a fresh, initialised database in a temp directory.

    Returns the Path to the .db file.
    Every test that uses this fixture gets its own isolated database.
    """
    db_path = tmp_path / "test_expense_tracker.db"
    create_tables(db_path)
    seed_categories(db_path)
    return db_path


@pytest.fixture()
def empty_db(tmp_path: Path) -> Path:
    """A database with tables created but no categories seeded."""
    db_path = tmp_path / "empty_expense_tracker.db"
    create_tables(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Helper: insert a category and return its id
# ---------------------------------------------------------------------------

def _insert_category(conn: sqlite3.Connection, name: str, cat_type: str) -> int:
    cur = conn.execute(
        "INSERT INTO categories (name, type) VALUES (?, ?);", (name, cat_type)
    )
    return cur.lastrowid


def _insert_transaction(
    conn: sqlite3.Connection,
    *,
    date: str = "2026-11-01",
    category_id: int,
    amount: float = 100.0,
    txn_type: str,
    payment_method: str = "Cash",
    description: str = "Test",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO transactions
            (date, category_id, amount, type, payment_method, description)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (date, category_id, amount, txn_type, payment_method, description),
    )
    return cur.lastrowid


# ===========================================================================
# Test 1 — Successful database connection
# ===========================================================================

class TestConnection:
    def test_connection_opens_and_yields_connection_object(self, tmp_path: Path):
        """get_connection() must yield a live sqlite3.Connection."""
        db_path = tmp_path / "conn_test.db"
        with get_connection(db_path) as conn:
            assert isinstance(conn, sqlite3.Connection)
            result = conn.execute("SELECT 1;").fetchone()
            assert result[0] == 1

    def test_row_factory_is_sqlite_row(self, tmp_path: Path):
        """Rows returned by the connection must be sqlite3.Row instances."""
        db_path = tmp_path / "row_factory.db"
        create_tables(db_path)
        seed_categories(db_path)
        with get_connection(db_path) as conn:
            row = conn.execute("SELECT name, type FROM categories LIMIT 1;").fetchone()
        # sqlite3.Row supports key-based access
        assert "name" in row.keys()
        assert "type" in row.keys()


# ===========================================================================
# Test 2 — All four tables are created
# ===========================================================================

class TestTableCreation:
    def test_all_four_tables_exist(self, db: Path):
        """create_tables() must produce exactly the four required tables."""
        tables = get_table_names(db)
        assert "categories"     in tables
        assert "transactions"   in tables
        assert "budgets"        in tables
        assert "import_batches" in tables

    def test_create_tables_is_idempotent(self, db: Path):
        """Calling create_tables() a second time must not raise or drop data."""
        # Seed a custom category first
        with get_connection(db) as conn:
            conn.execute(
                "INSERT INTO categories (name, type) VALUES ('Custom', 'Expense');"
            )

        # Re-run create_tables — must not wipe the custom category
        create_tables(db)

        with get_connection(db) as conn:
            names = [
                r["name"]
                for r in conn.execute("SELECT name FROM categories;").fetchall()
            ]
        assert "Custom" in names

    def test_import_batches_columns(self, db: Path):
        """import_batches table must have all required columns."""
        with get_connection(db) as conn:
            info = conn.execute("PRAGMA table_info(import_batches);").fetchall()
        col_names = {row["name"] for row in info}
        expected = {"id", "filename", "imported_at",
                    "total_rows", "successful_rows", "rejected_rows"}
        assert expected.issubset(col_names)


# ===========================================================================
# Test 3 — Foreign keys are enabled
# ===========================================================================

class TestForeignKeys:
    def test_foreign_keys_pragma_is_on(self, db: Path):
        """PRAGMA foreign_keys must return 1 on every new connection."""
        assert foreign_keys_enabled(db) is True

    def test_foreign_keys_active_on_multiple_connections(self, tmp_path: Path):
        """Each new call to get_connection() must re-enable foreign keys."""
        db_path = tmp_path / "fk_multi.db"
        create_tables(db_path)
        for _ in range(3):
            assert foreign_keys_enabled(db_path) is True


# ===========================================================================
# Test 4 — Default categories inserted correctly
# ===========================================================================

class TestSeedCategories:
    _EXPECTED_EXPENSE = {
        "Food", "Transportation", "Housing",
        "Utilities", "Healthcare", "Shopping",
    }
    _EXPECTED_INCOME = {"Salary", "Other Income"}

    def test_eight_default_categories_inserted(self, db: Path):
        """seed_categories() must insert exactly 8 rows."""
        with get_connection(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM categories;").fetchone()[0]
        assert count == 8

    def test_expense_category_names_correct(self, db: Path):
        with get_connection(db) as conn:
            rows = conn.execute(
                "SELECT name FROM categories WHERE type = 'Expense';"
            ).fetchall()
        names = {r["name"] for r in rows}
        assert names == self._EXPECTED_EXPENSE

    def test_income_category_names_correct(self, db: Path):
        with get_connection(db) as conn:
            rows = conn.execute(
                "SELECT name FROM categories WHERE type = 'Income';"
            ).fetchall()
        names = {r["name"] for r in rows}
        assert names == self._EXPECTED_INCOME

    def test_seed_returns_inserted_count(self, empty_db: Path):
        """seed_categories() must return the number of rows actually inserted."""
        inserted = seed_categories(empty_db)
        assert inserted == 8


# ===========================================================================
# Test 5 — Seeding is idempotent (no duplicates on re-run)
# ===========================================================================

class TestSeedIdempotency:
    def test_double_seed_produces_no_duplicates(self, db: Path):
        """Running seed_categories() twice must not increase the row count."""
        second_run_inserted = seed_categories(db)
        assert second_run_inserted == 0

        with get_connection(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM categories;").fetchone()[0]
        assert count == 8

    def test_triple_seed_still_no_duplicates(self, db: Path):
        seed_categories(db)
        seed_categories(db)
        with get_connection(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM categories;").fetchone()[0]
        assert count == 8


# ===========================================================================
# Test 6 — Duplicate categories are rejected
# ===========================================================================

class TestDuplicateCategory:
    def test_duplicate_name_and_type_rejected(self, db: Path):
        """Inserting (Food, Expense) twice must raise IntegrityError."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    "INSERT INTO categories (name, type) VALUES ('Food', 'Expense');"
                )

    def test_same_name_different_type_allowed(self, db: Path):
        """Same name with a different type must be allowed (different UNIQUE key)."""
        # 'Food' as Income doesn't exist yet — should insert fine
        with get_connection(db) as conn:
            conn.execute(
                "INSERT INTO categories (name, type) VALUES ('Food', 'Income');"
            )
        with get_connection(db) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM categories WHERE name='Food';"
            ).fetchone()[0]
        assert count == 2


# ===========================================================================
# Test 7 & 8 — Negative and zero amounts are rejected
# ===========================================================================

class TestTransactionAmountConstraints:
    def _get_expense_category_id(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
        ).fetchone()
        return row["id"]

    def test_negative_amount_rejected(self, db: Path):
        """Transactions with amount < 0 must be rejected by CHECK constraint."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                cat_id = self._get_expense_category_id(conn)
                _insert_transaction(
                    conn,
                    category_id=cat_id,
                    amount=-50.0,
                    txn_type="Expense",
                )

    def test_zero_amount_rejected(self, db: Path):
        """Transactions with amount == 0 must be rejected by CHECK constraint."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                cat_id = self._get_expense_category_id(conn)
                _insert_transaction(
                    conn,
                    category_id=cat_id,
                    amount=0.0,
                    txn_type="Expense",
                )

    def test_positive_amount_accepted(self, db: Path):
        """Transactions with amount > 0 must be accepted."""
        with get_connection(db) as conn:
            cat_id = self._get_expense_category_id(conn)
            row_id = _insert_transaction(
                conn,
                category_id=cat_id,
                amount=250.0,
                txn_type="Expense",
            )
        assert row_id is not None and row_id > 0


# ===========================================================================
# Test 9 — Invalid transaction type values are rejected
# ===========================================================================

class TestTransactionTypeConstraint:
    def test_invalid_type_rejected(self, db: Path):
        """Transaction type must be 'Income' or 'Expense'."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                cat_id = conn.execute(
                    "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
                ).fetchone()["id"]
                conn.execute(
                    """
                    INSERT INTO transactions
                        (date, category_id, amount, type)
                    VALUES ('2026-11-01', ?, 100.0, 'Other');
                    """,
                    (cat_id,),
                )

    def test_valid_expense_type_accepted(self, db: Path):
        with get_connection(db) as conn:
            cat_id = conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]
            row_id = _insert_transaction(
                conn, category_id=cat_id, amount=100.0, txn_type="Expense"
            )
        assert row_id > 0

    def test_valid_income_type_accepted(self, db: Path):
        with get_connection(db) as conn:
            cat_id = conn.execute(
                "SELECT id FROM categories WHERE type='Income' LIMIT 1;"
            ).fetchone()["id"]
            row_id = _insert_transaction(
                conn, category_id=cat_id, amount=5000.0, txn_type="Income"
            )
        assert row_id > 0


# ===========================================================================
# Test 10 — Transaction type must match category type (trigger)
# ===========================================================================

class TestTransactionCategoryTypeMismatch:
    def test_expense_txn_on_income_category_rejected(self, db: Path):
        """Trigger must abort INSERT when txn.type != category.type."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                # Get an Income category id
                income_cat_id = conn.execute(
                    "SELECT id FROM categories WHERE type='Income' LIMIT 1;"
                ).fetchone()["id"]
                # Try to insert an Expense transaction against it
                _insert_transaction(
                    conn,
                    category_id=income_cat_id,
                    amount=100.0,
                    txn_type="Expense",    # mismatch!
                )

    def test_income_txn_on_expense_category_rejected(self, db: Path):
        """Trigger must abort when income txn maps to expense category."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                expense_cat_id = conn.execute(
                    "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
                ).fetchone()["id"]
                _insert_transaction(
                    conn,
                    category_id=expense_cat_id,
                    amount=5000.0,
                    txn_type="Income",    # mismatch!
                )

    def test_matching_types_accepted(self, db: Path):
        """Transactions whose type matches the category type must succeed."""
        with get_connection(db) as conn:
            expense_cat_id = conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]
            row_id = _insert_transaction(
                conn, category_id=expense_cat_id, amount=100.0, txn_type="Expense"
            )
        assert row_id > 0


# ===========================================================================
# Test 11 — Invalid category foreign key is rejected
# ===========================================================================

class TestForeignKeyEnforcement:
    def test_nonexistent_category_id_rejected(self, db: Path):
        """Inserting a transaction with a non-existent category_id must fail."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    """
                    INSERT INTO transactions
                        (date, category_id, amount, type)
                    VALUES ('2026-11-01', 99999, 100.0, 'Expense');
                    """
                )

    def test_valid_category_id_accepted(self, db: Path):
        """A transaction referencing a real category_id must succeed."""
        with get_connection(db) as conn:
            cat_id = conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]
            row_id = _insert_transaction(
                conn, category_id=cat_id, amount=100.0, txn_type="Expense"
            )
        assert row_id > 0


# ===========================================================================
# Test 12 — Budgets cannot be assigned to Income categories
# ===========================================================================

class TestBudgetExpenseOnlyConstraint:
    def test_income_category_budget_rejected(self, db: Path):
        """Trigger must abort a budget INSERT on an Income category."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                income_cat_id = conn.execute(
                    "SELECT id FROM categories WHERE type='Income' LIMIT 1;"
                ).fetchone()["id"]
                conn.execute(
                    """
                    INSERT INTO budgets (category_id, month, limit_amount)
                    VALUES (?, '2026-11', 10000.0);
                    """,
                    (income_cat_id,),
                )

    def test_expense_category_budget_accepted(self, db: Path):
        """A budget on an Expense category must succeed."""
        with get_connection(db) as conn:
            expense_cat_id = conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT INTO budgets (category_id, month, limit_amount)
                VALUES (?, '2026-11', 5000.0);
                """,
                (expense_cat_id,),
            )
        # Verify it was stored
        with get_connection(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM budgets;").fetchone()[0]
        assert count == 1


# ===========================================================================
# Test 13 — Duplicate monthly budgets are rejected
# ===========================================================================

class TestDuplicateBudget:
    def _get_expense_cat_id(self, db: Path) -> int:
        with get_connection(db) as conn:
            return conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]

    def test_duplicate_category_month_budget_rejected(self, db: Path):
        """Two budgets for the same category+month must violate UNIQUE."""
        cat_id = self._get_expense_cat_id(db)

        with get_connection(db) as conn:
            conn.execute(
                "INSERT INTO budgets (category_id, month, limit_amount) VALUES (?,?,?);",
                (cat_id, "2026-11", 5000.0),
            )

        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    "INSERT INTO budgets (category_id, month, limit_amount) VALUES (?,?,?);",
                    (cat_id, "2026-11", 8000.0),
                )

    def test_same_category_different_month_allowed(self, db: Path):
        """Same category, different month → two separate budgets allowed."""
        cat_id = self._get_expense_cat_id(db)
        with get_connection(db) as conn:
            conn.execute(
                "INSERT INTO budgets (category_id, month, limit_amount) VALUES (?,?,?);",
                (cat_id, "2026-10", 4000.0),
            )
            conn.execute(
                "INSERT INTO budgets (category_id, month, limit_amount) VALUES (?,?,?);",
                (cat_id, "2026-11", 5000.0),
            )
        with get_connection(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM budgets;").fetchone()[0]
        assert count == 2


# ===========================================================================
# Test 14 — Failed transactions are rolled back
# ===========================================================================

class TestRollback:
    def test_rollback_on_constraint_violation(self, db: Path):
        """
        When a constraint is violated mid-transaction, the entire transaction
        (including any preceding valid inserts in the same block) must roll back.
        """
        with get_connection(db) as conn:
            # Count categories before attempted bad insert
            before = conn.execute("SELECT COUNT(*) FROM categories;").fetchone()[0]

        # Attempt an operation that will fail inside a with-block
        try:
            with get_connection(db) as conn:
                # This first insert would succeed on its own ...
                conn.execute(
                    "INSERT INTO categories (name, type) VALUES ('TempCat', 'Expense');"
                )
                # ... but this duplicate will raise IntegrityError
                conn.execute(
                    "INSERT INTO categories (name, type) VALUES ('TempCat', 'Expense');"
                )
        except sqlite3.IntegrityError:
            pass   # expected

        # After rollback, row count must be unchanged
        with get_connection(db) as conn:
            after = conn.execute("SELECT COUNT(*) FROM categories;").fetchone()[0]

        assert after == before, (
            f"Rollback failed: count went from {before} to {after}"
        )

    def test_successful_transaction_persists(self, db: Path):
        """A clean transaction (no errors) must be committed and readable."""
        with get_connection(db) as conn:
            conn.execute(
                "INSERT INTO categories (name, type) VALUES ('MyNewCat', 'Expense');"
            )

        with get_connection(db) as conn:
            row = conn.execute(
                "SELECT name FROM categories WHERE name='MyNewCat';"
            ).fetchone()
        assert row is not None


# ===========================================================================
# Test 15 — Connection is closed after context-manager usage
# ===========================================================================

class TestConnectionLifecycle:
    def test_connection_closed_after_context_exit(self, tmp_path: Path):
        """
        After the with-block, the connection object must be closed.
        Attempting to use it again must raise ProgrammingError.
        """
        db_path = tmp_path / "lifecycle.db"
        create_tables(db_path)

        captured_conn: sqlite3.Connection | None = None

        with get_connection(db_path) as conn:
            captured_conn = conn
            conn.execute("SELECT 1;")

        # Connection is now closed — any further use must raise
        with pytest.raises(Exception):
            captured_conn.execute("SELECT 1;")

    def test_connection_closed_even_on_exception(self, tmp_path: Path):
        """
        The connection must be closed even when an exception occurs inside
        the with-block (finally block must always run).
        """
        db_path = tmp_path / "exception_close.db"
        create_tables(db_path)

        captured_conn = None
        try:
            with get_connection(db_path) as conn:
                captured_conn = conn
                raise RuntimeError("Simulated failure")
        except RuntimeError:
            pass

        with pytest.raises(Exception):
            captured_conn.execute("SELECT 1;")


# ===========================================================================
# Additional edge-case tests
# ===========================================================================

class TestImportBatchConstraints:
    def test_negative_total_rows_rejected(self, db: Path):
        """import_batches.total_rows must not go negative."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    "INSERT INTO import_batches (filename, total_rows) VALUES ('f.csv', -1);"
                )

    def test_successful_rows_exceeding_total_rejected(self, db: Path):
        """successful_rows > total_rows must violate the CHECK constraint."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    """
                    INSERT INTO import_batches
                        (filename, total_rows, successful_rows, rejected_rows)
                    VALUES ('f.csv', 5, 10, 0);
                    """
                )

    def test_valid_import_batch_accepted(self, db: Path):
        """A valid import_batches row must be persisted without error."""
        with get_connection(db) as conn:
            cur = conn.execute(
                """
                INSERT INTO import_batches
                    (filename, total_rows, successful_rows, rejected_rows)
                VALUES ('data.csv', 100, 95, 5);
                """
            )
        assert cur.lastrowid > 0


class TestEmptyCategoryName:
    def test_empty_category_name_rejected(self, db: Path):
        """An empty or whitespace-only category name must be rejected."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    "INSERT INTO categories (name, type) VALUES ('   ', 'Expense');"
                )

    def test_whitespace_only_name_rejected(self, db: Path):
        """Tabs and spaces only should be caught by the CHECK(length(trim()))."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    "INSERT INTO categories (name, type) VALUES ('\t\n', 'Income');"
                )


# ===========================================================================
# Session 2b — Database Hardening Tests
# ===========================================================================
# Appended without modifying existing tests above.
# Imports are already present at the top of this file.

from database import (
    migrate_add_hardening_triggers,
    validate_budget_month,
    validate_transaction_date,
    get_trigger_names,
)


class TestTransactionUpdateTrigger:
    """Tests for the BEFORE UPDATE trigger on transactions."""

    def _get_expense_cat_id(self, conn: sqlite3.Connection) -> int:
        return conn.execute(
            "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
        ).fetchone()["id"]

    def _get_income_cat_id(self, conn: sqlite3.Connection) -> int:
        return conn.execute(
            "SELECT id FROM categories WHERE type='Income' LIMIT 1;"
        ).fetchone()["id"]

    def _insert_expense_txn(self, db: Path, cat_id: int) -> int:
        """Insert a valid Expense transaction and return its id."""
        with get_connection(db) as conn:
            cur = conn.execute(
                """INSERT INTO transactions (date, category_id, amount, type)
                   VALUES ('2026-11-01', ?, 100.0, 'Expense');""",
                (cat_id,),
            )
            return cur.lastrowid

    def test_update_to_mismatching_category_rejected(self, db: Path):
        """BEFORE UPDATE trigger must reject: Expense txn → Income category."""
        with get_connection(db) as conn:
            expense_cat = self._get_expense_cat_id(conn)
            income_cat  = self._get_income_cat_id(conn)

        txn_id = self._insert_expense_txn(db, expense_cat)

        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                # Changing category to Income while type stays Expense → mismatch
                conn.execute(
                    "UPDATE transactions SET category_id = ? WHERE id = ?;",
                    (income_cat, txn_id),
                )

    def test_update_type_mismatch_with_new_category_rejected(self, db: Path):
        """UPDATE that sets both category_id and type with a mismatch is rejected."""
        with get_connection(db) as conn:
            expense_cat = self._get_expense_cat_id(conn)
            income_cat  = self._get_income_cat_id(conn)

        txn_id = self._insert_expense_txn(db, expense_cat)

        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                # type=Income but new category is Expense → trigger fires type check
                conn.execute(
                    "UPDATE transactions SET category_id = ?, type = 'Income' WHERE id = ?;",
                    (expense_cat, txn_id),   # Expense cat but Income type
                )

    def test_update_to_nonexistent_category_rejected(self, db: Path):
        """BEFORE UPDATE trigger must reject an update to a non-existent category_id."""
        with get_connection(db) as conn:
            expense_cat = self._get_expense_cat_id(conn)

        txn_id = self._insert_expense_txn(db, expense_cat)

        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    "UPDATE transactions SET category_id = 99999 WHERE id = ?;",
                    (txn_id,),
                )

    def test_update_to_matching_category_accepted(self, db: Path):
        """UPDATE to a different Expense category (same type) must succeed."""
        # Insert a second Expense category
        with get_connection(db) as conn:
            conn.execute(
                "INSERT INTO categories (name, type) VALUES ('Entertainment', 'Expense');"
            )
            expense_cat_1 = conn.execute(
                "SELECT id FROM categories WHERE name='Food';"
            ).fetchone()["id"]
            expense_cat_2 = conn.execute(
                "SELECT id FROM categories WHERE name='Entertainment';"
            ).fetchone()["id"]

        txn_id = self._insert_expense_txn(db, expense_cat_1)

        # Switching to another Expense category — no type mismatch
        with get_connection(db) as conn:
            conn.execute(
                "UPDATE transactions SET category_id = ? WHERE id = ?;",
                (expense_cat_2, txn_id),
            )

        with get_connection(db) as conn:
            row = conn.execute(
                "SELECT category_id FROM transactions WHERE id = ?;", (txn_id,)
            ).fetchone()
        assert row["category_id"] == expense_cat_2

    def test_insert_type_mismatch_still_blocked(self, db: Path):
        """Original BEFORE INSERT trigger must still reject type mismatches."""
        with get_connection(db) as conn:
            income_cat = self._get_income_cat_id(conn)

        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    """INSERT INTO transactions (date, category_id, amount, type)
                       VALUES ('2026-11-01', ?, 500.0, 'Expense');""",
                    (income_cat,),
                )


class TestCategoryTypeLock:
    """Tests for the trg_category_type_lock trigger."""

    def test_category_type_cannot_change_when_transactions_exist(self, db: Path):
        """Must be unable to flip type Expense→Income when transactions reference it."""
        with get_connection(db) as conn:
            expense_cat = conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]
            # Insert a transaction against that category
            conn.execute(
                """INSERT INTO transactions (date, category_id, amount, type)
                   VALUES ('2026-11-01', ?, 200.0, 'Expense');""",
                (expense_cat,),
            )

        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    "UPDATE categories SET type = 'Income' WHERE id = ?;",
                    (expense_cat,),
                )

    def test_category_type_cannot_change_when_budgets_exist(self, db: Path):
        """Must be unable to flip type Expense→Income when budgets reference it."""
        with get_connection(db) as conn:
            expense_cat = conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]
            conn.execute(
                """INSERT INTO budgets (category_id, month, limit_amount)
                   VALUES (?, '2026-11', 5000.0);""",
                (expense_cat,),
            )

        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    "UPDATE categories SET type = 'Income' WHERE id = ?;",
                    (expense_cat,),
                )

    def test_category_type_can_change_when_no_dependents(self, db: Path):
        """A fresh category with no transactions or budgets CAN have its type changed."""
        with get_connection(db) as conn:
            conn.execute(
                "INSERT INTO categories (name, type) VALUES ('TempCat', 'Expense');"
            )
            cat_id = conn.execute(
                "SELECT id FROM categories WHERE name='TempCat';"
            ).fetchone()["id"]

        # No transactions or budgets → type change is allowed
        with get_connection(db) as conn:
            conn.execute(
                "UPDATE categories SET type = 'Income' WHERE id = ?;", (cat_id,)
            )

        with get_connection(db) as conn:
            row = conn.execute(
                "SELECT type FROM categories WHERE id = ?;", (cat_id,)
            ).fetchone()
        assert row["type"] == "Income"

    def test_category_name_can_change_freely(self, db: Path):
        """The lock only applies to the type column; name updates are unrestricted."""
        with get_connection(db) as conn:
            expense_cat = conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]
            conn.execute(
                """INSERT INTO transactions (date, category_id, amount, type)
                   VALUES ('2026-11-01', ?, 300.0, 'Expense');""",
                (expense_cat,),
            )

        # Renaming (not changing type) must succeed even with dependents
        with get_connection(db) as conn:
            conn.execute(
                "UPDATE categories SET name = 'FoodRenamed' WHERE id = ?;",
                (expense_cat,),
            )

        with get_connection(db) as conn:
            row = conn.execute(
                "SELECT name FROM categories WHERE id = ?;", (expense_cat,)
            ).fetchone()
        assert row["name"] == "FoodRenamed"


class TestStrictDateValidation:
    """Tests for the trg_transaction_date_insert / _update triggers."""

    def _expense_cat_id(self, db: Path) -> int:
        with get_connection(db) as conn:
            return conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]

    def _insert_txn(self, db: Path, date_str: str) -> None:
        cat_id = self._expense_cat_id(db)
        with get_connection(db) as conn:
            conn.execute(
                """INSERT INTO transactions (date, category_id, amount, type)
                   VALUES (?, ?, 100.0, 'Expense');""",
                (date_str, cat_id),
            )

    # --- Invalid dates ---
    def test_feb_30_rejected(self, db: Path):
        """2026-02-30 does not exist — must be rejected."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_txn(db, "2026-02-30")

    def test_invalid_month_99_rejected(self, db: Path):
        """2026-99-45 — month 99 is invalid."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_txn(db, "2026-99-45")

    def test_invalid_month_00_rejected(self, db: Path):
        """2026-00-10 — month 00 is invalid."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_txn(db, "2026-00-10")

    def test_invalid_day_00_rejected(self, db: Path):
        """2026-11-00 — day 00 is invalid."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_txn(db, "2026-11-00")

    def test_reversed_format_rejected(self, db: Path):
        """23-11-2026 fails the LIKE '____-__-__' guard (day > 31 equiv)."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_txn(db, "23-11-2026")

    def test_april_31_rejected(self, db: Path):
        """2026-04-31 — April has only 30 days."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_txn(db, "2026-04-31")

    def test_non_leap_feb_29_rejected(self, db: Path):
        """2023-02-29 — 2023 is not a leap year."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_txn(db, "2023-02-29")

    # --- Valid dates ---
    def test_valid_date_accepted(self, db: Path):
        """2026-11-23 is a real date and must be accepted."""
        self._insert_txn(db, "2026-11-23")   # must not raise

    def test_leap_year_feb_29_accepted(self, db: Path):
        """2024-02-29 is valid — 2024 is a leap year (divisible by 4, not 100)."""
        self._insert_txn(db, "2024-02-29")   # must not raise

    def test_century_leap_year_accepted(self, db: Path):
        """2000-02-29 is valid — 2000 is a leap year (divisible by 400)."""
        self._insert_txn(db, "2000-02-29")   # must not raise

    def test_century_non_leap_feb_29_rejected(self, db: Path):
        """1900-02-29 is invalid — 1900 is divisible by 100 but NOT by 400."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_txn(db, "1900-02-29")

    def test_dec_31_accepted(self, db: Path):
        """2026-12-31 is a valid date."""
        self._insert_txn(db, "2026-12-31")   # must not raise

    def test_date_update_invalid_rejected(self, db: Path):
        """BEFORE UPDATE OF date trigger must also reject invalid dates."""
        self._insert_txn(db, "2026-11-01")   # insert valid first
        with get_connection(db) as conn:
            txn_id = conn.execute(
                "SELECT id FROM transactions LIMIT 1;"
            ).fetchone()["id"]

        with pytest.raises(sqlite3.IntegrityError):
            with get_connection(db) as conn:
                conn.execute(
                    "UPDATE transactions SET date = '2026-02-30' WHERE id = ?;",
                    (txn_id,),
                )


class TestStrictBudgetMonthValidation:
    """Tests for the trg_budget_month_insert / _update triggers."""

    def _expense_cat_id(self, db: Path) -> int:
        with get_connection(db) as conn:
            return conn.execute(
                "SELECT id FROM categories WHERE type='Expense' LIMIT 1;"
            ).fetchone()["id"]

    def _insert_budget(self, db: Path, month: str) -> None:
        cat_id = self._expense_cat_id(db)
        with get_connection(db) as conn:
            conn.execute(
                "INSERT INTO budgets (category_id, month, limit_amount) VALUES (?, ?, 5000.0);",
                (cat_id, month),
            )

    # --- Invalid months ---
    def test_month_00_rejected(self, db: Path):
        """2026-00 is not a valid month."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_budget(db, "2026-00")

    def test_month_13_rejected(self, db: Path):
        """2026-13 is not a valid month."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_budget(db, "2026-13")

    def test_month_15_rejected(self, db: Path):
        """2026-15 is out of range."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_budget(db, "2026-15")

    def test_wrong_format_rejected(self, db: Path):
        """11-2026 fails the LIKE guard."""
        with pytest.raises(sqlite3.IntegrityError):
            self._insert_budget(db, "11-2026")

    # --- Valid months ---
    def test_month_01_accepted(self, db: Path):
        """2026-01 (January) is valid."""
        self._insert_budget(db, "2026-01")   # must not raise

    def test_month_12_accepted(self, db: Path):
        """2026-12 (December) is valid."""
        # Use a different category so we don't hit the UNIQUE(cat, month) constraint
        with get_connection(db) as conn:
            conn.execute(
                "INSERT INTO categories (name, type) VALUES ('UniqueForDec', 'Expense');"
            )
            cat_id = conn.execute(
                "SELECT id FROM categories WHERE name='UniqueForDec';"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO budgets (category_id, month, limit_amount) VALUES (?, '2026-12', 3000.0);",
                (cat_id,),
            )


class TestPythonValidationHelpers:
    """Tests for validate_transaction_date() and validate_budget_month()."""

    # --- validate_transaction_date ---
    def test_valid_date_returns_date_object(self):
        result = validate_transaction_date("2026-11-23")
        assert result == _date_type(2026, 11, 23)

    def test_leap_year_date_valid(self):
        result = validate_transaction_date("2024-02-29")
        assert result == _date_type(2024, 2, 29)

    def test_feb_30_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_transaction_date("2026-02-30")

    def test_reversed_format_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_transaction_date("23-11-2026")

    def test_non_string_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_transaction_date(20261123)  # type: ignore[arg-type]

    def test_invalid_month_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_transaction_date("2026-13-01")

    def test_non_leap_feb_29_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_transaction_date("2023-02-29")

    # --- validate_budget_month ---
    def test_valid_month_01_passes(self):
        validate_budget_month("2026-01")   # must not raise

    def test_valid_month_12_passes(self):
        validate_budget_month("2026-12")   # must not raise

    def test_month_00_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_budget_month("2026-00")

    def test_month_13_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_budget_month("2026-13")

    def test_wrong_format_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_budget_month("11-2026")

    def test_non_string_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_budget_month(202611)  # type: ignore[arg-type]


class TestHardeningTriggersExist:
    """Confirm all 9 triggers are present in the schema after create_tables()."""

    _EXPECTED_TRIGGERS = {
        "trg_transaction_type_match",
        "trg_budget_expense_only_insert",
        "trg_budget_expense_only_update",
        "trg_transaction_type_match_update",
        "trg_category_type_lock",
        "trg_transaction_date_insert",
        "trg_transaction_date_update",
        "trg_budget_month_insert",
        "trg_budget_month_update",
    }

    def test_all_triggers_present(self, db: Path):
        triggers = set(get_trigger_names(db))
        assert self._EXPECTED_TRIGGERS.issubset(triggers), (
            f"Missing triggers: {self._EXPECTED_TRIGGERS - triggers}"
        )

    def test_migrate_function_is_idempotent(self, db: Path):
        """Running migrate_add_hardening_triggers() twice must not raise."""
        migrate_add_hardening_triggers(db)   # second call
        triggers = set(get_trigger_names(db))
        assert self._EXPECTED_TRIGGERS.issubset(triggers)
