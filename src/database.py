"""
src/database.py — SQLite Database Layer
=========================================
Manages the SQLite database for the Personal Expense Tracker.

Uses Python's built-in sqlite3 module exclusively — no external ORM.

Tables
------
  categories     : Lookup table for Income / Expense categories.
  transactions   : Every financial transaction (income or expense).
  budgets        : Monthly spending limits per Expense category.
  import_batches : Audit log for CSV import operations.

Public API
----------
  get_connection(db_path)              — context-managed sqlite3.Connection
  create_tables(db_path)               — idempotent schema creation (tables + all triggers)
  seed_categories(db_path)             — idempotent default-category insertion
  initialise_database(db_path)         — one-shot start-up helper
  migrate_add_hardening_triggers(path) — safely adds Session-2b triggers to an existing DB
  migrate_add_duplicate_rows_column(path) — safely adds Session-4 column and triggers
  validate_transaction_date(date_str)  — Python-layer date validator (raises ValueError)
  validate_budget_month(month_str)     — Python-layer month validator (raises ValueError)

Triggers (11 total)
-------------------
  Session 2 (original):
    trg_transaction_type_match          BEFORE INSERT  transactions — type must match category
    trg_budget_expense_only_insert      BEFORE INSERT  budgets      — Expense categories only
    trg_budget_expense_only_update      BEFORE UPDATE  budgets      — Expense categories only

  Session 2b (hardening):
    trg_transaction_type_match_update   BEFORE UPDATE  transactions — type must match category
    trg_category_type_lock              BEFORE UPDATE OF type categories — block if dependents exist
    trg_transaction_date_insert         BEFORE INSERT  transactions — strict calendar date
    trg_transaction_date_update         BEFORE UPDATE OF date transactions — strict calendar date
    trg_budget_month_insert             BEFORE INSERT  budgets — month 01-12
    trg_budget_month_update             BEFORE UPDATE OF month budgets — month 01-12

  Session 4 (import batches accounting):
    trg_import_batches_accounting_insert BEFORE INSERT  import_batches — strict accounting: total == successful + rejected + duplicate
    trg_import_batches_accounting_update BEFORE UPDATE  import_batches — strict accounting: total == successful + rejected + duplicate

Design Decisions
----------------
  * pathlib.Path for all file paths (cross-platform, no hardcoded separators).
  * Foreign-key support enabled on every connection via PRAGMA.
  * All triggers use CREATE TRIGGER IF NOT EXISTS — safe to re-run.
  * Parameterised SQL throughout — no string formatting of user data.
  * The database is never created by a bare import; call create_tables()
    explicitly or use the CLI helper at the bottom of this file.
  * Strict date validation uses a CASE expression that correctly handles
    30/31-day months and leap years (year % 400 = 0 OR year % 4 = 0 AND year % 100 != 0).
"""

from __future__ import annotations

import logging
import re as _re
import sqlite3
from contextlib import contextmanager
from datetime import date as _date_type
from pathlib import Path
from typing import Generator, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Root of the project: two levels up from this file  (src/ → project root)
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
_DATA_DIR: Path = _PROJECT_ROOT / "data"
DEFAULT_DB_PATH: Path = _DATA_DIR / "expense_tracker.db"

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL: Table DDL
# ---------------------------------------------------------------------------

_DDL_CATEGORIES = """
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER  PRIMARY KEY AUTOINCREMENT,
    name       TEXT     NOT NULL
                        CHECK(length(trim(replace(replace(replace(name, char(9), ' '), char(10), ' '), char(13), ' '))) > 0),
    type       TEXT     NOT NULL
                        CHECK(type IN ('Income', 'Expense')),
    created_at TEXT     NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    UNIQUE(name, type)
);
"""

