"""
src/budget_manager.py — Budget Management Module
==================================================
Manages per-category monthly budget limits, budget tracking,
utilization calculation, and breach alert detection.

Features:
  - set_budget: Upsert budget limit for an Expense category and month (YYYY-MM).
  - get_budget: Retrieve budget details for a category and month.
  - get_all_budgets: List all set budgets for a given month as a DataFrame.
  - get_budget_status: Compare budgets against actual expenses and compute status.
  - get_budget_alerts: Filter budgets in Warning (80% <= util < 100%) or Exceeded (>= 100%).
  - delete_budget: Delete a budget record by its primary key.
  - BudgetManager: Object-oriented interface wrapper.

Threshold Rules:
  - Normal:   utilization < 80.0%
  - Warning:  80.0% <= utilization < 100.0%
  - Exceeded: utilization >= 100.0%
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

from src.database import get_connection, validate_budget_month

logger = logging.getLogger(__name__)

# Status constants
STATUS_NORMAL = "Normal"
STATUS_WARNING = "Warning"
STATUS_EXCEEDED = "Exceeded"

THRESHOLD_WARNING = 80.0
THRESHOLD_EXCEEDED = 100.0

# Expected DataFrame schemas
BUDGET_COLUMNS = ["budget_id", "category", "month", "budget_limit"]
BUDGET_STATUS_COLUMNS = [
    "category",
    "month",
    "budget_limit",
    "actual_expenses",
    "remaining_budget",
    "utilization_percentage",
    "status",
]


def _validate_budget_amount(amount: Any) -> float:
    """
    Validate that amount is a positive finite number greater than zero.

    Raises
    ------
    ValueError
        If amount is not numeric, <= 0, NaN, or infinite.
    """
    if amount is None or isinstance(amount, bool):
        raise ValueError(f"Invalid budget amount {amount!r}: must be a positive number")
    try:
        val = float(amount)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid budget amount {amount!r}: must be numeric") from exc

    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"Invalid budget amount {amount!r}: must be finite")
    if val <= 0:
        raise ValueError(f"Budget amount must be strictly greater than zero, got {val}")

    return round(val, 2)


def set_budget(
    category: str,
    month: str,
    amount: Union[float, int, str],
    db_path: Optional[Union[Path, str]] = None,
) -> int:
    """
    Create or update the budget limit for an Expense category in a given month.

    Uses an idempotent upsert: if a budget already exists for the (category, month)
    combination, its limit is updated.

    Parameters
    ----------
    category : str
        Category name (case-insensitive lookup; must be an Expense category).
    month : str
        Target month in YYYY-MM format (01-12).
    amount : float | int | str
        Budget limit amount (must be strictly > 0).
    db_path : Optional[Path | str]
        Optional path to the SQLite database file.

    Returns
    -------
    int
        The primary key ID of the created or updated budget.

    Raises
    ------
    ValueError
        If category is invalid or non-existent, category type is not Expense,
        month format is invalid, or amount <= 0.
    """
    if not isinstance(category, str) or not category.strip():
        raise ValueError("Category name must be a non-empty string")
    category_clean = category.strip()

    validate_budget_month(month)
    valid_amount = _validate_budget_amount(amount)

    with get_connection(db_path) as conn:
        cat_row = conn.execute(
            "SELECT id, name, type FROM categories WHERE name = ? COLLATE NOCASE;",
            (category_clean,),
        ).fetchone()

        if cat_row is None:
            raise ValueError(f"Category '{category_clean}' does not exist")

        if cat_row["type"] != "Expense":
            raise ValueError(
                f"Budgets can only be set for Expense categories, got '{cat_row['type']}' "
                f"for category '{cat_row['name']}'"
            )

        category_id = cat_row["id"]

        # Upsert budget
        conn.execute(
            """
            INSERT INTO budgets (category_id, month, limit_amount)
            VALUES (?, ?, ?)
            ON CONFLICT(category_id, month) DO UPDATE SET limit_amount = excluded.limit_amount;
            """,
            (category_id, month, valid_amount),
        )

        row = conn.execute(
            "SELECT id FROM budgets WHERE category_id = ? AND month = ?;",
            (category_id, month),
        ).fetchone()

        budget_id = int(row["id"])
        logger.info(
            "Budget set: id=%d, category=%s, month=%s, limit=%.2f",
            budget_id,
            cat_row["name"],
            month,
            valid_amount,
        )
        return budget_id


def get_budget(
    category: str,
    month: str,
    db_path: Optional[Union[Path, str]] = None,
) -> Optional[dict[str, Any]]:
    """
    Retrieve budget details for a specific category and month.

    Parameters
    ----------
    category : str
        Category name (case-insensitive).
    month : str
        Month in YYYY-MM format.
    db_path : Optional[Path | str]
        Optional database path.

    Returns
    -------
    dict or None
        Dict containing budget details if found, or None if no budget exists.
    """
    if not isinstance(category, str) or not category.strip():
        return None
    validate_budget_month(month)

    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                b.id,
                c.name AS category,
                b.month,
                b.limit_amount,
                b.created_at
            FROM budgets b
            JOIN categories c ON b.category_id = c.id
            WHERE c.name = ? COLLATE NOCASE AND b.month = ?;
            """,
            (category.strip(), month),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": int(row["id"]),
            "category": str(row["category"]),
            "month": str(row["month"]),
            "limit_amount": round(float(row["limit_amount"]), 2),
            "created_at": str(row["created_at"]),
        }


