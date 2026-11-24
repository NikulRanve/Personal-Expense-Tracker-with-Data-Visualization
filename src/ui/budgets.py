"""
src/ui/budgets.py — Budget Management Page
===========================================
Create, update, monitor, and delete monthly category budgets and alerts.
Consumes src.budget_manager functions exclusively.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional, Union

import streamlit as st

from src.budget_manager import (
    STATUS_EXCEEDED,
    STATUS_NORMAL,
    STATUS_WARNING,
    delete_budget,
    get_all_budgets,
    get_budget_alerts,
    get_budget_status,
    set_budget,
)
from src.ui.common import (
    format_inr,
    format_pct,
    get_active_db_path,
    get_categories,
    render_dataframe,
)


def render_budgets(db_path: Optional[Union[Path, str]] = None) -> None:
    """Render the Budget Management interface."""
    active_path = db_path or get_active_db_path()

    st.title("🎯 Monthly Budgets")
    st.markdown("Set spending targets, track utilization, and monitor budget alerts.")

    # 1. Month Selector
    curr_month = datetime.date.today().strftime("%Y-%m")
    selected_month = st.text_input(
        "Select Month (YYYY-MM)",
        value=curr_month,
        placeholder="e.g. 2026-11",
        key="budget_mgmt_month",
    ).strip()

    if not selected_month:
        st.warning("Please enter a valid month in YYYY-MM format.")
        return

    # -----------------------------------------------------------------------
    # Create / Update Budget Section
    # -----------------------------------------------------------------------
    expense_categories = get_categories(trans_type="Expense", db_path=active_path)

    with st.expander("➕ Set or Update Budget Limit", expanded=True):
        if not expense_categories:
            st.warning("No Expense categories found in the database.")
        else:
            with st.form("set_budget_form"):
                col1, col2 = st.columns(2)
                with col1:
                    cat_val = st.selectbox("Expense Category", options=expense_categories)
                with col2:
                    limit_val = st.number_input(
                        "Monthly Limit (₹)",
                        min_value=1.0,
                        value=5000.0,
                        step=500.0,
                        format="%.2f",
                    )

                submit_budget = st.form_submit_button("💾 Save Budget", use_container_width=True)

                if submit_budget:
                    try:
                        b_id = set_budget(
                            category=cat_val,
                            month=selected_month,
                            amount=limit_val,
                            db_path=active_path,
                        )
                        st.success(f"✅ Budget set for '{cat_val}' ({selected_month}) at {format_inr(limit_val)} (Budget #{b_id}).")
                        st.rerun()
                    except ValueError as exc:
                        st.error(f"❌ Validation Error: {exc}")
                    except Exception as exc:
                        st.error(f"❌ Failed to set budget: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Budget Alerts Banner Section
    # -----------------------------------------------------------------------
    try:
        alerts_df = get_budget_alerts(selected_month, db_path=active_path)
    except Exception as exc:
        st.error(f"Error fetching budget alerts: {exc}")
        alerts_df = None

    if alerts_df is not None and not alerts_df.empty:
        st.subheader("⚠️ Active Budget Alerts")
        for _, alert in alerts_df.iterrows():
            status = alert["status"]
            cat = alert["category"]
            util = alert["utilization_percentage"]
            spent = format_inr(alert["actual_expenses"])
            limit = format_inr(alert["budget_limit"])

            if status == STATUS_EXCEEDED:
                st.error(f"🚨 **EXCEEDED:** Category **{cat}** has exceeded its budget! Spent {spent} of {limit} ({util:.1f}%).")
            elif status == STATUS_WARNING:
                st.warning(f"⚠️ **WARNING:** Category **{cat}** is nearing its limit: spent {spent} of {limit} ({util:.1f}%).")

    # -----------------------------------------------------------------------
    # Current Budgets & Utilization Status Table
    # -----------------------------------------------------------------------
    st.subheader(f"📊 Budget Status for {selected_month}")

    try:
        status_df = get_budget_status(selected_month, db_path=active_path)
    except Exception as exc:
        st.error(f"Error loading budget status: {exc}")
        return

    if status_df.empty:
        st.info(f"No budgets configured for {selected_month}. Use the form above to add one.")
        return

    display_status = status_df.copy()
    display_status["budget_limit"] = display_status["budget_limit"].apply(format_inr)
    display_status["actual_expenses"] = display_status["actual_expenses"].apply(format_inr)
    display_status["remaining_budget"] = display_status["remaining_budget"].apply(format_inr)
    display_status["utilization_percentage"] = display_status["utilization_percentage"].apply(lambda p: f"{p:.1f}%")

    render_dataframe(
        display_status[["category", "budget_limit", "actual_expenses", "remaining_budget", "utilization_percentage", "status"]],
        hide_index=True,
    )

    st.divider()

    # -----------------------------------------------------------------------
    # Delete Budget Section
    # -----------------------------------------------------------------------
    st.subheader("🗑️ Delete Budget")
    all_budgets_df = get_all_budgets(selected_month, db_path=active_path)

    if not all_budgets_df.empty:
        budget_options = {
            int(row["budget_id"]): f"Budget #{row['budget_id']} — {row['category']} ({format_inr(row['budget_limit'])})"
            for _, row in all_budgets_df.iterrows()
        }
        del_b_id = st.selectbox(
            "Select Budget to Remove",
            options=list(budget_options.keys()),
            format_func=lambda bid: budget_options.get(bid, f"Budget #{bid}"),
            key="del_budget_id",
        )

        display_label = budget_options.get(del_b_id, f"Budget #{del_b_id}")
        confirm_del = st.checkbox(
            f"Confirm deletion of {display_label}",
            key=f"confirm_del_b_{del_b_id}",
        )
        if st.button("Delete Selected Budget", disabled=not confirm_del, type="primary"):
            try:
                deleted = delete_budget(del_b_id, db_path=active_path)
                if deleted:
                    st.success(f"✅ Budget #{del_b_id} deleted successfully.")
                    st.rerun()
                else:
                    st.error("Budget could not be found.")
            except Exception as exc:
                st.error(f"❌ Deletion failed: {exc}")