_DDL_IMPORT_BATCHES = """
CREATE TABLE IF NOT EXISTS import_batches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    filename        TEXT    NOT NULL,
    imported_at     TEXT    NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    total_rows      INTEGER NOT NULL DEFAULT 0
                            CHECK(total_rows >= 0),
    successful_rows INTEGER NOT NULL DEFAULT 0
                            CHECK(successful_rows >= 0),
    rejected_rows   INTEGER NOT NULL DEFAULT 0
                            CHECK(rejected_rows >= 0),
    duplicate_rows  INTEGER NOT NULL DEFAULT 0
                            CHECK(duplicate_rows >= 0),
    CHECK(successful_rows <= total_rows),
    CHECK(rejected_rows   <= total_rows),
    CHECK(duplicate_rows  <= total_rows),
    CHECK(successful_rows + rejected_rows + duplicate_rows <= total_rows)
);
"""

_DDL_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT    NOT NULL
                            CHECK(date LIKE '____-__-__'),
    category_id     INTEGER NOT NULL
                            REFERENCES categories(id) ON DELETE RESTRICT,
    amount          REAL    NOT NULL
                            CHECK(amount > 0),
    payment_method  TEXT,
    description     TEXT,
    type            TEXT    NOT NULL
                            CHECK(type IN ('Income', 'Expense')),
    import_batch_id INTEGER
                            REFERENCES import_batches(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
"""

_DDL_BUDGETS = """
CREATE TABLE IF NOT EXISTS budgets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id   INTEGER NOT NULL
                          REFERENCES categories(id) ON DELETE RESTRICT,
    month         TEXT    NOT NULL
                          CHECK(month LIKE '____-__'),
    limit_amount  REAL    NOT NULL
                          CHECK(limit_amount > 0),
    created_at    TEXT    NOT NULL
                          DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    UNIQUE(category_id, month)
);
"""

# ---------------------------------------------------------------------------
# SQL: Triggers — Session 2 (original)
# ---------------------------------------------------------------------------

# Enforce that a transaction's type matches its category's type on INSERT.
_TRIGGER_TXN_TYPE_MATCH = """
CREATE TRIGGER IF NOT EXISTS trg_transaction_type_match
BEFORE INSERT ON transactions
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Transaction type must match its category type')
    WHERE (
        SELECT type FROM categories WHERE id = NEW.category_id
    ) != NEW.type;
END;
"""

# Prevent budgets from being assigned to Income categories (INSERT).
_TRIGGER_BUDGET_EXPENSE_ONLY_INSERT = """
CREATE TRIGGER IF NOT EXISTS trg_budget_expense_only_insert
BEFORE INSERT ON budgets
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Budgets can only be set for Expense categories')
    WHERE (
        SELECT type FROM categories WHERE id = NEW.category_id
    ) != 'Expense';
END;
"""

# Prevent budgets from being assigned to Income categories (UPDATE).
_TRIGGER_BUDGET_EXPENSE_ONLY_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_budget_expense_only_update
BEFORE UPDATE ON budgets
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Budgets can only be set for Expense categories')
    WHERE (
        SELECT type FROM categories WHERE id = NEW.category_id
    ) != 'Expense';
END;
"""

# ---------------------------------------------------------------------------
# SQL: Triggers — Session 2b (hardening)
# ---------------------------------------------------------------------------

# 1. Enforce transaction type/category match on UPDATE.
#    Also explicitly checks that the category exists (FK alone would catch it
#    after the trigger, but raising here gives a clearer error message).
_TRIGGER_TXN_TYPE_MATCH_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_transaction_type_match_update
BEFORE UPDATE ON transactions
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Invalid category_id: no matching category found')
    WHERE NOT EXISTS (SELECT 1 FROM categories WHERE id = NEW.category_id);

    SELECT RAISE(ABORT, 'Transaction type must match its category type')
    WHERE (
        SELECT type FROM categories WHERE id = NEW.category_id
    ) != NEW.type;
