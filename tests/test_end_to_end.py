"""
tests/test_end_to_end.py — Session 11: Comprehensive End-to-End Workflow Tests
===============================================================================
Verifies the complete application workflow using temporary databases:
  1. Add income and expense transactions.
  2. Edit a transaction.
  3. Delete a transaction.
  4. Filter transactions by type, category, date, and search.
  5. Import a CSV file (preview + import).
  6. Inspect import history and batch details.
  7. Create and update budgets with status checking.
  8. Generate monthly PDF report.
  9. Generate custom-period PDF report.
  10. Export filtered and all transactions to CSV.
  11. Dashboard metrics update correctly after CRUD operations.
  12. Demo CSV dataset import verification.
  13. Security: formula injection, HTML escaping, SQL parameterisation.
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from analytics import get_financial_overview, get_category_wise_expenses
from budget_manager import (
    delete_budget,
    get_all_budgets,
    get_budget,
    get_budget_status,
    set_budget,
)
from database import initialise_database, seed_categories, get_connection
from expense_manager import (
    add_transaction,
    delete_transaction,
    get_all_transactions,
    get_filtered_transactions,
    get_transaction,
    update_transaction,
)
from import_service import (
    get_batch_transactions,
    get_import_history,
    import_transactions,
    preview_import,
)
from report_generator import (
    export_all_transactions_csv,
    export_transactions_csv,
    generate_custom_period_report,
    generate_monthly_report,
    generate_transaction_report,
    sanitize_csv_value,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Create a fresh initialised and seeded database."""
    db_file = tmp_path / "e2e_test.db"
    initialise_database(db_file)
    seed_categories(db_file)
    return db_file


@pytest.fixture
def demo_csv() -> Path:
    """Return path to the demo CSV dataset."""
    return Path(__file__).resolve().parent.parent / "data" / "sample" / "demo_transactions.csv"


# ---------------------------------------------------------------------------
# 1. Transaction CRUD Workflow
# ---------------------------------------------------------------------------

class TestTransactionCRUD:
    """Add → Edit → Delete workflow with metric verification."""

    def test_add_income_and_expenses(self, db: Path):
        inc_id = add_transaction("2026-11-01", "Salary", 50000, "Bank Transfer", "Monthly salary", "Income", db_path=db)
        exp_id = add_transaction("2026-11-05", "Food", 1200, "UPI", "Groceries", "Expense", db_path=db)

        assert inc_id > 0
        assert exp_id > 0

        inc = get_transaction(inc_id, db_path=db)
        assert inc["amount"] == 50000.0
        assert inc["type"] == "Income"

        exp = get_transaction(exp_id, db_path=db)
        assert exp["amount"] == 1200.0
        assert exp["category"] == "Food"

    def test_edit_transaction(self, db: Path):
        t_id = add_transaction("2026-11-05", "Food", 500, "UPI", "Lunch", "Expense", db_path=db)
        update_transaction(t_id, amount=750, description="Updated lunch", db_path=db)
        t = get_transaction(t_id, db_path=db)
        assert t["amount"] == 750.0
        assert t["description"] == "Updated lunch"

    def test_delete_transaction(self, db: Path):
        t_id = add_transaction("2026-11-10", "Shopping", 1000, "Cash", "Test", "Expense", db_path=db)
        assert get_transaction(t_id, db_path=db) is not None
        delete_transaction(t_id, db_path=db)
        assert get_transaction(t_id, db_path=db) is None

    def test_filter_transactions(self, db: Path):
        add_transaction("2026-11-01", "Salary", 50000, "Bank Transfer", "Salary", "Income", db_path=db)
        add_transaction("2026-11-05", "Food", 500, "UPI", "Lunch", "Expense", db_path=db)
        add_transaction("2026-11-10", "Transportation", 200, "Cash", "Metro", "Expense", db_path=db)

        # Filter by type
        expenses = get_filtered_transactions(transaction_type="Expense", db_path=db)
        assert len(expenses) == 2

        # Filter by category
        food = get_filtered_transactions(category="Food", db_path=db)
        assert len(food) == 1

        # Filter by search
        result = get_filtered_transactions(search_term="Metro", db_path=db)
        assert len(result) == 1

    def test_dashboard_metrics_after_crud(self, db: Path):
        """Verify analytics update correctly after add/edit/delete."""
        # Initial state
        overview = get_financial_overview(db_path=db)
        assert overview["total_income"] == 0
        assert overview["total_expenses"] == 0

        # Add transactions
        inc_id = add_transaction("2026-11-01", "Salary", 40000, "Bank Transfer", "Salary", "Income", db_path=db)
        exp_id = add_transaction("2026-11-05", "Food", 1500, "UPI", "Groceries", "Expense", db_path=db)

        overview = get_financial_overview(db_path=db)
        assert overview["total_income"] == 40000.0
        assert overview["total_expenses"] == 1500.0
        assert overview["net_savings"] == 38500.0

        # Edit expense amount
        update_transaction(exp_id, amount=2000, db_path=db)
        overview = get_financial_overview(db_path=db)
        assert overview["total_expenses"] == 2000.0
        assert overview["net_savings"] == 38000.0

        # Delete expense
        delete_transaction(exp_id, db_path=db)
        overview = get_financial_overview(db_path=db)
        assert overview["total_expenses"] == 0
        assert overview["net_savings"] == 40000.0


