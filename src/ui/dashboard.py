"""
src/ui/dashboard.py — Financial Overview Dashboard Page
========================================================
Presents KPI overview cards, date/year filters, and all 6 interactive Plotly charts.
"""

from __future__ import annotations

import datetime
from typing import Optional, Union
from pathlib import Path

import streamlit as st

from src.analytics import get_financial_overview
from src.ui.common import format_inr, format_pct, get_active_db_path
from src.visualizations import (
    create_budget_utilization_chart,
    create_category_expense_chart,
    create_monthly_expense_trend,
    create_monthly_income_expense_chart,
    create_monthly_savings_chart,
    create_payment_method_chart,
)


def render_dashboard(db_path: Optional[Union[Path, str]] = None) -> None:
    """Render the main Financial Overview Dashboard."""
    active_path = db_path or get_active_db_path()

    st.title("📊 Financial Dashboard")
    st.markdown("Interactive overview of your income, expenses, budgets, and savings trends.")

    # -----------------------------------------------------------------------
    # Filters
    # -----------------------------------------------------------------------
    with st.expander("🔍 Dashboard Filters", expanded=True):
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)

        with col_f1:
            use_date_filter = st.checkbox("Filter by Date Range", value=False)
        with col_f2:
            start_date_val = st.date_input(
                "Start Date",
                value=datetime.date.today().replace(day=1),
                disabled=not use_date_filter,
            )
        with col_f3:
            end_date_val = st.date_input(
                "End Date",
                value=datetime.date.today(),
                disabled=not use_date_filter,
            )
        with col_f4:
            year_option = st.selectbox(
                "Annual View (Year)",
                options=["All Time", 2024, 2025, 2026, 2027],
                index=0,
            )

    start_date_str = start_date_val.strftime("%Y-%m-%d") if use_date_filter else None
    end_date_str = end_date_val.strftime("%Y-%m-%d") if use_date_filter else None
    selected_year = int(year_option) if isinstance(year_option, int) else None

    # -----------------------------------------------------------------------
    # KPI Cards
    # -----------------------------------------------------------------------
    overview = get_financial_overview(
        start_date=start_date_str,
        end_date=end_date_str,
        db_path=active_path,
    )

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric(
            label="Total Income",
            value=format_inr(overview["total_income"]),
            help=f"{overview['income_transaction_count']} income transaction(s)",
        )
    with kpi2:
        st.metric(
            label="Total Expenses",
            value=format_inr(overview["total_expenses"]),
            help=f"{overview['expense_transaction_count']} expense transaction(s)",
        )
    with kpi3:
        savings_color = "normal" if overview["net_savings"] >= 0 else "inverse"
        st.metric(
            label="Net Savings",
            value=format_inr(overview["net_savings"]),
            delta=f"{overview['savings_rate']:.1f}% rate" if overview["savings_rate"] is not None else None,
            delta_color=savings_color,
        )
    with kpi4:
        st.metric(
            label="Savings Rate",
            value=format_pct(overview["savings_rate"]),
            help="Net Savings divided by Total Income",
        )

    st.divider()

    # -----------------------------------------------------------------------
    # Visualizations (All 6 Charts)
    # -----------------------------------------------------------------------
    st.subheader("📈 Financial Visualizations")

    # Row 1: Category Expense Donut + Payment Methods
    row1_c1, row1_c2 = st.columns(2)
    with row1_c1:
        fig_cat = create_category_expense_chart(
            start_date=start_date_str,
            end_date=end_date_str,
            db_path=active_path,
        )
        st.plotly_chart(fig_cat, use_container_width=True)

    with row1_c2:
        fig_pm = create_payment_method_chart(
            start_date=start_date_str,
            end_date=end_date_str,
            db_path=active_path,
        )
        st.plotly_chart(fig_pm, use_container_width=True)

    # Row 2: Monthly Income vs Expenses + Monthly Net Savings
    row2_c1, row2_c2 = st.columns(2)
    with row2_c1:
        fig_inc_exp = create_monthly_income_expense_chart(
            year=selected_year,
            db_path=active_path,
        )
        st.plotly_chart(fig_inc_exp, use_container_width=True)

    with row2_c2:
        fig_savings = create_monthly_savings_chart(
            year=selected_year,
            db_path=active_path,
        )
        st.plotly_chart(fig_savings, use_container_width=True)

    # Row 3: Monthly Expense Trend + Budget Utilization
    row3_c1, row3_c2 = st.columns(2)
    with row3_c1:
        fig_trend = create_monthly_expense_trend(
            year=selected_year,
            db_path=active_path,
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    with row3_c2:
        # Month selector for budget utilization
        current_month_str = datetime.date.today().strftime("%Y-%m")
        budget_month = st.text_input(
            "Budget Month (YYYY-MM)",
            value=current_month_str,
            key="dash_budget_month",
        )
        fig_budget = create_budget_utilization_chart(
            month=budget_month.strip(),
            db_path=active_path,
        )
        st.plotly_chart(fig_budget, use_container_width=True)