END;
"""

# 2. Prevent changing a category's type when transactions or budgets depend on it.
#    Uses "BEFORE UPDATE OF type" so it only fires when the type column changes.
_TRIGGER_CATEGORY_TYPE_LOCK = """
CREATE TRIGGER IF NOT EXISTS trg_category_type_lock
BEFORE UPDATE OF type ON categories
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Cannot change category type: existing transactions reference this category')
    WHERE EXISTS (SELECT 1 FROM transactions WHERE category_id = OLD.id LIMIT 1);

    SELECT RAISE(ABORT, 'Cannot change category type: existing budgets reference this category')
    WHERE EXISTS (SELECT 1 FROM budgets WHERE category_id = OLD.id LIMIT 1);
END;
"""

# 3a. Strict calendar-date validation on transaction INSERT.
#     The LIKE check in the table schema catches format; this trigger validates
#     that the month is 01-12 and the day is valid for that month/year,
#     including correct leap-year logic.
_TRIGGER_TXN_DATE_INSERT = """
CREATE TRIGGER IF NOT EXISTS trg_transaction_date_insert
BEFORE INSERT ON transactions
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Invalid date format: must be YYYY-MM-DD')
    WHERE NEW.date NOT LIKE '____-__-__';

    SELECT RAISE(ABORT, 'Invalid date: month must be between 01 and 12')
    WHERE CAST(substr(NEW.date, 6, 2) AS INTEGER) NOT BETWEEN 1 AND 12;

    SELECT RAISE(ABORT, 'Invalid date: day is out of range for the given month and year')
    WHERE CAST(substr(NEW.date, 9, 2) AS INTEGER) < 1
       OR CAST(substr(NEW.date, 9, 2) AS INTEGER) >
          CASE
            WHEN CAST(substr(NEW.date, 6, 2) AS INTEGER) IN (1,3,5,7,8,10,12) THEN 31
            WHEN CAST(substr(NEW.date, 6, 2) AS INTEGER) IN (4,6,9,11)         THEN 30
            WHEN CAST(substr(NEW.date, 6, 2) AS INTEGER) = 2 THEN
              CASE
                WHEN (CAST(substr(NEW.date, 1, 4) AS INTEGER) % 400 = 0)
                  OR (CAST(substr(NEW.date, 1, 4) AS INTEGER) % 4   = 0
                      AND CAST(substr(NEW.date, 1, 4) AS INTEGER) % 100 != 0)
                THEN 29
                ELSE 28
              END
          END;
END;
"""

# 3b. Strict calendar-date validation on transaction UPDATE (date column only).
_TRIGGER_TXN_DATE_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_transaction_date_update
BEFORE UPDATE OF date ON transactions
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Invalid date format: must be YYYY-MM-DD')
    WHERE NEW.date NOT LIKE '____-__-__';

    SELECT RAISE(ABORT, 'Invalid date: month must be between 01 and 12')
    WHERE CAST(substr(NEW.date, 6, 2) AS INTEGER) NOT BETWEEN 1 AND 12;

    SELECT RAISE(ABORT, 'Invalid date: day is out of range for the given month and year')
    WHERE CAST(substr(NEW.date, 9, 2) AS INTEGER) < 1
       OR CAST(substr(NEW.date, 9, 2) AS INTEGER) >
          CASE
            WHEN CAST(substr(NEW.date, 6, 2) AS INTEGER) IN (1,3,5,7,8,10,12) THEN 31
            WHEN CAST(substr(NEW.date, 6, 2) AS INTEGER) IN (4,6,9,11)         THEN 30
            WHEN CAST(substr(NEW.date, 6, 2) AS INTEGER) = 2 THEN
              CASE
                WHEN (CAST(substr(NEW.date, 1, 4) AS INTEGER) % 400 = 0)
                  OR (CAST(substr(NEW.date, 1, 4) AS INTEGER) % 4   = 0
                      AND CAST(substr(NEW.date, 1, 4) AS INTEGER) % 100 != 0)
                THEN 29
                ELSE 28
              END
          END;
END;
"""

