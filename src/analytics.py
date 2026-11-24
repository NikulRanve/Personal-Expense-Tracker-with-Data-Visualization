"""
src/analytics.py — Financial Analytics Module
==============================================
Computes deterministic financial analytics, aggregations, trend series,
and multi-period comparisons from transaction data.

Public API
----------
  - get_financial_overview(start_date=None, end_date=None, db_path=None) -> dict
  - get_category_wise_expenses(start_date=None, end_date=None, db_path=None) -> pd.DataFrame
  - get_monthly_summary(year=None, db_path=None) -> pd.DataFrame
  - get_monthly_trends(year=None, db_path=None) -> pd.DataFrame
  - get_payment_method_summary(start_date=None, end_date=None, db_path=None) -> pd.DataFrame
  - get_top_expense_categories(limit=5, start_date=None, end_date=None, db_path=None) -> pd.DataFrame
  - get_average_transaction(start_date=None, end_date=None, db_path=None) -> dict
  - compare_months(first_month, second_month, db_path=None) -> dict
  - Analytics (OOP class wrapper)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

from database import (
    DEFAULT_DB_PATH,
    get_connection,
    validate_budget_month,
    validate_transaction_date,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def _build_date_filter(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[list[str], list[str]]:
    """Validate and generate WHERE clauses for optional start_date and end_date."""
    clauses: list[str] = []
    params: list[str] = []

    if start_date:
        parsed_start = validate_transaction_date(start_date)
        clauses.append("t.date >= ?")
        params.append(parsed_start.strftime("%Y-%m-%d"))

    if end_date:
        parsed_end = validate_transaction_date(end_date)
        clauses.append("t.date <= ?")
        params.append(parsed_end.strftime("%Y-%m-%d"))

    if start_date and end_date and start_date > end_date:
        raise ValueError(
            f"Invalid date range: start_date ({start_date}) cannot be after end_date ({end_date})."
        )

    return clauses, params


# ---------------------------------------------------------------------------
# A. Financial Overview
# ---------------------------------------------------------------------------

def get_financial_overview(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> dict[str, Any]:
    """
    Compute comprehensive high-level financial overview metrics.

    Formulas
    --------
    net_savings = total_income - total_expenses
    savings_rate = (net_savings / total_income) * 100, if total_income > 0 else 0.0

    Returns
    -------
    dict
        {
            "total_income": float,
            "total_expenses": float,
            "net_savings": float,
            "savings_rate": float,
            "transaction_count": int,
            "income_transaction_count": int,
            "expense_transaction_count": int,
        }
    """
    clauses, params = _build_date_filter(start_date, end_date)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    query = f"""
        SELECT
            COALESCE(SUM(CASE WHEN t.type = 'Income' THEN t.amount ELSE 0 END), 0.0) AS total_income,
            COALESCE(SUM(CASE WHEN t.type = 'Expense' THEN t.amount ELSE 0 END), 0.0) AS total_expenses,
            COUNT(*) AS transaction_count,
            COALESCE(SUM(CASE WHEN t.type = 'Income' THEN 1 ELSE 0 END), 0) AS income_count,
            COALESCE(SUM(CASE WHEN t.type = 'Expense' THEN 1 ELSE 0 END), 0) AS expense_count
        FROM transactions t
        {where_sql};
    """

    with get_connection(db_path) as conn:
        row = conn.execute(query, params).fetchone()

    total_income = round(float(row["total_income"]), 2)
    total_expenses = round(float(row["total_expenses"]), 2)
    net_savings = round(total_income - total_expenses, 2)
    txn_count = int(row["transaction_count"])
    inc_count = int(row["income_count"])
    exp_count = int(row["expense_count"])

    savings_rate = (
        round((net_savings / total_income) * 100.0, 2)
        if total_income > 0
        else 0.0
    )

    return {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_savings": net_savings,
        "savings_rate": savings_rate,
        "transaction_count": txn_count,
        "income_transaction_count": inc_count,
        "expense_transaction_count": exp_count,
    }


# ---------------------------------------------------------------------------
# B. Category-wise Expenses
# ---------------------------------------------------------------------------

def get_category_wise_expenses(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Compute breakdown of expenses across categories.

    Rules:
      - Expense transactions only (excludes Income).
      - Sorted by total_expenses descending.
      - percentage_of_total calculated against total expenses.

    Returns
    -------
    pd.DataFrame
        Columns: category, total_expenses, transaction_count, percentage_of_total
    """
    clauses, params = _build_date_filter(start_date, end_date)
    clauses.append("t.type = 'Expense'")
    where_sql = f"WHERE {' AND '.join(clauses)}"

    query = f"""
        SELECT
            c.name AS category,
            COALESCE(SUM(t.amount), 0.0) AS total_expenses,
            COUNT(t.id) AS transaction_count
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        {where_sql}
        GROUP BY c.name
        ORDER BY total_expenses DESC, c.name ASC;
    """

    cols = ["category", "total_expenses", "transaction_count", "percentage_of_total"]

    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=params)

    if df.empty:
        return pd.DataFrame(columns=cols)

    df["total_expenses"] = df["total_expenses"].astype(float).round(2)
    df["transaction_count"] = df["transaction_count"].astype(int)

    grand_total = df["total_expenses"].sum()
    if grand_total > 0:
        df["percentage_of_total"] = ((df["total_expenses"] / grand_total) * 100.0).round(2)
    else:
        df["percentage_of_total"] = 0.0

    return df[cols]


