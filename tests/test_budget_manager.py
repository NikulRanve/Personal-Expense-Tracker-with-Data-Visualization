"""
tests/test_budget_manager.py — Test Suite for Budget Management Module
========================================================================
Covers all required scenarios for Session 7:
  1. Set valid budget (returns budget_id, correctly stored)
  2. Update existing budget (upsert increases/decreases limit)
  3. Reject budget with zero amount
  4. Reject budget with negative amount
  5. Reject non-numeric / invalid amount (NaN, inf, str, boolean)
  6. Reject budget for non-existent category
  7. Reject budget for Income category
  8. Reject invalid month format (2026-13, 11-2026, etc.)
  9. Case-insensitive category lookup when setting budget
  10. Get budget for existing category and month
  11. Get budget for non-existent category or month (returns None)
  12. Get budget with invalid month raises ValueError
  13. Get all budgets for a month with multiple budgets
  14. Get all budgets for a month with no budgets (empty DataFrame with schema)
  15. Get budget status: Normal status (< 80% utilization)
  16. Get budget status: Warning status (80% <= utilization < 100%)
  17. Get budget status: Exceeded status (>= 100% utilization)
  18. Get budget status: Zero expenses (0.0% utilization, Normal)
  19. Get budget status: Multiple transactions summed accurately
  20. Get budget status: Transactions outside the specified month are excluded
  21. Get budget status: Income transactions do not affect expense budgets
  22. Get budget status: Other category expenses do not affect target budget
  23. Get budget status: Negative remaining budget when exceeded
  24. Get budget status: Month with no budgets returns empty DataFrame
  25. Get budget alerts: Returns only Warning and Exceeded budgets
  26. Get budget alerts: Returns empty DataFrame when all budgets are Normal
  27. Delete existing budget (returns True, row removed)
  28. Delete nonexistent budget (returns False)
  29. Delete budget with invalid ID raises ValueError
  30. Delete budget does not affect categories or transactions
  31. BudgetManager OOP class wrapper methods
"""

from __future__ import annotations

import math
from pathlib import Path
import sys