# 4a. Strict budget month validation on INSERT — month number must be 01-12.
_TRIGGER_BUDGET_MONTH_INSERT = """
CREATE TRIGGER IF NOT EXISTS trg_budget_month_insert
BEFORE INSERT ON budgets
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Invalid month format: must be YYYY-MM')
    WHERE NEW.month NOT LIKE '____-__';

    SELECT RAISE(ABORT, 'Invalid month: month number must be between 01 and 12')
    WHERE CAST(substr(NEW.month, 6, 2) AS INTEGER) NOT BETWEEN 1 AND 12;
END;
"""

# 4b. Strict budget month validation on UPDATE (month column only).
_TRIGGER_BUDGET_MONTH_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_budget_month_update
BEFORE UPDATE OF month ON budgets
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Invalid month format: must be YYYY-MM')
    WHERE NEW.month NOT LIKE '____-__';

    SELECT RAISE(ABORT, 'Invalid month: month number must be between 01 and 12')
    WHERE CAST(substr(NEW.month, 6, 2) AS INTEGER) NOT BETWEEN 1 AND 12;
END;
"""

# ---------------------------------------------------------------------------
# SQL: Triggers — Session 4 (import batches accounting)
# ---------------------------------------------------------------------------

_TRIGGER_IMPORT_BATCHES_ACCOUNTING_INSERT = """
CREATE TRIGGER IF NOT EXISTS trg_import_batches_accounting_insert
BEFORE INSERT ON import_batches
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'duplicate_rows must be non-negative')
    WHERE NEW.duplicate_rows < 0;

    SELECT RAISE(ABORT, 'Batch row accounting violation: successful + rejected + duplicate exceeds total_rows')
    WHERE (NEW.successful_rows + NEW.rejected_rows + NEW.duplicate_rows) > NEW.total_rows;

    SELECT RAISE(ABORT, 'Batch row accounting violation: total_rows must equal successful_rows + rejected_rows + duplicate_rows')
    WHERE (NEW.successful_rows + NEW.rejected_rows + NEW.duplicate_rows) != NEW.total_rows;
END;
"""

_TRIGGER_IMPORT_BATCHES_ACCOUNTING_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_import_batches_accounting_update
BEFORE UPDATE ON import_batches
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'duplicate_rows must be non-negative')
    WHERE NEW.duplicate_rows < 0;

    SELECT RAISE(ABORT, 'Batch row accounting violation: successful + rejected + duplicate exceeds total_rows')
    WHERE (NEW.successful_rows + NEW.rejected_rows + NEW.duplicate_rows) > NEW.total_rows;

    SELECT RAISE(ABORT, 'Batch row accounting violation: total_rows must equal successful_rows + rejected_rows + duplicate_rows')
    WHERE (NEW.successful_rows + NEW.rejected_rows + NEW.duplicate_rows) != NEW.total_rows;
END;
"""

# ---------------------------------------------------------------------------
# SQL: Indexes
# ---------------------------------------------------------------------------

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_transactions_date        ON transactions(date);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_category_id ON transactions(category_id);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_type        ON transactions(type);",
    "CREATE INDEX IF NOT EXISTS idx_budgets_category_month   ON budgets(category_id, month);",
]

# ---------------------------------------------------------------------------
# Default seed data
# ---------------------------------------------------------------------------

_DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("Food",           "Expense"),
    ("Transportation", "Expense"),
    ("Housing",        "Expense"),
    ("Utilities",      "Expense"),
    ("Healthcare",     "Expense"),
    ("Shopping",       "Expense"),
    ("Salary",         "Income"),
    ("Other Income",   "Income"),
]

# ---------------------------------------------------------------------------
# Python-layer validation helpers
# ---------------------------------------------------------------------------