def get_all_budgets(
    month: str,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Retrieve all budgets configured for a given month.

    Parameters
    ----------
    month : str
        Month in YYYY-MM format.
    db_path : Optional[Path | str]
        Optional database path.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: [budget_id, category, month, budget_limit]
        Ordered by category name ascending.
    """
    validate_budget_month(month)

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                b.id AS budget_id,
                c.name AS category,
                b.month,
                b.limit_amount AS budget_limit
            FROM budgets b
            JOIN categories c ON b.category_id = c.id
            WHERE b.month = ?
            ORDER BY c.name ASC;
            """,
            (month,),
        ).fetchall()

    if not rows:
        return pd.DataFrame(columns=BUDGET_COLUMNS).astype({
            "budget_id": "int64",
            "category": "object",
            "month": "object",
            "budget_limit": "float64",
        })

    data = [
        {
            "budget_id": int(r["budget_id"]),
            "category": str(r["category"]),
            "month": str(r["month"]),
            "budget_limit": round(float(r["budget_limit"]), 2),
        }
        for r in rows
    ]
    return pd.DataFrame(data, columns=BUDGET_COLUMNS)


def get_budget_status(
    month: str,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Compare monthly budget limits against actual Expense transactions.

    Calculates:
      - actual_expenses: Sum of Expense transactions in the category for that month.
      - remaining_budget: budget_limit - actual_expenses
      - utilization_percentage: (actual_expenses / budget_limit) * 100
      - status:
          * Normal: utilization < 80.0%
          * Warning: 80.0% <= utilization < 100.0%
          * Exceeded: utilization >= 100.0%

    Parameters
    ----------
    month : str
        Month in YYYY-MM format.
    db_path : Optional[Path | str]
        Optional database path.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns:
        [category, month, budget_limit, actual_expenses, remaining_budget, utilization_percentage, status]
        Ordered by category ascending.
    """
    validate_budget_month(month)

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                c.name AS category,
                b.month,
                b.limit_amount AS budget_limit,
                COALESCE(SUM(t.amount), 0.0) AS actual_expenses
            FROM budgets b
            JOIN categories c ON b.category_id = c.id
            LEFT JOIN transactions t ON t.category_id = b.category_id
                                    AND t.type = 'Expense'
                                    AND t.date LIKE ?
            WHERE b.month = ?
            GROUP BY b.id, c.name, b.month, b.limit_amount
            ORDER BY c.name ASC;
            """,
            (f"{month}%", month),
        ).fetchall()

    if not rows:
        return pd.DataFrame(columns=BUDGET_STATUS_COLUMNS).astype({
            "category": "object",
            "month": "object",
            "budget_limit": "float64",
            "actual_expenses": "float64",
            "remaining_budget": "float64",
            "utilization_percentage": "float64",
            "status": "object",
        })

    records = []
    for r in rows:
        limit = round(float(r["budget_limit"]), 2)
        spent = round(float(r["actual_expenses"]), 2)
        remaining = round(limit - spent, 2)
        utilization = round((spent / limit) * 100.0, 2) if limit > 0 else 0.0

        if utilization >= THRESHOLD_EXCEEDED:
            status = STATUS_EXCEEDED
        elif utilization >= THRESHOLD_WARNING:
            status = STATUS_WARNING
        else:
            status = STATUS_NORMAL

        records.append({
            "category": str(r["category"]),
            "month": str(r["month"]),
            "budget_limit": limit,
            "actual_expenses": spent,
            "remaining_budget": remaining,
            "utilization_percentage": utilization,
            "status": status,
        })

    return pd.DataFrame(records, columns=BUDGET_STATUS_COLUMNS)