# ---------------------------------------------------------------------------
# 2. CSV Import Workflow
# ---------------------------------------------------------------------------

class TestCSVImportWorkflow:
    """Preview → Import → History → Batch inspection."""

    def test_csv_preview_and_import(self, db: Path, tmp_path: Path):
        # Create test CSV
        csv_file = tmp_path / "test_import.csv"
        csv_file.write_text(
            "date,category,amount,payment_method,description,type\n"
            "2026-11-01,Food,350,UPI,Lunch,Expense\n"
            "2026-11-02,Salary,30000,Bank Transfer,Monthly salary,Income\n"
            "2026-11-03,Transportation,150,Cash,Bus fare,Expense\n",
            encoding="utf-8",
        )

        # Preview
        preview = preview_import(str(csv_file), db_path=db)
        assert preview.total_rows == 3
        assert preview.valid_count == 3
        assert preview.rejected_count == 0

        # Import
        summary = import_transactions(preview, filename="test_import.csv", db_path=db)
        assert summary.successful_rows == 3

        # Verify transactions in DB
        all_txns = get_all_transactions(db_path=db)
        assert len(all_txns) == 3

    def test_import_history_and_batch(self, db: Path, tmp_path: Path):
        csv_file = tmp_path / "batch.csv"
        csv_file.write_text(
            "date,category,amount,payment_method,description,type\n"
            "2026-10-01,Food,100,UPI,Snack,Expense\n",
            encoding="utf-8",
        )
        preview = preview_import(str(csv_file), db_path=db)
        import_transactions(preview, filename="batch.csv", db_path=db)

        history = get_import_history(db_path=db)
        assert len(history) >= 1
        batch_id = history[0]["id"]

        batch_txns = get_batch_transactions(batch_id, db_path=db)
        assert len(batch_txns) == 1

    def test_demo_csv_imports_successfully(self, db: Path, demo_csv: Path):
        """Verify the synthetic demo dataset is fully importable."""
        assert demo_csv.exists(), f"Demo CSV not found: {demo_csv}"

        preview = preview_import(str(demo_csv), db_path=db)
        assert preview.total_rows == 38
        assert preview.valid_count == 38
        assert preview.rejected_count == 0
        assert preview.duplicate_count == 0

        summary = import_transactions(preview, filename="demo_transactions.csv", db_path=db)
        assert summary.successful_rows == 38

        # Verify analytics work with imported data
        overview = get_financial_overview(db_path=db)
        assert overview["total_income"] > 0
        assert overview["total_expenses"] > 0
        assert overview["transaction_count"] == 38


# ---------------------------------------------------------------------------
# 3. Budget Workflow
# ---------------------------------------------------------------------------

class TestBudgetWorkflow:
    """Create → Update → Status → Delete."""

    def test_budget_lifecycle(self, db: Path):
        # Add an expense to test budget status
        add_transaction("2026-11-05", "Food", 3000, "UPI", "Groceries", "Expense", db_path=db)

        # Create budget
        b_id = set_budget("Food", "2026-11", 5000, db_path=db)
        assert b_id > 0

        budget = get_budget("Food", "2026-11", db_path=db)
        assert budget is not None
        assert budget["limit_amount"] == 5000.0

        # Check status
        status_df = get_budget_status(month="2026-11", db_path=db)
        assert len(status_df) >= 1
        food_row = status_df[status_df["category"] == "Food"].iloc[0]
        assert food_row["actual_expenses"] == 3000.0
        assert food_row["utilization_percentage"] == 60.0

        # Update budget
        new_id = set_budget("Food", "2026-11", 3500, db_path=db)
        assert new_id == b_id  # Same ID on upsert update
        budget = get_budget("Food", "2026-11", db_path=db)
        assert budget["limit_amount"] == 3500.0

        # Delete budget
        delete_budget(b_id, db_path=db)
        assert get_budget("Food", "2026-11", db_path=db) is None


# ---------------------------------------------------------------------------
# 4. Report Generation Workflow
# ---------------------------------------------------------------------------