import pandas as pd
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from budget_manager import (
    BUDGET_COLUMNS,
    BUDGET_STATUS_COLUMNS,
    STATUS_EXCEEDED,
    STATUS_NORMAL,
    STATUS_WARNING,
    BudgetManager,
    delete_budget,
    get_all_budgets,
    get_budget,
    get_budget_alerts,
    get_budget_status,
    set_budget,
)
from database import (
    create_tables,
    get_connection,
    seed_categories,
)
from expense_manager import add_transaction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Provide a fresh SQLite database with tables, hardening triggers, and default categories."""
    db_file = tmp_path / "test_budget.db"
    create_tables(db_file)
    seed_categories(db_file)
    return db_file


# ---------------------------------------------------------------------------
# 1. set_budget Tests
# ---------------------------------------------------------------------------

class TestSetBudget:
    """Tests for creating and updating budget limits."""

    def test_set_valid_budget(self, temp_db: Path):
        b_id = set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        assert isinstance(b_id, int)
        assert b_id > 0

        b = get_budget("Food", "2026-11", db_path=temp_db)
        assert b is not None
        assert b["id"] == b_id
        assert b["category"] == "Food"
        assert b["month"] == "2026-11"
        assert b["limit_amount"] == 5000.0
        assert "created_at" in b

    def test_set_budget_upsert_update(self, temp_db: Path):
        b_id1 = set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        b_id2 = set_budget("Food", "2026-11", 7500.0, db_path=temp_db)
        assert b_id1 == b_id2

        b = get_budget("Food", "2026-11", db_path=temp_db)
        assert b is not None
        assert b["limit_amount"] == 7500.0

        # Verify only one row exists for (Food, 2026-11)
        df = get_all_budgets("2026-11", db_path=temp_db)
        assert len(df) == 1

    def test_set_budget_multi_category_id_isolation(self, temp_db: Path):
        """Confirm updating one category preserves its ID and does not cross-talk with another category."""
        food_id_1 = set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        trans_id_1 = set_budget("Transportation", "2026-11", 2000.0, db_path=temp_db)
        assert food_id_1 != trans_id_1

        # Update Food
        food_id_2 = set_budget("Food", "2026-11", 6000.0, db_path=temp_db)
        assert food_id_2 == food_id_1
        assert food_id_2 != trans_id_1

        # Update Transportation
        trans_id_2 = set_budget("Transportation", "2026-11", 2500.0, db_path=temp_db)
        assert trans_id_2 == trans_id_1
        assert trans_id_2 != food_id_2

    def test_set_budget_reject_zero_amount(self, temp_db: Path):
        with pytest.raises(ValueError, match="strictly greater than zero"):
            set_budget("Food", "2026-11", 0, db_path=temp_db)

        with pytest.raises(ValueError, match="strictly greater than zero"):
            set_budget("Food", "2026-11", 0.0, db_path=temp_db)

    def test_set_budget_reject_negative_amount(self, temp_db: Path):
        with pytest.raises(ValueError, match="strictly greater than zero"):
            set_budget("Food", "2026-11", -250.0, db_path=temp_db)

    def test_set_budget_reject_invalid_amount_types(self, temp_db: Path):
        with pytest.raises(ValueError, match="numeric"):
            set_budget("Food", "2026-11", "not-a-number", db_path=temp_db)

        with pytest.raises(ValueError, match="positive number"):
            set_budget("Food", "2026-11", None, db_path=temp_db)

        with pytest.raises(ValueError, match="positive number"):
            set_budget("Food", "2026-11", True, db_path=temp_db)

        with pytest.raises(ValueError, match="finite"):
            set_budget("Food", "2026-11", float("nan"), db_path=temp_db)

        with pytest.raises(ValueError, match="finite"):
            set_budget("Food", "2026-11", float("inf"), db_path=temp_db)

    def test_set_budget_reject_unknown_category(self, temp_db: Path):
        with pytest.raises(ValueError, match="Category 'NonExistent' does not exist"):
            set_budget("NonExistent", "2026-11", 1000.0, db_path=temp_db)

    def test_set_budget_reject_empty_category(self, temp_db: Path):
        with pytest.raises(ValueError, match="non-empty string"):
            set_budget("", "2026-11", 1000.0, db_path=temp_db)

        with pytest.raises(ValueError, match="non-empty string"):
            set_budget("   ", "2026-11", 1000.0, db_path=temp_db)

    def test_set_budget_reject_income_category(self, temp_db: Path):
        with pytest.raises(ValueError, match="Budgets can only be set for Expense categories"):
            set_budget("Salary", "2026-11", 50000.0, db_path=temp_db)

        with pytest.raises(ValueError, match="Budgets can only be set for Expense categories"):
            set_budget("Other Income", "2026-11", 10000.0, db_path=temp_db)

    def test_set_budget_reject_invalid_month(self, temp_db: Path):
        for invalid_month in ["2026-13", "2026-00", "11-2026", "2026/11", "2026-1", "abc"]:
            with pytest.raises(ValueError, match="Invalid month"):
                set_budget("Food", invalid_month, 5000.0, db_path=temp_db)

    def test_set_budget_case_insensitive_category(self, temp_db: Path):
        b_id = set_budget("food", "2026-11", 4000.0, db_path=temp_db)
        b = get_budget("FOOD", "2026-11", db_path=temp_db)
        assert b is not None
        assert b["category"] == "Food"
        assert b["limit_amount"] == 4000.0


# ---------------------------------------------------------------------------
# 2. get_budget & get_all_budgets Tests
# ---------------------------------------------------------------------------

class TestGetBudgets:
    """Tests for reading budget records."""

    def test_get_budget_existing(self, temp_db: Path):
        set_budget("Healthcare", "2026-11", 3000.0, db_path=temp_db)
        res = get_budget("Healthcare", "2026-11", db_path=temp_db)
        assert res is not None
        assert res["category"] == "Healthcare"
        assert res["month"] == "2026-11"
        assert res["limit_amount"] == 3000.0
        assert "created_at" in res

    def test_get_budget_nonexistent(self, temp_db: Path):
        assert get_budget("Food", "2026-11", db_path=temp_db) is None
        assert get_budget("NonExistent", "2026-11", db_path=temp_db) is None
        assert get_budget("", "2026-11", db_path=temp_db) is None

    def test_get_budget_invalid_month(self, temp_db: Path):
        with pytest.raises(ValueError, match="Invalid month"):
            get_budget("Food", "2026-99", db_path=temp_db)

    def test_get_all_budgets_multiple(self, temp_db: Path):
        set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        set_budget("Transportation", "2026-11", 2000.0, db_path=temp_db)
        set_budget("Shopping", "2026-11", 3500.0, db_path=temp_db)
        # Budget in a different month
        set_budget("Food", "2026-12", 6000.0, db_path=temp_db)

        df = get_all_budgets("2026-11", db_path=temp_db)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert list(df.columns) == BUDGET_COLUMNS
        assert list(df["category"]) == ["Food", "Shopping", "Transportation"]
        assert list(df["budget_limit"]) == [5000.0, 3500.0, 2000.0]

    def test_get_all_budgets_empty(self, temp_db: Path):
        df = get_all_budgets("2026-11", db_path=temp_db)
        assert isinstance(df, pd.DataFrame)
        assert df.empty
        assert list(df.columns) == BUDGET_COLUMNS


# ---------------------------------------------------------------------------
# 3. get_budget_status Tests
# ---------------------------------------------------------------------------

class TestBudgetStatus:
    """Tests for budget status calculation, thresholds, and edge cases."""

    def test_budget_status_normal(self, temp_db: Path):
        # Limit 5000, spent 2500 -> 50.0% -> Normal
        set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        add_transaction("2026-11-05", "Food", 2500.0, "UPI", "Groceries", "Expense", db_path=temp_db)

        df = get_budget_status("2026-11", db_path=temp_db)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["category"] == "Food"
        assert row["budget_limit"] == 5000.0
        assert row["actual_expenses"] == 2500.0
        assert row["remaining_budget"] == 2500.0
        assert row["utilization_percentage"] == 50.0
        assert row["status"] == STATUS_NORMAL

    def test_budget_status_warning_at_exact_threshold(self, temp_db: Path):
        # Limit 1000, spent 800 -> 80.0% -> Warning
        set_budget("Shopping", "2026-11", 1000.0, db_path=temp_db)
        add_transaction("2026-11-10", "Shopping", 800.0, "Card", "Clothes", "Expense", db_path=temp_db)

        df = get_budget_status("2026-11", db_path=temp_db)
        row = df.iloc[0]
        assert row["utilization_percentage"] == 80.0
        assert row["status"] == STATUS_WARNING
        assert row["remaining_budget"] == 200.0

    def test_budget_status_warning_near_limit(self, temp_db: Path):
        # Limit 1000, spent 950 -> 95.0% -> Warning
        set_budget("Utilities", "2026-11", 1000.0, db_path=temp_db)
        add_transaction("2026-11-12", "Utilities", 950.0, "UPI", "Electricity", "Expense", db_path=temp_db)

        df = get_budget_status("2026-11", db_path=temp_db)
        row = df.iloc[0]
        assert row["utilization_percentage"] == 95.0
        assert row["status"] == STATUS_WARNING
        assert row["remaining_budget"] == 50.0

    def test_budget_status_exceeded_at_exact_limit(self, temp_db: Path):
        # Limit 2000, spent 2000 -> 100.0% -> Exceeded
        set_budget("Transportation", "2026-11", 2000.0, db_path=temp_db)
        add_transaction("2026-11-15", "Transportation", 2000.0, "Card", "Fuel", "Expense", db_path=temp_db)

        df = get_budget_status("2026-11", db_path=temp_db)
        row = df.iloc[0]
        assert row["utilization_percentage"] == 100.0
        assert row["remaining_budget"] == 0.0
        assert row["status"] == STATUS_EXCEEDED

    def test_budget_status_exceeded_over_limit(self, temp_db: Path):
        # Limit 1000, spent 1500 -> 150.0% -> Exceeded
        set_budget("Healthcare", "2026-11", 1000.0, db_path=temp_db)
        add_transaction("2026-11-18", "Healthcare", 1500.0, "Cash", "Dentist", "Expense", db_path=temp_db)

        df = get_budget_status("2026-11", db_path=temp_db)
        row = df.iloc[0]
        assert row["utilization_percentage"] == 150.0
        assert row["remaining_budget"] == -500.0
        assert row["status"] == STATUS_EXCEEDED

    def test_budget_status_zero_expenses(self, temp_db: Path):
        # Budget set, 0 expenses logged -> 0.0% -> Normal
        set_budget("Housing", "2026-11", 15000.0, db_path=temp_db)

        df = get_budget_status("2026-11", db_path=temp_db)
        row = df.iloc[0]
        assert row["actual_expenses"] == 0.0
        assert row["remaining_budget"] == 15000.0
        assert row["utilization_percentage"] == 0.0
        assert row["status"] == STATUS_NORMAL

    def test_budget_status_multiple_transactions_summed(self, temp_db: Path):
        set_budget("Food", "2026-11", 3000.0, db_path=temp_db)
        add_transaction("2026-11-01", "Food", 500.0, "UPI", "Dinner", "Expense", db_path=temp_db)
        add_transaction("2026-11-05", "Food", 700.0, "Cash", "Lunch", "Expense", db_path=temp_db)
        add_transaction("2026-11-10", "Food", 800.0, "Card", "Snacks", "Expense", db_path=temp_db)

        df = get_budget_status("2026-11", db_path=temp_db)
        row = df.iloc[0]
        assert row["actual_expenses"] == 2000.0
        assert row["remaining_budget"] == 1000.0
        assert row["utilization_percentage"] == 66.67
        assert row["status"] == STATUS_NORMAL

    def test_budget_status_other_month_transactions_excluded(self, temp_db: Path):
        set_budget("Food", "2026-11", 2000.0, db_path=temp_db)
        # Oct and Dec transactions should not count
        add_transaction("2026-10-28", "Food", 1500.0, "UPI", "Oct food", "Expense", db_path=temp_db)
        add_transaction("2026-11-02", "Food", 400.0, "UPI", "Nov food", "Expense", db_path=temp_db)
        add_transaction("2026-12-01", "Food", 800.0, "UPI", "Dec food", "Expense", db_path=temp_db)

        df = get_budget_status("2026-11", db_path=temp_db)
        row = df.iloc[0]
        assert row["actual_expenses"] == 400.0
        assert row["remaining_budget"] == 1600.0
        assert row["utilization_percentage"] == 20.0
        assert row["status"] == STATUS_NORMAL

    def test_budget_status_income_transactions_excluded(self, temp_db: Path):
        set_budget("Food", "2026-11", 2000.0, db_path=temp_db)
        # Add income transaction
        add_transaction("2026-11-01", "Salary", 50000.0, "Bank Transfer", "Monthly Salary", "Income", db_path=temp_db)

        df = get_budget_status("2026-11", db_path=temp_db)
        row = df.iloc[0]
        assert row["actual_expenses"] == 0.0
        assert row["remaining_budget"] == 2000.0

    def test_budget_status_empty_when_no_budgets(self, temp_db: Path):
        df = get_budget_status("2026-11", db_path=temp_db)
        assert isinstance(df, pd.DataFrame)
        assert df.empty
        assert list(df.columns) == BUDGET_STATUS_COLUMNS


# ---------------------------------------------------------------------------
# 4. get_budget_alerts Tests
# ---------------------------------------------------------------------------

class TestBudgetAlerts:
    """Tests for threshold alerts filtering."""

    def test_get_budget_alerts_filtered(self, temp_db: Path):
        # 1. Normal (50%)
        set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        add_transaction("2026-11-01", "Food", 2500.0, "UPI", "Food", "Expense", db_path=temp_db)

        # 2. Warning (85%)
        set_budget("Transportation", "2026-11", 2000.0, db_path=temp_db)
        add_transaction("2026-11-02", "Transportation", 1700.0, "Card", "Metro", "Expense", db_path=temp_db)

        # 3. Exceeded (110%)
        set_budget("Shopping", "2026-11", 1000.0, db_path=temp_db)
        add_transaction("2026-11-03", "Shopping", 1100.0, "Card", "Mall", "Expense", db_path=temp_db)

        alerts = get_budget_alerts("2026-11", db_path=temp_db)
        assert len(alerts) == 2
        categories = list(alerts["category"])
        assert "Transportation" in categories
        assert "Shopping" in categories
        assert "Food" not in categories

        statuses = list(alerts["status"])
        assert STATUS_WARNING in statuses
        assert STATUS_EXCEEDED in statuses
        assert STATUS_NORMAL not in statuses

    def test_get_budget_alerts_empty_when_all_normal(self, temp_db: Path):
        set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        add_transaction("2026-11-01", "Food", 1000.0, "UPI", "Food", "Expense", db_path=temp_db)

        alerts = get_budget_alerts("2026-11", db_path=temp_db)
        assert isinstance(alerts, pd.DataFrame)
        assert alerts.empty
        assert list(alerts.columns) == BUDGET_STATUS_COLUMNS


# ---------------------------------------------------------------------------
# 5. delete_budget Tests
# ---------------------------------------------------------------------------

class TestDeleteBudget:
    """Tests for deleting budget limits."""

    def test_delete_existing_budget(self, temp_db: Path):
        b_id = set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        assert delete_budget(b_id, db_path=temp_db) is True

        assert get_budget("Food", "2026-11", db_path=temp_db) is None
        df = get_all_budgets("2026-11", db_path=temp_db)
        assert df.empty

    def test_delete_nonexistent_budget(self, temp_db: Path):
        assert delete_budget(99999, db_path=temp_db) is False

    def test_delete_budget_invalid_id(self, temp_db: Path):
        with pytest.raises(ValueError, match="positive integer"):
            delete_budget(0, db_path=temp_db)

        with pytest.raises(ValueError, match="positive integer"):
            delete_budget(-5, db_path=temp_db)

        with pytest.raises(ValueError, match="positive integer"):
            delete_budget("1", db_path=temp_db)

        with pytest.raises(ValueError, match="positive integer"):
            delete_budget(True, db_path=temp_db)

    def test_delete_budget_does_not_affect_categories_or_transactions(self, temp_db: Path):
        b_id = set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        txn_id = add_transaction("2026-11-05", "Food", 250.0, "Cash", "Lunch", "Expense", db_path=temp_db)

        delete_budget(b_id, db_path=temp_db)

        # Check transactions and categories are completely untouched
        with get_connection(temp_db) as conn:
            txn_count = conn.execute("SELECT count(*) FROM transactions WHERE id = ?;", (txn_id,)).fetchone()[0]
            cat_count = conn.execute("SELECT count(*) FROM categories WHERE name = 'Food';").fetchone()[0]
            assert txn_count == 1
            assert cat_count == 1


# ---------------------------------------------------------------------------
# 6. BudgetManager OOP Class Wrapper Tests
# ---------------------------------------------------------------------------

class TestBudgetManagerClass:
    """Tests for BudgetManager OOP wrapper interface."""

    def test_budget_manager_oop_interface(self, temp_db: Path):
        mgr = BudgetManager(temp_db)

        # 1. set_budget
        b_id = mgr.set_budget("Food", "2026-11", 6000.0)
        assert b_id > 0

        # 2. get_budget
        b = mgr.get_budget("Food", "2026-11")
        assert b is not None
        assert b["limit_amount"] == 6000.0

        # 3. get_all_budgets
        df = mgr.get_all_budgets("2026-11")
        assert len(df) == 1

        # 4. get_budget_status & get_budget_alerts
        add_transaction("2026-11-10", "Food", 5400.0, "UPI", "Dinner", "Expense", db_path=temp_db)
        status_df = mgr.get_budget_status("2026-11")
        assert len(status_df) == 1
        assert status_df.iloc[0]["status"] == STATUS_WARNING

        alerts = mgr.get_budget_alerts("2026-11")
        assert len(alerts) == 1

        # 5. delete_budget
        deleted = mgr.delete_budget(b_id)
        assert deleted is True
        assert mgr.get_budget("Food", "2026-11") is None
