"""
src/ui/transactions.py — Transactions Management Page
======================================================
View, filter, search, edit, and delete transactions.
Consumes src.expense_manager functions directly.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional, Union

import streamlit as st

from src.expense_manager import (
    delete_transaction,
    get_filtered_transactions,
    get_transaction,
    update_transaction,
)
from src.ui.common import (
    PAYMENT_METHODS,
    format_inr,
    get_active_db_path,
    get_categories,
    render_dataframe,
)


def render_transactions(db_path: Optional[Union[Path, str]] = None) -> None:
    """Render the Transactions table with filtering, editing, and deletion."""
    active_path = db_path or get_active_db_path()

    st.title("📋 Transactions")
    st.markdown("Inspect, search, update, or remove recorded transactions.")

    # -----------------------------------------------------------------------
    # Filters
    # -----------------------------------------------------------------------
    all_categories = ["All"] + get_categories(db_path=active_path)

    with st.expander("🔍 Filter & Search Transactions", expanded=True):
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        with f_col1:
            type_filter = st.selectbox("Type", options=["All", "Expense", "Income"], key="filter_type")
            cat_filter = st.selectbox("Category", options=all_categories, key="filter_category")
        with f_col2:
            pm_filter = st.selectbox("Payment Method", options=["All"] + PAYMENT_METHODS, key="filter_pm")
            search_query = st.text_input("Search Description", key="filter_search")
        with f_col3:
            use_dates = st.checkbox("Filter by Date Range", value=False, key="filter_use_dates")
            start_d = st.date_input("Start Date", value=datetime.date.today().replace(day=1), disabled=not use_dates)
            end_d = st.date_input("End Date", value=datetime.date.today(), disabled=not use_dates)
        with f_col4:
            month_input = st.text_input("Month (YYYY-MM)", placeholder="e.g. 2026-11", key="filter_month")
            year_input = st.text_input("Year (YYYY)", placeholder="e.g. 2026", key="filter_year")

    # Format arguments for get_filtered_transactions
    s_date = start_d.strftime("%Y-%m-%d") if use_dates else None
    e_date = end_d.strftime("%Y-%m-%d") if use_dates else None
    cat_arg = cat_filter if cat_filter != "All" else None
    type_arg = type_filter if type_filter != "All" else None
    pm_arg = pm_filter if pm_filter != "All" else None
    search_arg = search_query.strip() if search_query.strip() else None
    month_arg = month_input.strip() if month_input.strip() else None
    year_arg = int(year_input.strip()) if year_input.strip().isdigit() else None

    # Fetch transactions
    try:
        df = get_filtered_transactions(
            start_date=s_date,
            end_date=e_date,
            category=cat_arg,
            transaction_type=type_arg,
            payment_method=pm_arg,
            search_term=search_arg,
            year=year_arg,
            month=month_arg,
            db_path=active_path,
        )
    except Exception as exc:
        st.error(f"Error loading transactions: {exc}")
        return

    # Table View
    st.subheader(f"Results ({len(df)} transactions)")

    if df.empty:
        st.info("No transactions match the selected filters.")
        return

    # Display clean table
    display_df = df.copy()
    display_df["amount"] = display_df["amount"].apply(format_inr)
    render_dataframe(
        display_df[["id", "date", "category", "amount", "payment_method", "description", "type"]],
        hide_index=True,
    )

    st.divider()

    # -----------------------------------------------------------------------
    # Edit / Delete Section
    # -----------------------------------------------------------------------
    st.subheader("✏️ Manage Selected Transaction")

    txn_ids = list(df["id"])
    selected_id = st.selectbox("Select Transaction ID", options=txn_ids, key="selected_txn_id")

    if selected_id:
        current_txn = get_transaction(selected_id, db_path=active_path)
        if not current_txn:
            st.warning(f"Transaction #{selected_id} not found.")
            return

        tab_edit, tab_delete = st.tabs(["Edit Transaction", "Delete Transaction"])

        # Edit Tab
        with tab_edit:
            with st.form(f"edit_form_{selected_id}"):
                c1, c2 = st.columns(2)
                with c1:
                    edit_type = st.selectbox(
                        "Type",
                        options=["Expense", "Income"],
                        index=0 if current_txn["type"] == "Expense" else 1,
                    )
                    avail_cats = get_categories(trans_type=edit_type, db_path=active_path)
                    cur_cat_idx = (
                        avail_cats.index(current_txn["category"])
                        if current_txn["category"] in avail_cats
                        else 0
                    )
                    edit_category = st.selectbox("Category", options=avail_cats, index=cur_cat_idx)
                    edit_amount = st.number_input(
                        "Amount (₹)",
                        min_value=0.01,
                        value=float(current_txn["amount"]),
                        step=10.0,
                        format="%.2f",
                    )
                with c2:
                    curr_d = datetime.date.fromisoformat(current_txn["date"])
                    edit_date = st.date_input("Date", value=curr_d)
                    pm_opts = PAYMENT_METHODS
                    pm_idx = pm_opts.index(current_txn["payment_method"]) if current_txn["payment_method"] in pm_opts else 0
                    edit_pm = st.selectbox("Payment Method", options=pm_opts, index=pm_idx)
                    edit_desc = st.text_input("Description", value=current_txn["description"] or "")

                save_btn = st.form_submit_button("Update Transaction", use_container_width=True)

                if save_btn:
                    try:
                        updated = update_transaction(
                            transaction_id=selected_id,
                            date=edit_date.strftime("%Y-%m-%d"),
                            category=edit_category,
                            amount=edit_amount,
                            payment_method=edit_pm,
                            description=edit_desc,
                            type=edit_type,
                            db_path=active_path,
                        )
                        if updated:
                            st.success(f"✅ Transaction #{selected_id} updated successfully!")
                            st.rerun()
                        else:
                            st.error("Failed to update transaction.")
                    except Exception as exc:
                        st.error(f"❌ Update Error: {exc}")

        # Delete Tab
        with tab_delete:
            st.warning(
                f"Are you sure you want to delete transaction **#{selected_id}** "
                f"({current_txn['type']} of {format_inr(current_txn['amount'])} on {current_txn['date']})?"
            )
            confirm_delete = st.checkbox(
                f"Yes, permanently delete transaction #{selected_id}",
                key=f"confirm_del_{selected_id}",
            )
            if st.button("🗑️ Delete Transaction", disabled=not confirm_delete, type="primary"):
                try:
                    success = delete_transaction(selected_id, db_path=active_path)
                    if success:
                        st.success(f"Transaction #{selected_id} has been permanently deleted.")
                        st.rerun()
                    else:
                        st.error("Transaction could not be found.")
                except Exception as exc:
                    st.error(f"❌ Deletion failed: {exc}")
