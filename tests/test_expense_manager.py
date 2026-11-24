"""
tests/test_expense_manager.py — Tests for Expense Manager CRUD Operations
==========================================================================
Covers all 26 required scenarios:
  1. Add valid expense
  2. Add valid income
  3. Reject zero amount
  4. Reject negative amount
  5. Reject invalid date
  6. Reject unknown category
  7. Reject category/type mismatch
  8. Retrieve transaction by ID
  9. Retrieve nonexistent transaction
  10. Retrieve all transactions
  11. Empty database retrieval
  12. Update existing transaction
  13. Update nonexistent transaction
  14. Update category and type together correctly
  15. Reject invalid update
  16. Delete existing transaction
  17. Delete nonexistent transaction
  18. Filter by category
  19. Filter by type
  20. Filter by date range
  21. Filter by month and year
  22. Filter by payment method
  23. Search description
  24. Combine multiple filters
  25. Calculate income, expenses, and net savings
  26. Verify imported transactions are retrievable
"""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database import (
    get_connection,
    initialise_database,
    migrate_add_duplicate_rows_column,
    migrate_add_hardening_triggers,
)
from expense_manager import (
    ExpenseManager,
    add_transaction,
    delete_transaction,
    get_all_transactions,
    get_filtered_transactions,
    get_transaction,
    get_transaction_summary,
    update_transaction,
)
from import_service import (
    import_transactions,
    preview_import,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Isolated temporary SQLite database with all tables and seed categories."""
    db_file = tmp_path / "test_expense_manager.db"
    initialise_database(db_file)
    migrate_add_hardening_triggers(db_file)
    migrate_add_duplicate_rows_column(db_file)
    return db_file


# ---------------------------------------------------------------------------
# Test Suites
# ---------------------------------------------------------------------------

class TestAddTransaction:
    """Tests for adding transactions and validation rules."""

    def test_add_valid_expense(self, temp_db: Path):
        txn_id = add_transaction(
            date="2026-11-01",
            category="Food",
            amount=250.00,
            payment_method="UPI",
            description="Lunch",
            type="Expense",
            db_path=temp_db,
        )
        assert txn_id > 0
        txn = get_transaction(txn_id, db_path=temp_db)
        assert txn is not None
        assert txn["date"] == "2026-11-01"
        assert txn["category"] == "Food"
        assert txn["amount"] == 250.00
        assert txn["payment_method"] == "UPI"
        assert txn["description"] == "Lunch"
        assert txn["type"] == "Expense"

    def test_add_valid_income(self, temp_db: Path):
        txn_id = add_transaction(
            date="2026-11-02",
            category="Salary",
            amount=50000.00,
            payment_method="Bank Transfer",
            description="Monthly salary",
            type="Income",
            db_path=temp_db,
        )
        assert txn_id > 0
        txn = get_transaction(txn_id, db_path=temp_db)
        assert txn is not None
        assert txn["type"] == "Income"
        assert txn["amount"] == 50000.00

    def test_reject_zero_amount(self, temp_db: Path):
        with pytest.raises(ValueError, match="greater than zero"):
            add_transaction(
                date="2026-11-01",
                category="Food",
                amount=0,
                type="Expense",
                db_path=temp_db,
            )

    def test_reject_negative_amount(self, temp_db: Path):
        with pytest.raises(ValueError, match="greater than zero"):
            add_transaction(
                date="2026-11-01",
                category="Food",
                amount=-100.50,
                type="Expense",
                db_path=temp_db,
            )

    def test_reject_invalid_date(self, temp_db: Path):
        with pytest.raises(ValueError, match="Invalid calendar date"):
            add_transaction(
                date="2026-02-30",
                category="Food",
                amount=100.00,
                type="Expense",
                db_path=temp_db,
            )

    def test_reject_unknown_category(self, temp_db: Path):
        with pytest.raises(ValueError, match="Unknown category"):
            add_transaction(
                date="2026-11-01",
                category="NonExistentCategory",
                amount=100.00,
                type="Expense",
                db_path=temp_db,
            )

    def test_reject_category_type_mismatch(self, temp_db: Path):
        # 'Food' is an Expense category; cannot add it with type='Income'
        with pytest.raises(ValueError, match="Category type mismatch"):
            add_transaction(
                date="2026-11-01",
                category="Food",
                amount=100.00,
                type="Income",
                db_path=temp_db,
            )

        # 'Salary' is an Income category; cannot add it with type='Expense'
        with pytest.raises(ValueError, match="Category type mismatch"):
            add_transaction(
                date="2026-11-01",
                category="Salary",
                amount=1000.00,
                type="Expense",
                db_path=temp_db,
            )


class TestRetrieveTransactions:
    """Tests for fetching individual and collections of transactions."""

    def test_retrieve_transaction_by_id(self, temp_db: Path):
        txn_id = add_transaction(
            date="2026-11-05",
            category="Utilities",
            amount=150.00,
            description="Electric Bill",
            type="Expense",
            db_path=temp_db,
        )
        txn = get_transaction(txn_id, db_path=temp_db)
        assert txn is not None
        assert txn["id"] == txn_id
        assert txn["category"] == "Utilities"

    def test_retrieve_nonexistent_transaction(self, temp_db: Path):
        txn = get_transaction(99999, db_path=temp_db)
        assert txn is None

    def test_retrieve_all_transactions_ordered_newest_first(self, temp_db: Path):
        add_transaction(date="2026-11-01", category="Food", amount=50.0, type="Expense", db_path=temp_db)
        add_transaction(date="2026-11-05", category="Transportation", amount=30.0, type="Expense", db_path=temp_db)
        add_transaction(date="2026-11-03", category="Food", amount=80.0, type="Expense", db_path=temp_db)

        df = get_all_transactions(db_path=temp_db)
        assert len(df) == 3
        # Newest date first
        assert list(df["date"]) == ["2026-11-05", "2026-11-03", "2026-11-01"]

    def test_empty_database_retrieval(self, temp_db: Path):
        df = get_all_transactions(db_path=temp_db)
        assert isinstance(df, pd.DataFrame)
        assert df.empty
        assert "category" in df.columns
        assert "amount" in df.columns


class TestUpdateTransaction:
    """Tests for modifying existing transactions."""

    def test_update_existing_transaction(self, temp_db: Path):
        txn_id = add_transaction(
            date="2026-11-01",
            category="Food",
            amount=100.0,
            description="Initial",
            type="Expense",
            db_path=temp_db,
        )

        success = update_transaction(
            txn_id,
            amount=150.0,
            description="Updated Description",
            db_path=temp_db,
        )
        assert success is True

        txn = get_transaction(txn_id, db_path=temp_db)
        assert txn["amount"] == 150.0
        assert txn["description"] == "Updated Description"
        assert txn["category"] == "Food"  # preserved

    def test_update_nonexistent_transaction(self, temp_db: Path):
        success = update_transaction(99999, amount=50.0, db_path=temp_db)
        assert success is False

    def test_update_category_and_type_together_correctly(self, temp_db: Path):
        # Start as Expense (Food)
        txn_id = add_transaction(
            date="2026-11-01",
            category="Food",
            amount=200.0,
            type="Expense",
            db_path=temp_db,
        )

        # Update both category and type to Income (Salary)
        success = update_transaction(
            txn_id,
            category="Salary",
            type="Income",
            amount=3000.0,
            db_path=temp_db,
        )
        assert success is True

        txn = get_transaction(txn_id, db_path=temp_db)
        assert txn["category"] == "Salary"
        assert txn["type"] == "Income"
        assert txn["amount"] == 3000.0

    def test_reject_invalid_update(self, temp_db: Path):
        txn_id = add_transaction(
            date="2026-11-01",
            category="Food",
            amount=100.0,
            type="Expense",
            db_path=temp_db,
        )

        # Negative amount must fail
        with pytest.raises(ValueError, match="greater than zero"):
            update_transaction(txn_id, amount=-50.0, db_path=temp_db)

        # Invalid calendar date must fail
        with pytest.raises(ValueError, match="Invalid calendar date"):
            update_transaction(txn_id, date="2026-02-30", db_path=temp_db)

        # Type mismatch: changing type to Income without changing category Food
        with pytest.raises(ValueError, match="Category type mismatch"):
            update_transaction(txn_id, type="Income", db_path=temp_db)


class TestDeleteTransaction:
    """Tests for removing transactions."""

    def test_delete_existing_transaction(self, temp_db: Path):
        txn_id = add_transaction(
            date="2026-11-01",
            category="Food",
            amount=100.0,
            type="Expense",
            db_path=temp_db,
        )
        assert get_transaction(txn_id, db_path=temp_db) is not None

        deleted = delete_transaction(txn_id, db_path=temp_db)
        assert deleted is True
        assert get_transaction(txn_id, db_path=temp_db) is None

    def test_delete_nonexistent_transaction(self, temp_db: Path):
        deleted = delete_transaction(99999, db_path=temp_db)
        assert deleted is False


class TestFilteringAndSearch:
    """Tests for multi-criteria querying."""

    @pytest.fixture(autouse=True)
    def seed_test_data(self, temp_db: Path):
        """Populate a diverse set of transactions for filtering tests."""
        add_transaction("2026-10-15", "Food", 120.0, "Cash", "Dinner at Bistro", "Expense", db_path=temp_db)
        add_transaction("2026-11-01", "Food", 250.0, "UPI", "Team lunch", "Expense", db_path=temp_db)
        add_transaction("2026-11-05", "Transportation", 45.0, "Card", "Taxi fare", "Expense", db_path=temp_db)
        add_transaction("2026-11-10", "Salary", 40000.0, "Bank Transfer", "Monthly Paycheck", "Income", db_path=temp_db)
        add_transaction("2026-11-15", "Healthcare", 800.0, "Card", "Doctor checkup", "Expense", db_path=temp_db)
        add_transaction("2026-12-01", "Food", 300.0, "UPI", "Groceries at Supermarket", "Expense", db_path=temp_db)

    def test_filter_by_category(self, temp_db: Path):
        df = get_filtered_transactions(category="Food", db_path=temp_db)
        assert len(df) == 3
        assert all(df["category"] == "Food")

    def test_filter_by_type(self, temp_db: Path):
        income_df = get_filtered_transactions(transaction_type="Income", db_path=temp_db)
        assert len(income_df) == 1
        assert income_df.iloc[0]["category"] == "Salary"

        expense_df = get_filtered_transactions(transaction_type="Expense", db_path=temp_db)
        assert len(expense_df) == 5

    def test_filter_by_date_range(self, temp_db: Path):
        df = get_filtered_transactions(start_date="2026-11-01", end_date="2026-11-10", db_path=temp_db)
        assert len(df) == 3
        dates = list(df["date"])
        assert "2026-11-01" in dates
        assert "2026-11-05" in dates
        assert "2026-11-10" in dates

    def test_filter_by_month_and_year(self, temp_db: Path):
        df_nov = get_filtered_transactions(year=2026, month=11, db_path=temp_db)
        assert len(df_nov) == 4
        assert all(d.startswith("2026-11") for d in df_nov["date"])

    def test_filter_by_payment_method(self, temp_db: Path):
        df = get_filtered_transactions(payment_method="UPI", db_path=temp_db)
        assert len(df) == 2
        assert all(df["payment_method"] == "UPI")

    def test_search_description(self, temp_db: Path):
        df = get_filtered_transactions(search_term="lunch", db_path=temp_db)
        assert len(df) == 1
        assert "Team lunch" in df.iloc[0]["description"]

        df_checkup = get_filtered_transactions(search_term="Doctor", db_path=temp_db)
        assert len(df_checkup) == 1
        assert df_checkup.iloc[0]["category"] == "Healthcare"

    def test_combine_multiple_filters(self, temp_db: Path):
        # Category Food + Year 2026 + Month 11 + Payment UPI
        df = get_filtered_transactions(
            category="Food",
            year=2026,
            month=11,
            payment_method="UPI",
            db_path=temp_db,
        )
        assert len(df) == 1
        assert df.iloc[0]["amount"] == 250.0

    def test_calculate_income_expenses_and_net_savings(self, temp_db: Path):
        summary = get_transaction_summary(db_path=temp_db)
        # Income: 40000.0 (Salary)
        # Expenses: 120 + 250 + 45 + 800 + 300 = 1515.0
        # Net savings: 40000.0 - 1515.0 = 38485.0
        assert summary["total_income"] == 40000.0
        assert summary["total_expenses"] == 1515.0
        assert summary["net_savings"] == 38485.0
        assert summary["transaction_count"] == 6

    def test_summary_with_date_filtering(self, temp_db: Path):
        summary = get_transaction_summary(
            start_date="2026-11-01",
            end_date="2026-11-05",
            db_path=temp_db,
        )
        # Transactions in range: 250 (Food) + 45 (Trans) = 295.0
        assert summary["total_income"] == 0.0
        assert summary["total_expenses"] == 295.0
        assert summary["net_savings"] == -295.0
        assert summary["transaction_count"] == 2


class TestImportIntegration:
    """Verify imported transactions are visible through expense_manager."""

    def test_imported_transactions_retrievable_and_filterable(self, temp_db: Path, tmp_path: Path):
        csv_file = tmp_path / "sample_batch.csv"
        csv_file.write_text(
            "date,category,amount,payment_method,description,type\n"
            "2026-11-20,Food,175.0,UPI,Batch Imported Burger,Expense\n"
            "2026-11-21,Salary,45000.0,Bank Transfer,Batch Paycheck,Income\n",
            encoding="utf-8",
        )

        preview = preview_import(csv_file, db_path=temp_db)
        import_summary = import_transactions(preview, filename="sample_batch.csv", db_path=temp_db)
        assert import_summary.successful_rows == 2

        # Retrieve through expense_manager
        all_txns = get_all_transactions(db_path=temp_db)
        assert len(all_txns) >= 2

        # Filter by search_term
        found = get_filtered_transactions(search_term="Burger", db_path=temp_db)
        assert len(found) == 1
        assert found.iloc[0]["import_batch_id"] == import_summary.batch_id
        assert found.iloc[0]["amount"] == 175.0


class TestExpenseManagerClass:
    """Test the OOP wrapper ExpenseManager."""

    def test_oop_add_and_summary(self, temp_db: Path):
        mgr = ExpenseManager(temp_db)
        e_id = mgr.add_expense(amount=60.0, category="Food", date="2026-11-18", description="Coffee")
        i_id = mgr.add_income(amount=5000.0, source="Other Income", date="2026-11-18", note="Freelance")

        assert e_id > 0
        assert i_id > 0

        summary = mgr.get_summary()
        assert summary["total_income"] == 5000.0
        assert summary["total_expenses"] == 60.0
        assert summary["net_savings"] == 4940.0
        assert summary["transaction_count"] == 2

        all_txns = mgr.get_all()
        assert len(all_txns) == 2