# ---------------------------------------------------------------------------
# C. Monthly Summary
# ---------------------------------------------------------------------------

def get_monthly_summary(
    year: Optional[Union[int, str]] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Compute aggregated financial metrics grouped by month.

    Rules:
      - Chronologically sorted (month ASC).
      - Calculates income and expenses separately.
      - savings_rate = (net_savings / total_income) * 100 if total_income > 0 else 0.0.

    Returns
    -------
    pd.DataFrame
        Columns: month, total_income, total_expenses, net_savings, savings_rate
    """
    clauses: list[str] = []
    params: list[Any] = []

    if year is not None:
        clauses.append("t.date LIKE ?")
        params.append(f"{int(year):04d}-%")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    query = f"""
        SELECT
            substr(t.date, 1, 7) AS month,
            COALESCE(SUM(CASE WHEN t.type = 'Income' THEN t.amount ELSE 0 END), 0.0) AS total_income,
            COALESCE(SUM(CASE WHEN t.type = 'Expense' THEN t.amount ELSE 0 END), 0.0) AS total_expenses
        FROM transactions t
        {where_sql}
        GROUP BY substr(t.date, 1, 7)
        ORDER BY month ASC;
    """

    cols = ["month", "total_income", "total_expenses", "net_savings", "savings_rate"]

    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=params)

    if df.empty:
        return pd.DataFrame(columns=cols)

    df["total_income"] = df["total_income"].astype(float).round(2)
    df["total_expenses"] = df["total_expenses"].astype(float).round(2)
    df["net_savings"] = (df["total_income"] - df["total_expenses"]).round(2)

    df["savings_rate"] = np.where(
        df["total_income"] > 0,
        ((df["net_savings"] / df["total_income"]) * 100.0).round(2),
        0.0,
    )

    return df[cols]


# ---------------------------------------------------------------------------
# D. Monthly Trends
# ---------------------------------------------------------------------------

def get_monthly_trends(
    year: Optional[Union[int, str]] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Return monthly financial trend data formatted for visualization.

    Returns
    -------
    pd.DataFrame
        Columns: month, income, expenses, net_savings
    """
    df_summary = get_monthly_summary(year=year, db_path=db_path)
    cols = ["month", "income", "expenses", "net_savings"]

    if df_summary.empty:
        return pd.DataFrame(columns=cols)

    trend_df = pd.DataFrame({
        "month": df_summary["month"],
        "income": df_summary["total_income"],
        "expenses": df_summary["total_expenses"],
        "net_savings": df_summary["net_savings"],
    })
    return trend_df[cols]


# ---------------------------------------------------------------------------
# E. Payment Method Summary
# ---------------------------------------------------------------------------

def get_payment_method_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Compute expenses grouped by payment method.

    Rules:
      - Expense transactions only.
      - Missing, null, or blank payment methods represented as 'Unspecified'.
      - Sorted by total_expenses descending.

    Returns
    -------
    pd.DataFrame
        Columns: payment_method, total_expenses, transaction_count, percentage_of_total
    """
    clauses, params = _build_date_filter(start_date, end_date)
    clauses.append("t.type = 'Expense'")
    where_sql = f"WHERE {' AND '.join(clauses)}"

    query = f"""
        SELECT
            CASE
                WHEN t.payment_method IS NULL OR trim(t.payment_method) = '' THEN 'Unspecified'
                ELSE trim(t.payment_method)
            END AS payment_method,
            COALESCE(SUM(t.amount), 0.0) AS total_expenses,
            COUNT(t.id) AS transaction_count
        FROM transactions t
        {where_sql}
        GROUP BY 1
        ORDER BY total_expenses DESC, payment_method ASC;
    """

    cols = ["payment_method", "total_expenses", "transaction_count", "percentage_of_total"]

    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=params)

    if df.empty:
        return pd.DataFrame(columns=cols)

    df["total_expenses"] = df["total_expenses"].astype(float).round(2)
    df["transaction_count"] = df["transaction_count"].astype(int)

    grand_total = df["total_expenses"].sum()
    if grand_total > 0:
        df["percentage_of_total"] = ((df["total_expenses"] / grand_total) * 100.0).round(2)
    else:
        df["percentage_of_total"] = 0.0

    return df[cols]


# ---------------------------------------------------------------------------
# F. Top Expense Categories
# ---------------------------------------------------------------------------

def get_top_expense_categories(
    limit: int = 5,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """
    Retrieve top N expense categories by total spend.

    Parameters
    ----------
    limit : int, default 5
        Maximum number of categories to return.
    """
    df = get_category_wise_expenses(start_date=start_date, end_date=end_date, db_path=db_path)
    if df.empty or limit <= 0:
        return pd.DataFrame(columns=["category", "total_expenses", "transaction_count", "percentage_of_total"])
    return df.head(limit).copy()


# ---------------------------------------------------------------------------
# G. Average, Highest, and Lowest Transactions
# ---------------------------------------------------------------------------

def get_average_transaction(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> dict[str, Any]:
    """
    Compute average, maximum, and minimum transaction values for Income and Expense.

    Returns
    -------
    dict
        {
            "average_expense": float,
            "average_income": float,
            "highest_expense": float,
            "highest_income": float,
            "lowest_expense": float,
            "lowest_income": float,
        }
    """
    clauses, params = _build_date_filter(start_date, end_date)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    query = f"""
        SELECT
            t.type,
            COALESCE(AVG(t.amount), 0.0) AS avg_amt,
            COALESCE(MAX(t.amount), 0.0) AS max_amt,
            COALESCE(MIN(t.amount), 0.0) AS min_amt,
            COUNT(t.id) AS count_txns
        FROM transactions t
        {where_sql}
        GROUP BY t.type;
    """

    res = {
        "average_expense": 0.0,
        "average_income": 0.0,
        "highest_expense": 0.0,
        "highest_income": 0.0,
        "lowest_expense": 0.0,
        "lowest_income": 0.0,
    }

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    for r in rows:
        t_type = r["type"]
        if r["count_txns"] > 0:
            if t_type == "Expense":
                res["average_expense"] = round(float(r["avg_amt"]), 2)
                res["highest_expense"] = round(float(r["max_amt"]), 2)
                res["lowest_expense"] = round(float(r["min_amt"]), 2)
            elif t_type == "Income":
                res["average_income"] = round(float(r["avg_amt"]), 2)
                res["highest_income"] = round(float(r["max_amt"]), 2)
                res["lowest_income"] = round(float(r["min_amt"]), 2)

    return res


# ---------------------------------------------------------------------------
# H. Month Comparison
# ---------------------------------------------------------------------------

def compare_months(
    first_month: str,
    second_month: str,
    db_path: Optional[Union[Path, str]] = None,
) -> dict[str, Any]:
    """
    Compare financial performance between two calendar months (YYYY-MM).

    Percentage Change Formula
    -------------------------
    change = ((second - first) / abs(first)) * 100

    Zero Baseline Policy:
      - If first == 0: None (percentage change is undefined from a zero baseline;
        absolute change is retained in *_change_abs fields)
      - When first != 0: returns round(((second - first) / abs(first)) * 100.0, 2)
        using abs(first) to preserve intuitive directional signs for negative balances.

    Returns
    -------
    dict
        {
            "first_month": str,
            "second_month": str,
            "first_month_income": float,
            "second_month_income": float,
            "first_month_expenses": float,
            "second_month_expenses": float,
            "first_month_savings": float,
            "second_month_savings": float,
            "income_change": Optional[float],   # percentage, None if first_month == 0
            "expense_change": Optional[float],  # percentage, None if first_month == 0
            "savings_change": Optional[float],  # percentage, None if first_month == 0
            "income_change_abs": float,         # absolute currency delta
            "expense_change_abs": float,        # absolute currency delta
            "savings_change_abs": float,        # absolute currency delta
        }
    """
    validate_budget_month(first_month)
    validate_budget_month(second_month)

    def _get_month_totals(m_str: str) -> tuple[float, float, float]:
        with get_connection(db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN type = 'Income' THEN amount ELSE 0 END), 0.0) AS income,
                    COALESCE(SUM(CASE WHEN type = 'Expense' THEN amount ELSE 0 END), 0.0) AS expenses
                FROM transactions
                WHERE date LIKE ?;
                """,
                (f"{m_str}%",),
            ).fetchone()
        inc = round(float(row["income"]), 2)
        exp = round(float(row["expenses"]), 2)
        sav = round(inc - exp, 2)
        return inc, exp, sav

    m1_inc, m1_exp, m1_sav = _get_month_totals(first_month)
    m2_inc, m2_exp, m2_sav = _get_month_totals(second_month)

    def _calc_pct_change(v1: float, v2: float) -> Optional[float]:
        if v1 == 0.0:
            return None
        return round(((v2 - v1) / abs(v1)) * 100.0, 2)

    inc_pct = _calc_pct_change(m1_inc, m2_inc)
    exp_pct = _calc_pct_change(m1_exp, m2_exp)
    sav_pct = _calc_pct_change(m1_sav, m2_sav)

    return {
        "first_month": first_month,
        "second_month": second_month,
        "first_month_income": m1_inc,
        "second_month_income": m2_inc,
        "first_month_expenses": m1_exp,
        "second_month_expenses": m2_exp,
        "first_month_savings": m1_sav,
        "second_month_savings": m2_sav,
        "income_change": inc_pct,
        "expense_change": exp_pct,
        "savings_change": sav_pct,
        "income_change_abs": round(m2_inc - m1_inc, 2),
        "expense_change_abs": round(m2_exp - m1_exp, 2),
        "savings_change_abs": round(m2_sav - m1_sav, 2),
    }


