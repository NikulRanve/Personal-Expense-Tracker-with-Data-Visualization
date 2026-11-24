"""
src/ui/add_transaction.py — Manual Transaction Entry Page
==========================================================
Provides a validated form for adding Expense or Income transactions.
Calls src.expense_manager.add_transaction exclusively.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional, Union

import streamlit as st

from src.expense_manager import add_transaction
from src.ui.common import PAYMENT_METHODS, format_inr, get_active_db_path, get_categories


def render_add_transaction(db_path: Optional[Union[Path, str]] = None) -> None:
    """Render the Add Transaction form."""
    active_path = db_path or get_active_db_path()

    st.title("➕ Add Transaction")
    st.markdown("Record a new income or expense transaction with strict validation.")

    # 1. Type selector outside form so categories update reactively
    trans_type = st.radio(
        "Transaction Type",
        options=["Expense", "Income"],
        horizontal=True,
        key="add_trans_type",
    )

    categories = get_categories(trans_type=trans_type, db_path=active_path)
    if not categories:
        st.warning(f"No {trans_type} categories found in the database.")
        return

    # 2. Form for transaction details
    with st.form("add_transaction_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            date_val = st.date_input("Date", value=datetime.date.today())
            category_val = st.selectbox("Category", options=categories)
            amount_val = st.number_input(
                "Amount (₹)",
                min_value=0.01,
                value=100.0,
                step=10.0,
                format="%.2f",
            )

        with col2:
            payment_method_val = st.selectbox("Payment Method", options=PAYMENT_METHODS)
            description_val = st.text_input("Description (Optional)", placeholder="e.g. Grocery shopping, Salary")

        submitted = st.form_submit_button("💾 Save Transaction", use_container_width=True)

        if submitted:
            date_str = date_val.strftime("%Y-%m-%d")
            try:
                txn_id = add_transaction(
                    date=date_str,
                    category=category_val,
                    amount=amount_val,
                    payment_method=payment_method_val,
                    description=description_val,
                    type=trans_type,
                    db_path=active_path,
                )
                st.success(
                    f"✅ Transaction #{txn_id} added successfully: "
                    f"{trans_type} of {format_inr(amount_val)} under '{category_val}' on {date_str}."
                )
            except ValueError as exc:
                st.error(f"❌ Validation Error: {exc}")
            except Exception as exc:
                st.error(f"❌ Failed to record transaction: {exc}")
