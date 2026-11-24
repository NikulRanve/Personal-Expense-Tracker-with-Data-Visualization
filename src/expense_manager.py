"""
src/expense_manager.py — Transaction Management & CRUD Operations
==================================================================
Central transaction manager providing full CRUD operations, multi-criteria
filtering, text search, and financial summaries for income and expense records.

Public API
----------
  - add_transaction(...)             — validate & insert a single transaction
  - get_transaction(...)             — fetch a transaction by ID (with category name)
  - get_all_transactions(...)         — fetch all transactions as a DataFrame
  - update_transaction(...)          — update existing transaction fields
  - delete_transaction(...)          — delete transaction by ID
  - get_filtered_transactions(...)   — query transactions with multiple criteria
  - get_transaction_summary(...)     — calculate total income, expenses, net savings
  - ExpenseManager                   — class wrapper for OOP usage
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

from database import (
    DEFAULT_DB_PATH,
    get_connection,
    validate_transaction_date,
)

logger = logging.getLogger(__name__)

# Standard column list for transaction DataFrames
TRANSACTION_COLUMNS: list[str] = [
    "id",
    "date",
    "category",
    "amount",
    "payment_method",
    "description",
    "type",
    "import_batch_id",
    "created_at",
]


# ---------------------------------------------------------------------------
# Validation & Resolution Helpers
# ---------------------------------------------------------------------------

def _validate_amount(amount: Any) -> float:
    """Validate that amount is a positive, finite number."""
    if amount is None:
        raise ValueError("Amount cannot be None.")
    try:
        val = float(amount)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Non-numeric amount: {amount!r}") from exc

    if math.isnan(val) or math.isinf(val):
        raise ValueError("Amount must be a finite number.")
    if val <= 0:
        raise ValueError(f"Amount must be greater than zero, got {val}.")
    return round(val, 2)


def _validate_type(txn_type: Any) -> str:
    """Validate and normalize transaction type ('Income' or 'Expense')."""
    if not txn_type or not isinstance(txn_type, str):
        raise ValueError("Transaction type must be a non-empty string.")
    norm = txn_type.strip().capitalize()
    if norm not in ("Income", "Expense"):
        raise ValueError(
            f"Invalid transaction type: {txn_type!r}. Expected 'Income' or 'Expense'."
        )
    return norm


def _resolve_category(
    category_name: str,
    expected_type: str,
    conn: Any,
) -> tuple[int, str]:
    """
    Resolve a category name against the categories table.

    Returns
    -------
    tuple of (category_id, canonical_name)

    Raises
    ------
    ValueError
        If category is unknown or if category type does not match transaction type.
    """
    if not category_name or not str(category_name).strip():
        raise ValueError("Category name cannot be empty.")

    clean_name = str(category_name).strip()
    row = conn.execute(
        "SELECT id, name, type FROM categories WHERE name = ? COLLATE NOCASE;",
        (clean_name,),
    ).fetchone()

    if not row:
        raise ValueError(
            f"Unknown category '{clean_name}'. Category must exist in the database."
        )

    cat_id = row["id"]
    canonical_name = row["name"]
    cat_type = row["type"]

    if cat_type.lower() != expected_type.lower():
        raise ValueError(
            f"Category type mismatch: category '{canonical_name}' is of type '{cat_type}', "
            f"but transaction type is '{expected_type}'."
        )

    return cat_id, canonical_name


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------

def add_transaction(
    date: str,
    category: str,
    amount: Union[float, int, str],
    payment_method: Optional[str] = None,
    description: Optional[str] = None,
    type: str = "Expense",
    db_path: Optional[Union[Path, str]] = None,
) -> int:
    """
    Add a new transaction to the database after validating all fields.

    Parameters
    ----------
    date : str
        Date string in YYYY-MM-DD format (strictly validated).
    category : str
        Existing category name.
    amount : float | int | str
        Positive monetary amount.
    payment_method : str, optional
        Optional payment mode (e.g. 'UPI', 'Credit Card', 'Cash').
    description : str, optional
        Optional description note.
    type : str, default 'Expense'
        'Expense' or 'Income'.
    db_path : Path | str, optional
        Database file path override.

    Returns
    -------
    int
        The auto-generated transaction ID.

    Raises
    ------
    ValueError
        On invalid date, non-positive amount, unknown category, or type mismatch.
    """
    parsed_date = validate_transaction_date(date)
    norm_date = parsed_date.strftime("%Y-%m-%d")
    norm_amount = _validate_amount(amount)
    norm_type = _validate_type(type)
    clean_pm = payment_method.strip() if payment_method and str(payment_method).strip() else None
    clean_desc = description.strip() if description and str(description).strip() else None

    with get_connection(db_path) as conn:
        cat_id, _ = _resolve_category(category, norm_type, conn)

        cursor = conn.execute(
            """
            INSERT INTO transactions
                (date, category_id, amount, payment_method, description, type)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (norm_date, cat_id, norm_amount, clean_pm, clean_desc, norm_type),
        )
        txn_id = cursor.lastrowid

    logger.info("Added transaction #%d (%s, %s, %.2f)", txn_id, norm_date, category, norm_amount)
    return txn_id