def get_budget_alerts(
    month: str,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Retrieve budgets for the given month that have reached Warning or Exceeded status.

    Parameters
    ----------
    month : str
        Month in YYYY-MM format.
    db_path : Optional[Path | str]
        Optional database path.

    Returns
    -------
    pd.DataFrame
        Filtered DataFrame containing only Warning and Exceeded budgets.
    """
    status_df = get_budget_status(month, db_path=db_path)
    if status_df.empty:
        return status_df

    alerts_df = status_df[status_df["status"].isin([STATUS_WARNING, STATUS_EXCEEDED])].reset_index(drop=True)
    return alerts_df


def delete_budget(
    budget_id: int,
    db_path: Optional[Union[Path, str]] = None,
) -> bool:
    """
    Delete a budget entry by its ID.

    Never deletes or alters categories or transactions.

    Parameters
    ----------
    budget_id : int
        The primary key ID of the budget to delete.
    db_path : Optional[Path | str]
        Optional database path.

    Returns
    -------
    bool
        True if the budget was found and deleted, False otherwise.

    Raises
    ------
    ValueError
        If budget_id is not a positive integer.
    """
    if not isinstance(budget_id, int) or isinstance(budget_id, bool) or budget_id <= 0:
        raise ValueError(f"budget_id must be a positive integer, got {budget_id!r}")

    with get_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM budgets WHERE id = ?;", (budget_id,))
        deleted = cursor.rowcount > 0

    if deleted:
        logger.info("Deleted budget with id=%d", budget_id)
    else:
        logger.warning("Attempted to delete nonexistent budget id=%d", budget_id)

    return deleted


# ---------------------------------------------------------------------------
# BudgetManager OOP Class Wrapper
# ---------------------------------------------------------------------------

class BudgetManager:
    """
    Object-oriented interface for managing budgets and alerts.

    Parameters
    ----------
    db_path : Optional[Path | str]
        Optional path to the SQLite database file.
    """

    def __init__(self, db_path: Optional[Union[Path, str]] = None):
        self.db_path = db_path

    def set_budget(
        self,
        category: str,
        month: str,
        amount: Union[float, int, str],
    ) -> int:
        """Create or update a monthly budget for an Expense category."""
        return set_budget(category, month, amount, db_path=self.db_path)

    def get_budget(
        self,
        category: str,
        month: str,
    ) -> Optional[dict[str, Any]]:
        """Retrieve budget details for a category and month."""
        return get_budget(category, month, db_path=self.db_path)

    def get_all_budgets(self, month: str) -> pd.DataFrame:
        """Retrieve all budgets set for a month."""
        return get_all_budgets(month, db_path=self.db_path)

    def get_budget_status(self, month: str) -> pd.DataFrame:
        """Compare budget limits with actual expenses for a month."""
        return get_budget_status(month, db_path=self.db_path)

    def get_budget_alerts(self, month: str) -> pd.DataFrame:
        """Retrieve budgets with Warning or Exceeded status."""
        return get_budget_alerts(month, db_path=self.db_path)

    def delete_budget(self, budget_id: int) -> bool:
        """Delete a budget by its primary key ID."""
        return delete_budget(budget_id, db_path=self.db_path)