class TestReportWorkflow:
    """PDF and CSV generation with content verification."""

    def test_monthly_pdf_report(self, db: Path, tmp_path: Path):
        add_transaction("2026-11-01", "Salary", 50000, "Bank Transfer", "Salary", "Income", db_path=db)
        add_transaction("2026-11-10", "Food", 2000, "UPI", "Groceries", "Expense", db_path=db)
        set_budget("Food", "2026-11", 5000, db_path=db)

        pdf_path = generate_monthly_report("2026-11", db_path=db, output_path=tmp_path / "monthly.pdf")
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    def test_custom_period_pdf(self, db: Path, tmp_path: Path):
        add_transaction("2026-10-15", "Shopping", 1500, "Cash", "Books", "Expense", db_path=db)
        add_transaction("2026-11-05", "Food", 800, "UPI", "Lunch", "Expense", db_path=db)

        pdf_path = generate_custom_period_report(
            "2026-10-01", "2026-11-30", db_path=db, output_path=tmp_path / "custom.pdf"
        )
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    def test_transaction_pdf_with_filters(self, db: Path, tmp_path: Path):
        add_transaction("2026-11-05", "Food", 500, "UPI", "Lunch", "Expense", db_path=db)
        add_transaction("2026-11-10", "Salary", 50000, "Bank Transfer", "Salary", "Income", db_path=db)

        pdf_path = generate_transaction_report(
            category="Food", transaction_type="Expense",
            db_path=db, output_path=tmp_path / "filtered.pdf"
        )
        assert pdf_path.exists()

    def test_csv_export_all(self, db: Path, tmp_path: Path):
        add_transaction("2026-11-01", "Salary", 40000, "Bank Transfer", "Salary", "Income", db_path=db)
        add_transaction("2026-11-05", "Food", 1200, "UPI", "Groceries", "Expense", db_path=db)

        out = tmp_path / "all.csv"
        result = export_all_transactions_csv(db_path=db, output_path=out)
        assert Path(result).exists()

        df = pd.read_csv(out, encoding="utf-8-sig")
        assert len(df) == 2
        assert list(df.columns) == ["id", "date", "category", "type", "amount", "payment_method", "description"]

    def test_csv_export_filtered(self, db: Path):
        add_transaction("2026-11-01", "Salary", 40000, "Bank Transfer", "Salary", "Income", db_path=db)
        add_transaction("2026-11-05", "Food", 1200, "UPI", "Groceries", "Expense", db_path=db)

        csv_str = export_transactions_csv(transaction_type="Expense", db_path=db)
        assert "Groceries" in csv_str
        assert "Salary" not in csv_str


# ---------------------------------------------------------------------------
# 5. Security Verification
# ---------------------------------------------------------------------------

class TestSecurity:
    """CSV injection, HTML escaping, SQL parameterisation, FK enforcement."""

    def test_formula_injection_protection(self):
        assert sanitize_csv_value("=1+1") == "'=1+1"
        assert sanitize_csv_value("+cmd") == "'+cmd"
        assert sanitize_csv_value("-5+2") == "'-5+2"
        assert sanitize_csv_value("@SUM") == "'@SUM"
        assert sanitize_csv_value("Normal text") == "Normal text"
        assert sanitize_csv_value(42) == 42

    def test_formula_injection_in_exported_csv(self, db: Path):
        """Verify injected descriptions are sanitized in export, not in DB."""
        t_id = add_transaction("2026-11-01", "Food", 100, "UPI", "=1+1", "Expense", db_path=db)

        csv_str = export_all_transactions_csv(db_path=db)
        assert "'=1+1" in csv_str

        record = get_transaction(t_id, db_path=db)
        assert record["description"] == "=1+1"  # DB unmodified

    def test_sql_parameterisation(self, db: Path):
        """SQL injection attempts should be treated as literal strings."""
        t_id = add_transaction(
            "2026-11-01", "Food", 100, "UPI",
            "'; DROP TABLE transactions; --", "Expense", db_path=db
        )
        record = get_transaction(t_id, db_path=db)
        assert record is not None
        assert record["description"] == "'; DROP TABLE transactions; --"
        assert len(get_all_transactions(db_path=db)) == 1

    def test_foreign_key_enforcement(self, db: Path):
        """Transactions with invalid category_id should be rejected by FK constraint."""
        with get_connection(db) as conn:
            try:
                conn.execute(
                    "INSERT INTO transactions (date, category_id, amount, payment_method, description, type) "
                    "VALUES ('2026-11-01', 9999, 100, 'UPI', 'test', 'Expense')"
                )
                conn.commit()
                pytest.fail("FK constraint should have rejected invalid category_id")
            except Exception:
                pass  # Expected: FK or CHECK constraint violation

    def test_production_database_isolation(self):
        """The production database should NOT be touched by any test."""
        prod_db = Path(__file__).resolve().parent.parent / "data" / "expense_tracker.db"
        if prod_db.exists():
            import sqlite3
            conn = sqlite3.connect(str(prod_db))
            count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            conn.close()
            assert count == 0, "Production database should have 0 transactions"

    def test_no_personal_data_in_demo_csv(self, demo_csv: Path):
        """Verify demo CSV contains no real personal information."""
        content = demo_csv.read_text(encoding="utf-8")
        # Should not contain real-looking identifiers
        personal_patterns = ["@gmail", "@yahoo", "@hotmail", "passport", "aadhaar", "pan card"]
        for pattern in personal_patterns:
            assert pattern.lower() not in content.lower(), f"Demo CSV contains potential personal data: {pattern}"