def get_transaction(
    transaction_id: int,
    db_path: Optional[Union[Path, str]] = None,
) -> Optional[dict[str, Any]]:
    """
    Retrieve a single transaction by ID, including its category name.

    Returns
    -------
    dict or None
        Transaction record as a dictionary, or None if not found.
    """
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT t.id, t.date, c.name AS category, t.amount, t.payment_method,
                   t.description, t.type, t.import_batch_id, t.created_at
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.id = ?;
            """,
            (transaction_id,),
        ).fetchone()
        return dict(row) if row else None


def get_all_transactions(
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Retrieve all transactions ordered newest first.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: id, date, category, amount, payment_method,
        description, type, import_batch_id, created_at.
    """
    with get_connection(db_path) as conn:
        query = """
            SELECT t.id, t.date, c.name AS category, t.amount, t.payment_method,
                   t.description, t.type, t.import_batch_id, t.created_at
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            ORDER BY t.date DESC, t.id DESC;
        """
        df = pd.read_sql_query(query, conn)
        if df.empty:
            return pd.DataFrame(columns=TRANSACTION_COLUMNS)
        return df


def update_transaction(
    transaction_id: int,
    date: Optional[str] = None,
    category: Optional[str] = None,
    amount: Optional[Union[float, int, str]] = None,
    payment_method: Optional[str] = None,
    description: Optional[str] = None,
    type: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> bool:
    """
    Update an existing transaction by ID.

    Parameters
    ----------
    transaction_id : int
        ID of transaction to update.
    date, category, amount, payment_method, description, type : optional
        Fields to update. Only non-None arguments are modified.
    db_path : Path | str, optional
        Database path override.

    Returns
    -------
    bool
        True if updated successfully; False if transaction_id was not found.

    Raises
    ------
    ValueError
        If any updated value is invalid, or if category/type mismatch occurs.
    """
    with get_connection(db_path) as conn:
        existing = conn.execute(
            """
            SELECT t.id, t.date, t.category_id, c.name AS category_name,
                   c.type AS category_type, t.amount, t.payment_method,
                   t.description, t.type
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.id = ?;
            """,
            (transaction_id,),
        ).fetchone()

        if not existing:
            return False

        # Determine effective values
        eff_date = date if date is not None else existing["date"]
        eff_amount = amount if amount is not None else existing["amount"]
        eff_type = type if type is not None else existing["type"]
        eff_cat = category if category is not None else existing["category_name"]
        eff_pm = payment_method if payment_method is not None else existing["payment_method"]
        eff_desc = description if description is not None else existing["description"]

        # Validate effective values
        parsed_date = validate_transaction_date(eff_date)
        norm_date = parsed_date.strftime("%Y-%m-%d")
        norm_amount = _validate_amount(eff_amount)
        norm_type = _validate_type(eff_type)
        clean_pm = eff_pm.strip() if eff_pm and str(eff_pm).strip() else None
        clean_desc = eff_desc.strip() if eff_desc and str(eff_desc).strip() else None

        # Resolve category and verify category/type match
        cat_id, _ = _resolve_category(eff_cat, norm_type, conn)

        conn.execute(
            """
            UPDATE transactions
            SET date = ?, category_id = ?, amount = ?, payment_method = ?,
                description = ?, type = ?
            WHERE id = ?;
            """,
            (norm_date, cat_id, norm_amount, clean_pm, clean_desc, norm_type, transaction_id),
        )

    logger.info("Updated transaction #%d", transaction_id)
    return True


def delete_transaction(
    transaction_id: int,
    db_path: Optional[Union[Path, str]] = None,
) -> bool:
    """
    Delete a transaction by ID.

    Returns
    -------
    bool
        True if a row was deleted; False if the ID did not exist.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM transactions WHERE id = ?;",
            (transaction_id,),
        )
        deleted = cursor.rowcount > 0

    if deleted:
        logger.info("Deleted transaction #%d", transaction_id)
    return deleted


# ---------------------------------------------------------------------------
# Filtering and Search
# ---------------------------------------------------------------------------

def get_filtered_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    month: Optional[Union[int, str]] = None,
    year: Optional[Union[int, str]] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    payment_method: Optional[str] = None,
    search_term: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Filter transactions with multiple criteria, using parameterized SQL.

    Returns
    -------
    pd.DataFrame
        Filtered transactions sorted newest first. Empty DataFrame if no match.
    """
    conditions: list[str] = []
    params: list[Any] = []

    # 1. Date Range
    if start_date:
        parsed_start = validate_transaction_date(start_date)
        start_str = parsed_start.strftime("%Y-%m-%d")
        conditions.append("t.date >= ?")
        params.append(start_str)

    if end_date:
        parsed_end = validate_transaction_date(end_date)
        end_str = parsed_end.strftime("%Y-%m-%d")
        conditions.append("t.date <= ?")
        params.append(end_str)

    if start_date and end_date:
        if start_date > end_date:
            raise ValueError(
                f"Invalid date range: start_date ({start_date}) cannot be after end_date ({end_date})."
            )

    # 2. Month and Year
    if year is not None and month is not None:
        prefix = f"{int(year):04d}-{int(month):02d}"
        conditions.append("t.date LIKE ?")
        params.append(f"{prefix}%")
    elif year is not None:
        conditions.append("t.date LIKE ?")
        params.append(f"{int(year):04d}-%")
    elif month is not None:
        month_val = str(month).strip()
        if "-" in month_val:  # 'YYYY-MM' format passed directly
            conditions.append("t.date LIKE ?")
            params.append(f"{month_val}%")
        else:
            conditions.append("substr(t.date, 6, 2) = ?")
            params.append(f"{int(month):02d}")

    # 3. Category Filter
    if category:
        conditions.append("c.name = ? COLLATE NOCASE")
        params.append(category.strip())

    # 4. Transaction Type Filter
    if transaction_type:
        norm_type = _validate_type(transaction_type)
        conditions.append("t.type = ? COLLATE NOCASE")
        params.append(norm_type)

    # 5. Payment Method Filter
    if payment_method:
        conditions.append("t.payment_method = ? COLLATE NOCASE")
        params.append(payment_method.strip())

    # 6. Description / Category Text Search
    if search_term and str(search_term).strip():
        term = f"%{str(search_term).strip()}%"
        conditions.append("(t.description LIKE ? OR c.name LIKE ?)")
        params.extend([term, term])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT t.id, t.date, c.name AS category, t.amount, t.payment_method,
               t.description, t.type, t.import_batch_id, t.created_at
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        {where_clause}
        ORDER BY t.date DESC, t.id DESC;
    """

    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=params)
        if df.empty:
            return pd.DataFrame(columns=TRANSACTION_COLUMNS)
        return df


def get_transaction_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> dict[str, Any]:
    """
    Compute financial summary: total_income, total_expenses, net_savings, count.

    Formula:
      net_savings = total_income - total_expenses

    Returns
    -------
    dict
        {
            "total_income": float,
            "total_expenses": float,
            "net_savings": float,
            "transaction_count": int,
        }
    """
    df = get_filtered_transactions(
        start_date=start_date,
        end_date=end_date,
        category=category,
        transaction_type=transaction_type,
        db_path=db_path,
    )

    if df.empty:
        return {
            "total_income": 0.0,
            "total_expenses": 0.0,
            "net_savings": 0.0,
            "transaction_count": 0,
        }

    income_df = df[df["type"] == "Income"]
    expense_df = df[df["type"] == "Expense"]

    total_income = round(float(income_df["amount"].sum()), 2)
    total_expenses = round(float(expense_df["amount"].sum()), 2)
    net_savings = round(total_income - total_expenses, 2)
    count = len(df)

    return {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_savings": net_savings,
        "transaction_count": count,
    }


# ---------------------------------------------------------------------------
# ExpenseManager Class Wrapper
# ---------------------------------------------------------------------------

class ExpenseManager:
    """
    High-level object-oriented interface for transaction management.
    """

    def __init__(self, db_manager: Any = None):
        if hasattr(db_manager, "db_path"):
            self.db_path = db_manager.db_path
        elif isinstance(db_manager, (str, Path)):
            self.db_path = db_manager
        else:
            self.db_path = None

    def add_transaction(self, **kwargs) -> int:
        return add_transaction(**kwargs, db_path=self.db_path)

    def add_expense(
        self,
        amount: Union[float, int, str],
        category: str,
        date: str,
        description: str = "",
        payment_method: str = "Cash",
    ) -> int:
        return add_transaction(
            date=date,
            category=category,
            amount=amount,
            payment_method=payment_method,
            description=description,
            type="Expense",
            db_path=self.db_path,
        )

    def add_income(
        self,
        amount: Union[float, int, str],
        source: str,
        date: str,
        note: str = "",
        payment_method: str = "Bank Transfer",
    ) -> int:
        return add_transaction(
            date=date,
            category=source,
            amount=amount,
            payment_method=payment_method,
            description=note,
            type="Income",
            db_path=self.db_path,
        )

    def get_transaction(self, transaction_id: int) -> Optional[dict[str, Any]]:
        return get_transaction(transaction_id, db_path=self.db_path)

    def get_all(self) -> pd.DataFrame:
        return get_all_transactions(db_path=self.db_path)

    def update(self, transaction_id: int, **kwargs) -> bool:
        return update_transaction(transaction_id, **kwargs, db_path=self.db_path)

    def delete(self, transaction_id: int) -> bool:
        return delete_transaction(transaction_id, db_path=self.db_path)

    def filter(self, **kwargs) -> pd.DataFrame:
        return get_filtered_transactions(**kwargs, db_path=self.db_path)

    def get_summary(self, **kwargs) -> dict[str, Any]:
        return get_transaction_summary(**kwargs, db_path=self.db_path)