def validate_transaction_date(date_str: str) -> _date_type:
    """
    Validate a transaction date string as a real YYYY-MM-DD calendar date.

    Uses ``datetime.date.fromisoformat`` for authoritative parsing so that
    dates like ``2026-02-30`` are definitively rejected.

    Parameters
    ----------
    date_str : str
        Date string to validate.

    Returns
    -------
    datetime.date
        The parsed date object when valid.

    Raises
    ------
    ValueError
        If the string is not a valid YYYY-MM-DD calendar date.

    Examples
    --------
    >>> validate_transaction_date("2026-11-23")   # ✅ returns date(2026, 11, 23)
    >>> validate_transaction_date("2026-02-30")   # ❌ raises ValueError
    >>> validate_transaction_date("23-11-2026")   # ❌ raises ValueError
    """
    if not isinstance(date_str, str):
        raise ValueError(f"Date must be a string, got {type(date_str).__name__!r}")
    if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        raise ValueError(
            f"Invalid date format {date_str!r}: expected YYYY-MM-DD "
            f"with zero-padded month and day"
        )
    try:
        parsed = _date_type.fromisoformat(date_str)
    except ValueError as exc:
        raise ValueError(f"Invalid calendar date {date_str!r}: {exc}") from exc
    # Guard against any edge cases where fromisoformat might accept non-canonical forms
    if parsed.strftime("%Y-%m-%d") != date_str:
        raise ValueError(
            f"Date {date_str!r} did not round-trip — ensure leading zeros on month and day"
        )
    return parsed


def validate_budget_month(month_str: str) -> None:
    """
    Validate a budget month string as YYYY-MM with month number 01–12.

    Parameters
    ----------
    month_str : str
        Month string to validate.

    Raises
    ------
    ValueError
        If the string is not a valid YYYY-MM month (month must be 01–12).

    Examples
    --------
    >>> validate_budget_month("2026-11")   # ✅ passes
    >>> validate_budget_month("2026-00")   # ❌ raises ValueError
    >>> validate_budget_month("2026-13")   # ❌ raises ValueError
    >>> validate_budget_month("11-2026")   # ❌ raises ValueError
    """
    if not isinstance(month_str, str):
        raise ValueError(f"Month must be a string, got {type(month_str).__name__!r}")
    if not _re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month_str):
        raise ValueError(
            f"Invalid month {month_str!r}: expected YYYY-MM format "
            f"with month number between 01 and 12"
        )


# ---------------------------------------------------------------------------
# Core connection helper
# ---------------------------------------------------------------------------

@contextmanager
def get_connection(
    db_path: Optional[Path | str] = None,
) -> Generator[sqlite3.Connection, None, None]:
    """
    Context-managed SQLite connection with foreign-key support.

    Usage
    -----
    ::

        with get_connection() as conn:
            conn.execute("SELECT 1")

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Defaults to
        ``data/expense_tracker.db`` inside the project root.

    Behaviour
    ---------
    * Enables ``PRAGMA foreign_keys = ON`` immediately after opening.
    * Sets ``row_factory = sqlite3.Row`` so rows are accessible by name.
    * Commits on clean exit; rolls back and re-raises on any exception.
    * Always closes the connection in the ``finally`` block.

    Yields
    ------
    sqlite3.Connection
    """
    resolved: Path = _resolve_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    conn: sqlite3.Connection = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row

    try:
        # Enable foreign-key enforcement (off by default in SQLite)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")   # safer concurrent writes
        logger.debug("Opened connection → %s", resolved)
        yield conn
        conn.commit()
        logger.debug("Committed transaction → %s", resolved)
    except Exception:
        conn.rollback()
        logger.exception("Transaction rolled back → %s", resolved)
        raise
    finally:
        conn.close()
        logger.debug("Closed connection → %s", resolved)


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

# All trigger DDL strings grouped for use by create_tables() and migration.
_ALL_TRIGGERS = (
    # --- Session 2 original ---
    _TRIGGER_TXN_TYPE_MATCH
    + _TRIGGER_BUDGET_EXPENSE_ONLY_INSERT
    + _TRIGGER_BUDGET_EXPENSE_ONLY_UPDATE
    # --- Session 2b hardening ---
    + _TRIGGER_TXN_TYPE_MATCH_UPDATE
    + _TRIGGER_CATEGORY_TYPE_LOCK
    + _TRIGGER_TXN_DATE_INSERT
    + _TRIGGER_TXN_DATE_UPDATE
    + _TRIGGER_BUDGET_MONTH_INSERT
    + _TRIGGER_BUDGET_MONTH_UPDATE
    # --- Session 4 import batches accounting ---
    + _TRIGGER_IMPORT_BATCHES_ACCOUNTING_INSERT
    + _TRIGGER_IMPORT_BATCHES_ACCOUNTING_UPDATE
)


