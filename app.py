"""
app.py — Personal Expense Tracker with Data Visualization
==========================================================
Streamlit Web Application Entry Point.

Provides a unified interface for:
  1. Dashboard — Overview KPIs & Interactive Plotly Charts
  2. Add Transaction — Validated manual income & expense entry
  3. Transactions — Filter, search, edit, and delete transactions
  4. Import CSV — Preview, validation, rejected/duplicate export, and persistence
  5. Import History — Batch logs and transaction inspection
  6. Budgets — Monthly spending targets, utilization status, and breach alerts

Run using:
  streamlit run app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root and src/ are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st

from src.database import DEFAULT_DB_PATH, initialise_database, seed_categories
from src.ui.add_transaction import render_add_transaction
from src.ui.budgets import render_budgets
from src.ui.dashboard import render_dashboard
from src.ui.import_csv import render_import_csv
from src.ui.import_history import render_import_history
from src.ui.reports import render_reports
from src.ui.transactions import render_transactions


def setup_application(db_path: Path | str | None = None) -> None:
    """Initialize database and seed categories if not already done."""
    active_db = db_path or os.environ.get("EXPENSE_TRACKER_DB") or st.session_state.get("db_path", DEFAULT_DB_PATH)
    if "db_path" not in st.session_state and os.environ.get("EXPENSE_TRACKER_DB"):
        st.session_state["db_path"] = os.environ["EXPENSE_TRACKER_DB"]
    initialise_database(active_db)
    seed_categories(active_db)


def main() -> None:
    """Streamlit Application Entry Point."""
    st.set_page_config(
        page_title="Personal Expense Tracker",
        page_icon="💰",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Initialize database
    setup_application()

    # Sidebar Navigation
    st.sidebar.title("💰 Expense Tracker")
    st.sidebar.caption("Personal Finance & Analytics")

    pages = [
        "Dashboard",
        "Add Transaction",
        "Transactions",
        "Import CSV",
        "Import History",
        "Budgets",
        "Reports",
    ]

    default_idx = 0
    query_page = st.query_params.get("page")
    if query_page and query_page in pages:
        default_idx = pages.index(query_page)
        if "nav_choice" not in st.session_state or st.session_state.get("_last_query_page") != query_page:
            st.session_state["nav_choice"] = query_page
            st.session_state["_last_query_page"] = query_page

    choice = st.sidebar.radio(
        "Navigation",
        options=pages,
        index=default_idx,
        key="nav_choice",
    )

    st.sidebar.divider()
    st.sidebar.caption("System Status: Online 🟢")

    # Route to appropriate page renderer
    if choice == "Dashboard":
        render_dashboard()
    elif choice == "Add Transaction":
        render_add_transaction()
    elif choice == "Transactions":
        render_transactions()
    elif choice == "Import CSV":
        render_import_csv()
    elif choice == "Import History":
        render_import_history()
    elif choice == "Budgets":
        render_budgets()
    elif choice == "Reports":
        render_reports()


if __name__ == "__main__":
    main()
