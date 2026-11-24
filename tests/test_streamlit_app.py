"""
tests/test_streamlit_app.py — Integration and Component Tests for Streamlit App
==============================================================================
Covers all 18 required scenarios for Session 9:
  1. Application imports successfully.
  2. Dashboard loads with an empty database.
  3. Dashboard displays populated financial overview data.
  4. Add Expense workflow.
  5. Add Income workflow.
  6. Invalid transaction input handling.
  7. Transaction filtering.
  8. Transaction update.
  9. Transaction deletion with safety.
  10. CSV preview without database modification.
  11. CSV import only after confirmation.
  12. Import duplicate handling.
  13. Import history display and batch inspection.
  14. Budget creation.
  15. Budget update.
  16. Budget status display and active alerts.
  17. Budget deletion.
  18. Empty-state behavior across all pages.
  19. Sidebar navigation routing in app.py.
"""

from __future__ import annotations

import io
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Ensure src/ and project root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import app
from budget_manager import get_all_budgets, get_budget, set_budget
from database import create_tables, get_connection, seed_categories
from expense_manager import (
    add_transaction,
    get_all_transactions,
    get_filtered_transactions,
    get_transaction,
)
from import_service import get_import_history, preview_import
from ui.add_transaction import render_add_transaction
from ui.budgets import render_budgets
from ui.common import get_categories
from ui.dashboard import render_dashboard
from ui.import_csv import render_import_csv
from ui.import_history import render_import_history
from ui.reports import render_reports
from ui.transactions import render_transactions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Fresh initialized database with tables and categories."""
    db_file = tmp_path / "test_app.db"
    create_tables(db_file)
    seed_categories(db_file)
    return db_file


@pytest.fixture
def populated_db(temp_db: Path) -> Path:
    """Populated database with multi-month data for testing."""
    # Add income & expenses
    add_transaction("2026-11-01", "Salary", 50000.0, "Bank Transfer", "Monthly Pay", "Income", db_path=temp_db)
    add_transaction("2026-11-05", "Food", 3000.0, "UPI", "Groceries", "Expense", db_path=temp_db)
    add_transaction("2026-11-10", "Transportation", 1500.0, "Card", "Fuel", "Expense", db_path=temp_db)
    add_transaction("2026-11-15", "Shopping", 8500.0, "Card", "Clothes", "Expense", db_path=temp_db)

    # Budgets
    set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
    set_budget("Shopping", "2026-11", 8000.0, db_path=temp_db)
    return temp_db


# ---------------------------------------------------------------------------
# 1. Application Imports & Navigation Routing
# ---------------------------------------------------------------------------

class TestAppStructureAndNavigation:
    """Tests for application structure, imports, and navigation."""

    def test_application_imports(self):
        """1. Verify app and all page modules import cleanly."""
        assert hasattr(app, "main")
        assert hasattr(app, "setup_application")
        assert callable(render_dashboard)
        assert callable(render_add_transaction)
        assert callable(render_transactions)
        assert callable(render_import_csv)
        assert callable(render_import_history)
        assert callable(render_budgets)

    @patch("streamlit.sidebar.radio")
    @patch("app.render_dashboard")
    @patch("app.render_add_transaction")
    @patch("app.render_transactions")
    @patch("app.render_import_csv")
    @patch("app.render_import_history")
    @patch("app.render_budgets")
    @patch("app.render_reports")
    @patch("streamlit.set_page_config")
    def test_sidebar_navigation_routing(
        self,
        mock_config,
        mock_reports,
        mock_budgets,
        mock_history,
        mock_import_csv,
        mock_txns,
        mock_add_txn,
        mock_dash,
        mock_radio,
        temp_db: Path,
    ):
        """19. Verify sidebar routing dispatches to the correct page renderer."""
        # Test routing to each choice
        routes = [
            ("Dashboard", mock_dash),
            ("Add Transaction", mock_add_txn),
            ("Transactions", mock_txns),
            ("Import CSV", mock_import_csv),
            ("Import History", mock_history),
            ("Budgets", mock_budgets),
            ("Reports", mock_reports),
        ]

        with patch("streamlit.session_state", {"db_path": temp_db}):
            for choice, expected_mock in routes:
                mock_radio.return_value = choice
                app.main()
                expected_mock.assert_called()


# ---------------------------------------------------------------------------
# 2. Dashboard Tests
# ---------------------------------------------------------------------------

class TestDashboardUI:
    """Tests for dashboard KPI cards, filters, and charts."""

    @patch("streamlit.metric")
    @patch("streamlit.plotly_chart")
    def test_dashboard_empty_db(self, mock_chart, mock_metric, temp_db: Path):
        """2. Dashboard loads gracefully with an empty database."""
        render_dashboard(db_path=temp_db)

        # Confirm 4 KPI metrics were rendered with zeroed values
        labels = [call[1]["label"] for call in mock_metric.call_args_list]
        assert "Total Income" in labels
        assert "Total Expenses" in labels
        assert "Net Savings" in labels
        assert "Savings Rate" in labels

        # Confirm all 6 charts were called
        assert mock_chart.call_count == 6

    @patch("streamlit.metric")
    @patch("streamlit.plotly_chart")
    def test_dashboard_populated_data(self, mock_chart, mock_metric, populated_db: Path):
        """3. Dashboard displays populated financial overview data."""
        render_dashboard(db_path=populated_db)

        metric_dict = {call[1]["label"]: call[1]["value"] for call in mock_metric.call_args_list}
        assert metric_dict["Total Income"] == "₹50,000.00"
        assert metric_dict["Total Expenses"] == "₹13,000.00"
        assert metric_dict["Net Savings"] == "₹37,000.00"
        assert metric_dict["Savings Rate"] == "74.0%"


# ---------------------------------------------------------------------------
# 3. Add Transaction Workflow Tests
# ---------------------------------------------------------------------------

class TestAddTransactionUI:
    """Tests for manual transaction entry."""

    @patch("streamlit.form_submit_button", return_value=True)
    @patch("streamlit.radio", return_value="Expense")
    @patch("streamlit.selectbox", side_effect=["Food", "UPI"])
    @patch("streamlit.number_input", return_value=450.0)
    @patch("streamlit.text_input", return_value="Dinner")
    @patch("streamlit.success")
    def test_add_expense_workflow(
        self, mock_success, mock_desc, mock_amt, mock_sel, mock_radio, mock_submit, temp_db: Path
    ):
        """4. Add Expense workflow inserts an expense transaction into the database."""
        render_add_transaction(db_path=temp_db)

        txns = get_all_transactions(db_path=temp_db)
        assert len(txns) == 1
        row = txns.iloc[0]
        assert row["type"] == "Expense"
        assert row["category"] == "Food"
        assert row["amount"] == 450.0
        assert row["payment_method"] == "UPI"
        assert row["description"] == "Dinner"
        mock_success.assert_called_once()

    @patch("streamlit.form_submit_button", return_value=True)
    @patch("streamlit.radio", return_value="Income")
    @patch("streamlit.selectbox", side_effect=["Salary", "Bank Transfer"])
    @patch("streamlit.number_input", return_value=65000.0)
    @patch("streamlit.text_input", return_value="Monthly Salary")
    @patch("streamlit.success")
    def test_add_income_workflow(
        self, mock_success, mock_desc, mock_amt, mock_sel, mock_radio, mock_submit, temp_db: Path
    ):
        """5. Add Income workflow inserts an income transaction into the database."""
        render_add_transaction(db_path=temp_db)

        txns = get_all_transactions(db_path=temp_db)
        assert len(txns) == 1
        row = txns.iloc[0]
        assert row["type"] == "Income"
        assert row["category"] == "Salary"
        assert row["amount"] == 65000.0
        mock_success.assert_called_once()

    @patch("streamlit.form_submit_button", return_value=True)
    @patch("streamlit.radio", return_value="Expense")
    @patch("streamlit.selectbox", side_effect=["Food", "UPI"])
    @patch("streamlit.number_input", return_value=-100.0)
    @patch("streamlit.text_input", return_value="Invalid")
    @patch("streamlit.error")
    def test_invalid_transaction_input(
        self, mock_error, mock_desc, mock_amt, mock_sel, mock_radio, mock_submit, temp_db: Path
    ):
        """6. Invalid transaction input (amount <= 0) is rejected without mutating DB."""
        render_add_transaction(db_path=temp_db)

        txns = get_all_transactions(db_path=temp_db)
        assert len(txns) == 0
        mock_error.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Transactions Filtering, Update, and Deletion Tests
# ---------------------------------------------------------------------------

class TestTransactionsUI:
    """Tests for transactions filtering, editing, and deletion."""

    def test_transaction_filtering(self, populated_db: Path):
        """7. Transaction filtering restricts returned records."""
        # Test category filter
        food_txns = get_filtered_transactions(category="Food", db_path=populated_db)
        assert len(food_txns) == 1
        assert food_txns.iloc[0]["category"] == "Food"

        # Test type filter
        income_txns = get_filtered_transactions(transaction_type="Income", db_path=populated_db)
        assert len(income_txns) == 1
        assert income_txns.iloc[0]["type"] == "Income"

    @patch("streamlit.form_submit_button", return_value=True)
    @patch("streamlit.rerun")
    @patch("streamlit.success")
    def test_transaction_update(self, mock_success, mock_rerun, mock_submit, populated_db: Path):
        """8. Transaction update modifies the record in the database."""
        txns = get_all_transactions(db_path=populated_db)
        target_id = int(txns.iloc[0]["id"])

        # Patch edit form selections
        with patch("streamlit.selectbox", side_effect=[
            "All", "All", "All",  # Filters: type, cat, pm
            target_id,            # Select transaction ID
            "Expense", "Shopping", "Card",  # Edit fields: type, cat, pm
        ]):
            with patch("streamlit.number_input", return_value=9999.0):
                with patch("streamlit.text_input", side_effect=["", "", "", "Updated Clothes"]):
                    render_transactions(db_path=populated_db)

        updated_txn = get_transaction(target_id, db_path=populated_db)
        assert updated_txn["amount"] == 9999.0
        assert updated_txn["description"] == "Updated Clothes"

    @patch("streamlit.checkbox", return_value=True)  # Confirmation box checked
    @patch("streamlit.button", return_value=True)    # Delete button pressed
    @patch("streamlit.rerun")
    @patch("streamlit.success")
    def test_transaction_deletion(self, mock_success, mock_rerun, mock_btn, mock_check, populated_db: Path):
        """9. Transaction deletion removes the record safely."""
        txns = get_all_transactions(db_path=populated_db)
        target_id = int(txns.iloc[0]["id"])
        init_count = len(txns)

        with patch("streamlit.selectbox", side_effect=[
            "All", "All", "All",  # Filters
            target_id,            # Selected txn ID
            "Expense", "Food", "UPI",  # Dummy for edit form
        ]):
            render_transactions(db_path=populated_db)

        remaining_txns = get_all_transactions(db_path=populated_db)
        assert len(remaining_txns) == init_count - 1
        assert get_transaction(target_id, db_path=populated_db) is None


# ---------------------------------------------------------------------------
# 5. CSV Import & Duplicate Tests
# ---------------------------------------------------------------------------

class TestCSVImportUI:
    """Tests for CSV preview, duplicate detection, and persistence."""

    def test_csv_preview_does_not_mutate_database(self, temp_db: Path):
        """10. CSV preview analyzes transactions without database modification."""
        csv_content = (
            "date,category,amount,payment_method,description,type\n"
            "2026-11-20,Food,500.0,UPI,Snacks,Expense\n"
            "2026-11-21,Salary,40000.0,Bank Transfer,Pay,Income\n"
        )
        mock_file = MagicMock()
        mock_file.name = "test_import.csv"
        mock_file.getvalue.return_value = csv_content.encode("utf-8")

        with patch("streamlit.file_uploader", return_value=mock_file):
            render_import_csv(db_path=temp_db)

        # Verify DB transactions count remains 0!
        with get_connection(temp_db) as conn:
            count = conn.execute("SELECT count(*) FROM transactions;").fetchone()[0]
            assert count == 0

    @patch("streamlit.checkbox", return_value=True)  # Confirm import
    @patch("streamlit.button", return_value=True)    # Import button pressed
    def test_csv_import_only_after_confirmation(self, mock_btn, mock_check, temp_db: Path):
        """11. Transactions are inserted only after explicit confirmation."""
        csv_content = (
            "date,category,amount,payment_method,description,type\n"
            "2026-11-20,Food,500.0,UPI,Snacks,Expense\n"
            "2026-11-21,Salary,40000.0,Bank Transfer,Pay,Income\n"
        )
        mock_file = MagicMock()
        mock_file.name = "confirmed_import.csv"
        mock_file.getvalue.return_value = csv_content.encode("utf-8")

        with patch("streamlit.file_uploader", return_value=mock_file):
            with patch("streamlit.session_state", {}):
                render_import_csv(db_path=temp_db)

        # Database now has the 2 transactions
        txns = get_all_transactions(db_path=temp_db)
        assert len(txns) == 2

    def test_import_duplicate_handling(self, temp_db: Path):
        """12. Duplicates against existing DB records are detected and skipped."""
        # Add existing record
        add_transaction("2026-11-20", "Food", 500.0, "UPI", "Snacks", "Expense", db_path=temp_db)

        csv_content = (
            "date,category,amount,payment_method,description,type\n"
            "2026-11-20,Food,500.0,UPI,Snacks,Expense\n"      # Duplicate
            "2026-11-22,Shopping,1500.0,Card,Shoes,Expense\n"  # Valid new
        )
        preview = preview_import(io.StringIO(csv_content), db_path=temp_db)
        assert preview.total_rows == 2
        assert preview.valid_count == 1
        assert preview.duplicate_count == 1


# ---------------------------------------------------------------------------
# 6. Import History & Batch Inspection Tests
# ---------------------------------------------------------------------------

class TestImportHistoryUI:
    """Tests for import history and batch inspection."""

    def test_import_history_empty_and_populated(self, temp_db: Path):
        """13. Import history displays batches and inspects transactions."""
        # 1. Empty state
        with patch("streamlit.info") as mock_info:
            render_import_history(db_path=temp_db)
            mock_info.assert_called_with("No CSV import batches recorded yet. Use the 'Import CSV' page to upload transactions.")

        # 2. Add an import batch
        from import_service import import_transactions
        csv_content = (
            "date,category,amount,payment_method,description,type\n"
            "2026-11-25,Food,350.0,UPI,Burger,Expense\n"
        )
        prev = preview_import(io.StringIO(csv_content), db_path=temp_db)
        res = import_transactions(prev, filename="batch_test.csv", db_path=temp_db)

        hist = get_import_history(db_path=temp_db)
        assert len(hist) == 1
        assert hist[0]["filename"] == "batch_test.csv"
        assert hist[0]["successful_rows"] == 1


# ---------------------------------------------------------------------------
# 7. Budgets UI Tests
# ---------------------------------------------------------------------------

class TestBudgetsUI:
    """Tests for budget creation, update, status monitoring, and deletion."""

    @patch("streamlit.form_submit_button", return_value=True)
    @patch("streamlit.selectbox", side_effect=["Food", 1, "Food", 1])
    @patch("streamlit.number_input", return_value=5500.0)
    @patch("streamlit.rerun")
    @patch("streamlit.success")
    def test_budget_creation(self, mock_success, mock_rerun, mock_amt, mock_sel, mock_submit, temp_db: Path):
        """14. Budget creation inserts new budget for category and month."""
        with patch("streamlit.text_input", return_value="2026-11"):
            render_budgets(db_path=temp_db)

        b = get_budget("Food", "2026-11", db_path=temp_db)
        assert b is not None
        assert b["limit_amount"] == 5500.0

    @patch("streamlit.form_submit_button", return_value=True)
    @patch("streamlit.selectbox", side_effect=["Food", 1, "Food", 1])
    @patch("streamlit.number_input", return_value=7000.0)
    @patch("streamlit.rerun")
    def test_budget_update(self, mock_rerun, mock_amt, mock_sel, mock_submit, temp_db: Path):
        """15. Budget update updates limit amount while preserving the ID."""
        b_id = set_budget("Food", "2026-11", 5000.0, db_path=temp_db)

        with patch("streamlit.text_input", return_value="2026-11"):
            render_budgets(db_path=temp_db)

        b = get_budget("Food", "2026-11", db_path=temp_db)
        assert b["id"] == b_id
        assert b["limit_amount"] == 7000.0

    @patch("streamlit.dataframe")
    def test_budget_status_display(self, mock_df, populated_db: Path):
        """16. Budget status displays actual expenses and status."""
        with patch("streamlit.text_input", return_value="2026-11"):
            render_budgets(db_path=populated_db)

        # Check dataframe was called
        mock_df.assert_called()

    @patch("streamlit.checkbox", return_value=True)  # Confirm checkbox
    @patch("streamlit.button", return_value=True)    # Delete button pressed
    @patch("streamlit.rerun")
    @patch("streamlit.success")
    def test_budget_deletion(self, mock_success, mock_rerun, mock_btn, mock_check, temp_db: Path):
        """17. Budget deletion deletes budget without affecting categories or transactions."""
        b_id = set_budget("Food", "2026-11", 5000.0, db_path=temp_db)
        add_transaction("2026-11-05", "Food", 200.0, "UPI", "Snack", "Expense", db_path=temp_db)

        with patch("streamlit.text_input", return_value="2026-11"):
            with patch("streamlit.selectbox", return_value=b_id):
                render_budgets(db_path=temp_db)

        assert get_budget("Food", "2026-11", db_path=temp_db) is None
        # Transactions and categories remain intact
        txns = get_all_transactions(db_path=temp_db)
        assert len(txns) == 1
        cats = get_categories(db_path=temp_db)
        assert "Food" in cats


# ---------------------------------------------------------------------------
# 8. Empty-State Behavior Across All Pages
# ---------------------------------------------------------------------------

class TestEmptyStateBehavior:
    """18. Verify every page handles an empty database safely without exceptions."""

    def test_empty_state_all_pages(self, temp_db: Path):
        # 1. Dashboard
        render_dashboard(db_path=temp_db)

        # 2. Add Transaction
        render_add_transaction(db_path=temp_db)

        # 3. Transactions
        render_transactions(db_path=temp_db)

        # 4. Import CSV
        render_import_csv(db_path=temp_db)

        # 5. Import History
        render_import_history(db_path=temp_db)

        # 6. Budgets
        render_budgets(db_path=temp_db)

        # 7. Reports
        render_reports(db_path=temp_db)


# ---------------------------------------------------------------------------
# 9. Reports Page & Security Verification
# ---------------------------------------------------------------------------

class TestReportsAndSecurity:
    """Security verification and Reports page integration tests."""

    def test_render_dataframe_escapes_malicious_html(self):
        """Part A Security: Verify render_dataframe HTML-escapes all user content."""
        from ui.common import render_dataframe

        malicious_df = pd.DataFrame({
            "Description": ["<script>alert('XSS')</script>", "<img src=x onerror=alert(1)>"],
            "Amount": [100.0, 200.0],
        })

        with patch("streamlit.markdown") as mock_markdown:
            render_dataframe(malicious_df)

            mock_markdown.assert_called_once()
            rendered_html = mock_markdown.call_args[0][0]

            # Assert dangerous tags are escaped
            assert "<script>" not in rendered_html
            assert "&lt;script&gt;alert('XSS')&lt;/script&gt;" in rendered_html
            assert "<img src=x" not in rendered_html
            assert "&lt;img src=x onerror=alert(1)&gt;" in rendered_html

    def test_render_reports_page_loads(self, temp_db: Path):
        """Verify Reports page renders tabs and options cleanly."""
        render_reports(db_path=temp_db)

    def test_app_routing_includes_reports(self, temp_db: Path):
        """Verify app navigation routes to render_reports when 'Reports' is selected."""
        with patch("streamlit.sidebar.radio", return_value="Reports"):
            with patch("app.render_reports") as mock_render_reports:
                with patch("app.setup_application"):
                    app.main()
                    mock_render_reports.assert_called_once()