def create_tables(db_path: Optional[Path | str] = None) -> None:
    """
    Create all four tables, indexes, and all triggers if they do not exist.

    Safe to call multiple times — uses ``CREATE TABLE IF NOT EXISTS``
    and ``CREATE INDEX/TRIGGER IF NOT EXISTS`` throughout, so existing
    data is never touched and no tables are dropped or recreated.

    Parameters
    ----------
    db_path:
        Optional path to the database file.  Defaults to
        ``data/expense_tracker.db``.
    """
    with get_connection(db_path) as conn:
        # Tables — order matters: referenced tables before referencing tables
        conn.executescript(
            _DDL_CATEGORIES
            + _DDL_IMPORT_BATCHES
            + _DDL_TRANSACTIONS
            + _DDL_BUDGETS
        )

        # All triggers (original + hardening + accounting)
        conn.executescript(_ALL_TRIGGERS)

        # Indexes
        for sql in _INDEXES:
            conn.execute(sql)

    # Ensure duplicate_rows column exists on databases created prior to Session 4
    migrate_add_duplicate_rows_column(db_path)

    logger.info("Database schema created / verified → %s", _resolve_path(db_path))


def migrate_add_duplicate_rows_column(db_path: Optional[Path | str] = None) -> None:
    """
    Safely and idempotently add 'duplicate_rows' column to import_batches
    if it does not already exist, and install accounting triggers.
    Preserves all existing database records without dropping or recreating tables.
    """
    with get_connection(db_path) as conn:
        cols = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(import_batches);").fetchall()
        ]
        if "duplicate_rows" not in cols:
            conn.execute(
                "ALTER TABLE import_batches ADD COLUMN duplicate_rows INTEGER NOT NULL DEFAULT 0;"
            )
            logger.info("Added duplicate_rows column to import_batches in %s", _resolve_path(db_path))

        conn.executescript(
            _TRIGGER_IMPORT_BATCHES_ACCOUNTING_INSERT
            + _TRIGGER_IMPORT_BATCHES_ACCOUNTING_UPDATE
        )
    logger.info("Import batches accounting triggers verified in %s", _resolve_path(db_path))


def migrate_add_hardening_triggers(db_path: Optional[Path | str] = None) -> None:
    """
    Safely add the Session-2b hardening triggers to an already-existing database.

    This function is safe to run multiple times and against databases that
    already have the triggers — all CREATE statements use IF NOT EXISTS.
    It never drops or modifies any tables, never deletes any rows.

    Parameters
    ----------
    db_path:
        Optional path to the database file.
    """
    hardening_triggers = (
        _TRIGGER_TXN_TYPE_MATCH_UPDATE
        + _TRIGGER_CATEGORY_TYPE_LOCK
        + _TRIGGER_TXN_DATE_INSERT
        + _TRIGGER_TXN_DATE_UPDATE
        + _TRIGGER_BUDGET_MONTH_INSERT
        + _TRIGGER_BUDGET_MONTH_UPDATE
    )
    with get_connection(db_path) as conn:
        conn.executescript(hardening_triggers)

    logger.info(
        "Hardening triggers applied (idempotent) → %s", _resolve_path(db_path)
    )