# ---------------------------------------------------------------------------
# Analytics OOP Class Wrapper
# ---------------------------------------------------------------------------

class Analytics:
    """
    Object-oriented analytics interface for financial reporting.
    """

    def __init__(self, db_manager: Any = None):
        if hasattr(db_manager, "db_path"):
            self.db_path = db_manager.db_path
        elif isinstance(db_manager, (str, Path)):
            self.db_path = db_manager
        else:
            self.db_path = None

    def get_financial_overview(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> dict[str, Any]:
        return get_financial_overview(start_date=start_date, end_date=end_date, db_path=self.db_path)

    def get_category_wise_expenses(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return get_category_wise_expenses(start_date=start_date, end_date=end_date, db_path=self.db_path)

    def get_monthly_summary(self, year: Optional[Union[int, str]] = None) -> pd.DataFrame:
        return get_monthly_summary(year=year, db_path=self.db_path)

    def get_monthly_trends(self, year: Optional[Union[int, str]] = None) -> pd.DataFrame:
        return get_monthly_trends(year=year, db_path=self.db_path)

    def get_payment_method_summary(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return get_payment_method_summary(start_date=start_date, end_date=end_date, db_path=self.db_path)

    def get_top_expense_categories(
        self, limit: int = 5, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return get_top_expense_categories(limit=limit, start_date=start_date, end_date=end_date, db_path=self.db_path)

    def get_average_transaction(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> dict[str, Any]:
        return get_average_transaction(start_date=start_date, end_date=end_date, db_path=self.db_path)

    def compare_months(self, first_month: str, second_month: str) -> dict[str, Any]:
        return compare_months(first_month, second_month, db_path=self.db_path)