def migrate_update_transaction_type_match_trigger(db_path: Optional[Path | str] = None) -> None:
    """
    Safely and idempotently update the trg_transaction_type_match_update trigger.

    If the trigger exists with broken or outdated SQL, drops only that trigger
    and recreates it using the corrected definition from _TRIGGER_TXN_TYPE_MATCH_UPDATE.
    Preserves all existing tables and data (categories, transactions, budgets, import_batches).

    Parameters
    ----------
    db_path:
        Optional path to the database file.
    """
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'trg_transaction_type_match_update';"
        ).fetchone()

        needs_update = False
        if not row or not row["sql"]:
            needs_update = True
        elif "NEW.type" not in row["sql"] or "\n EW.type" in row["sql"]:
            needs_update = True

        if needs_update:
            conn.execute("DROP TRIGGER IF EXISTS trg_transaction_type_match_update;")
            conn.execute(_TRIGGER_TXN_TYPE_MATCH_UPDATE)
            logger.info("Updated trigger trg_transaction_type_match_update in %s", _resolve_path(db_path))
        else:
            logger.info("Trigger trg_transaction_type_match_update already up-to-date in %s", _resolve_path(db_path))


# ---------------------------------------------------------------------------
# Default category seeding
# ---------------------------------------------------------------------------

def seed_categories(db_path: Optional[Path | str] = None) -> int:
    """
    Insert the eight default categories if they do not already exist.

    Idempotent — uses ``INSERT OR IGNORE`` so running multiple times
    never creates duplicates and never overwrites user-created categories.

    Parameters
    ----------
    db_path:
        Optional path to the database file.

    Returns
    -------
    int
        Number of rows actually inserted (0 if already seeded).
    """
    inserted = 0
    with get_connection(db_path) as conn:
        for name, cat_type in _DEFAULT_CATEGORIES:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?);",
                (name, cat_type),
            )
            inserted += cursor.rowcount

    logger.info(
        "Category seeding complete — %d row(s) inserted → %s",
        inserted,
        _resolve_path(db_path),
    )
    return inserted


# ---------------------------------------------------------------------------
# Convenience initialiser
# ---------------------------------------------------------------------------

def initialise_database(db_path: Optional[Path | str] = None) -> None:
    """
    One-shot helper: create tables (+ all triggers) then seed default categories.

    Call this once at application start-up (e.g. from ``main.py``).
    Safe to call repeatedly.

    Parameters
    ----------
    db_path:
        Optional path override.
    """
    create_tables(db_path)
    seed_categories(db_path)
    logger.info("Database initialised → %s", _resolve_path(db_path))


# ---------------------------------------------------------------------------
# Schema introspection helpers (used by tests and reporting)
# ---------------------------------------------------------------------------

def get_table_names(db_path: Optional[Path | str] = None) -> list[str]:
    """Return a sorted list of user-created table names in the database."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ).fetchall()
    return [row["name"] for row in rows]


def get_schema(db_path: Optional[Path | str] = None) -> str:
    """
    Return the CREATE statements for all tables, triggers, and indexes as a string.
    Useful for debugging and documentation.
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type IN ('table','trigger','index')
              AND sql IS NOT NULL
            ORDER BY type, name;
            """
        ).fetchall()
    return "\n\n".join(row["sql"] for row in rows)


def get_trigger_names(db_path: Optional[Path | str] = None) -> list[str]:
    """Return a sorted list of trigger names in the database."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name;"
        ).fetchall()
    return [row["name"] for row in rows]


def foreign_keys_enabled(db_path: Optional[Path | str] = None) -> bool:
    """Return True if foreign-key enforcement is active on a new connection."""
    with get_connection(db_path) as conn:
        row = conn.execute("PRAGMA foreign_keys;").fetchone()
    return bool(row[0])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _resolve_path(db_path: Optional[Path | str]) -> Path:
    """Resolve an optional db_path argument to an absolute Path."""
    if db_path is None:
        return DEFAULT_DB_PATH
    return Path(db_path).resolve()


# ---------------------------------------------------------------------------
# CLI helper — python src/database.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    initialise_database(path)
    migrate_add_hardening_triggers(path)
    migrate_add_duplicate_rows_column(path)
    print("Tables  :", get_table_names(path))
    print("Triggers:", get_trigger_names(path))
    print("\nSchema:\n", get_schema(path))
