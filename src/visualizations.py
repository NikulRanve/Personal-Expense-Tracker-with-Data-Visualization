"""
src/visualizations.py — Interactive Financial Visualization Module
===================================================================
Generates reusable interactive financial charts using Plotly.

Consumes data directly from the deterministic analytics and budget-management
modules (src.analytics and src.budget_manager) without duplicating SQL
queries or financial calculations.

Functions:
  1. create_category_expense_chart: Donut chart of expenses by category (Expense only).
  2. create_monthly_income_expense_chart: Grouped bar chart comparing income vs expenses.
  3. create_monthly_expense_trend: Line chart with markers showing monthly expense trajectory.
  4. create_payment_method_chart: Donut chart showing expense distribution across payment methods.
  5. create_budget_utilization_chart: Horizontal bar chart showing category budget utilization
     with 80% (Warning) and 100% (Exceeded) threshold lines.
  6. create_monthly_savings_chart: Bar chart showing monthly net savings with distinct colors
     for positive and negative values and a zero baseline.
  7. ChartEngine: Object-oriented interface wrapper for visualization generation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd
import plotly.graph_objects as go

from src.analytics import (
    get_category_wise_expenses,
    get_monthly_summary,
    get_payment_method_summary,
)
from src.budget_manager import (
    STATUS_EXCEEDED,
    STATUS_NORMAL,
    STATUS_WARNING,
    get_budget_status,
)

logger = logging.getLogger(__name__)

# Color palettes
COLOR_INCOME = "#2ca02c"    # Green
COLOR_EXPENSE = "#d62728"   # Red
COLOR_TREND = "#1f77b4"     # Blue

STATUS_COLORS = {
    STATUS_NORMAL: "#2ca02c",    # Green
    STATUS_WARNING: "#ff7f0e",   # Orange
    STATUS_EXCEEDED: "#d62728",  # Red
}


def _create_empty_figure(title: str, message: str = "No data available to display") -> go.Figure:
    """
    Return a clean empty-state Plotly Figure with an informative annotation.

    Prevents exceptions on empty DataFrames while providing clear visual feedback.
    """
    fig = go.Figure()
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            {
                "text": message,
                "xref": "paper",
                "yref": "paper",
                "showarrow": False,
                "font": {"size": 14, "color": "gray"},
            }
        ],
        template="plotly_white",
    )
    return fig


# ---------------------------------------------------------------------------
# 1. Category Expense Chart (Donut)
# ---------------------------------------------------------------------------

def create_category_expense_chart(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> go.Figure:
    """
    Create a Plotly donut chart showing expenses by category.

    Excludes income categories. Handles empty datasets safely.

    Parameters
    ----------
    start_date : Optional[str]
        Start date (YYYY-MM-DD inclusive).
    end_date : Optional[str]
        End date (YYYY-MM-DD inclusive).
    db_path : Optional[Path | str]
        Database path.

    Returns
    -------
    go.Figure
        Interactive Plotly donut chart.
    """
    title = "Expenses by Category"
    if start_date and end_date:
        title = f"Expenses by Category ({start_date} to {end_date})"
    elif start_date:
        title = f"Expenses by Category (From {start_date})"
    elif end_date:
        title = f"Expenses by Category (Up to {end_date})"

    df = get_category_wise_expenses(start_date=start_date, end_date=end_date, db_path=db_path)

    if df.empty or df["total_expenses"].sum() == 0:
        return _create_empty_figure(title, "No expense data available")

    fig = go.Figure(
        data=[
            go.Pie(
                labels=df["category"],
                values=df["total_expenses"],
                hole=0.45,
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>Amount: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
                marker={"line": {"color": "#ffffff", "width": 1.5}},
            )
        ]
    )
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        template="plotly_white",
        legend_title_text="Category",
    )
    return fig


# ---------------------------------------------------------------------------
# 2. Monthly Income vs Expense Chart (Grouped Bar)
# ---------------------------------------------------------------------------

def create_monthly_income_expense_chart(
    year: Optional[int] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> go.Figure:
    """
    Create a grouped bar chart comparing monthly income and expenses.

    Chronologically ordered. Supports optional year filtering.

    Parameters
    ----------
    year : Optional[int]
        Optional calendar year filter (e.g. 2026).
    db_path : Optional[Path | str]
        Database path.

    Returns
    -------
    go.Figure
        Grouped bar chart.
    """
    title = f"Monthly Income vs Expenses ({year})" if year else "Monthly Income vs Expenses"
    df = get_monthly_summary(year=year, db_path=db_path)

    if df.empty:
        return _create_empty_figure(title, "No transaction data available")

    df = df.sort_values("month", ascending=True)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["month"],
            y=df["total_income"],
            name="Income",
            marker_color=COLOR_INCOME,
            hovertemplate="Month: %{x}<br>Income: ₹%{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=df["month"],
            y=df["total_expenses"],
            name="Expenses",
            marker_color=COLOR_EXPENSE,
            hovertemplate="Month: %{x}<br>Expenses: ₹%{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        barmode="group",
        xaxis_title="Month",
        yaxis_title="Amount (₹)",
        template="plotly_white",
        legend_title_text="Transaction Type",
    )
    return fig


# ---------------------------------------------------------------------------
# 3. Monthly Expense Trend (Line Chart)
# ---------------------------------------------------------------------------

def create_monthly_expense_trend(
    year: Optional[int] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> go.Figure:
    """
    Create a line chart showing monthly expense trends over time.

    Chronologically ordered with marked data points.

    Parameters
    ----------
    year : Optional[int]
        Optional calendar year filter.
    db_path : Optional[Path | str]
        Database path.

    Returns
    -------
    go.Figure
        Line chart.
    """
    title = f"Monthly Expense Trend ({year})" if year else "Monthly Expense Trend"
    df = get_monthly_summary(year=year, db_path=db_path)

    if df.empty:
        return _create_empty_figure(title, "No expense data available")

    df = df.sort_values("month", ascending=True)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["month"],
            y=df["total_expenses"],
            mode="lines+markers",
            name="Expenses",
            line={"color": COLOR_TREND, "width": 3},
            marker={"size": 8, "color": COLOR_TREND},
            hovertemplate="Month: %{x}<br>Expenses: ₹%{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        xaxis_title="Month",
        yaxis_title="Expenses (₹)",
        template="plotly_white",
    )
    return fig


# ---------------------------------------------------------------------------
# 4. Payment Method Chart (Donut)
# ---------------------------------------------------------------------------

def create_payment_method_chart(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> go.Figure:
    """
    Create a chart showing expense distribution across payment methods.

    Handles missing payment methods ('Unspecified').

    Parameters
    ----------
    start_date : Optional[str]
        Start date filter.
    end_date : Optional[str]
        End date filter.
    db_path : Optional[Path | str]
        Database path.

    Returns
    -------
    go.Figure
        Donut chart.
    """
    title = "Expenses by Payment Method"
    df = get_payment_method_summary(start_date=start_date, end_date=end_date, db_path=db_path)

    if df.empty or df["total_expenses"].sum() == 0:
        return _create_empty_figure(title, "No payment method data available")

    fig = go.Figure(
        data=[
            go.Pie(
                labels=df["payment_method"],
                values=df["total_expenses"],
                hole=0.45,
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>Amount: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
                marker={"line": {"color": "#ffffff", "width": 1.5}},
            )
        ]
    )
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        template="plotly_white",
        legend_title_text="Payment Method",
    )
    return fig


# ---------------------------------------------------------------------------
# 5. Budget Utilization Chart (Horizontal Bar)
# ---------------------------------------------------------------------------

def create_budget_utilization_chart(
    month: str,
    db_path: Optional[Union[Path, str]] = None,
) -> go.Figure:
    """
    Create a horizontal bar chart showing category budget utilization.

    Features:
      - Warning threshold indicator line at 80%
      - Exceeded threshold indicator line at 100%
      - Color distinction for Normal, Warning, and Exceeded statuses.

    Parameters
    ----------
    month : str
        Target month (YYYY-MM).
    db_path : Optional[Path | str]
        Database path.

    Returns
    -------
    go.Figure
        Horizontal bar chart.
    """
    title = f"Budget Utilization ({month})"
    df = get_budget_status(month=month, db_path=db_path)

    if df.empty:
        return _create_empty_figure(title, f"No budgets configured for {month}")

    colors = [STATUS_COLORS.get(s, "#1f77b4") for s in df["status"]]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=df["category"],
            x=df["utilization_percentage"],
            orientation="h",
            marker_color=colors,
            customdata=df[["budget_limit", "actual_expenses", "status"]].values,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Utilization: %{x:.1f}%<br>"
                "Spent: ₹%{customdata[1]:,.2f}<br>"
                "Limit: ₹%{customdata[0]:,.2f}<br>"
                "Status: %{customdata[2]}<extra></extra>"
            ),
        )
    )

    # 80% Warning threshold line
    fig.add_vline(
        x=80,
        line_dash="dash",
        line_color="#ff7f0e",
        annotation_text="Warning (80%)",
        annotation_position="top right",
    )

    # 100% Exceeded threshold line
    fig.add_vline(
        x=100,
        line_dash="dash",
        line_color="#d62728",
        annotation_text="Limit (100%)",
        annotation_position="top right",
    )

    max_util = float(df["utilization_percentage"].max()) if not df.empty else 0.0
    x_upper = max(115.0, max_util * 1.1)

    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        xaxis_title="Budget Utilization (%)",
        yaxis_title="Category",
        xaxis_range=[0, x_upper],
        template="plotly_white",
    )
    return fig


# ---------------------------------------------------------------------------
# 6. Monthly Net Savings Chart (Bar Chart)
# ---------------------------------------------------------------------------

def create_monthly_savings_chart(
    year: Optional[int] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> go.Figure:
    """
    Create a bar chart showing monthly net savings.

    Distinctly formats positive vs negative savings and displays a zero baseline.

    Parameters
    ----------
    year : Optional[int]
        Optional calendar year filter.
    db_path : Optional[Path | str]
        Database path.

    Returns
    -------
    go.Figure
        Bar chart with baseline.
    """
    title = f"Monthly Net Savings ({year})" if year else "Monthly Net Savings"
    df = get_monthly_summary(year=year, db_path=db_path)

    if df.empty:
        return _create_empty_figure(title, "No savings data available")

    df = df.sort_values("month", ascending=True)
    colors = [COLOR_INCOME if s >= 0 else COLOR_EXPENSE for s in df["net_savings"]]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["month"],
            y=df["net_savings"],
            marker_color=colors,
            hovertemplate="Month: %{x}<br>Net Savings: ₹%{y:,.2f}<extra></extra>",
        )
    )

    # Explicit zero baseline line
    fig.add_hline(
        y=0,
        line_width=1.5,
        line_color="#333333",
    )

    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        xaxis_title="Month",
        yaxis_title="Net Savings (₹)",
        template="plotly_white",
    )
    return fig


# ---------------------------------------------------------------------------
# ChartEngine OOP Class Wrapper
# ---------------------------------------------------------------------------

class ChartEngine:
    """
    Object-oriented visualization engine for generating interactive financial charts.

    Parameters
    ----------
    db_path : Optional[Path | str]
        Optional path to the SQLite database file.
    """

    def __init__(self, db_path: Optional[Union[Path, str]] = None):
        self.db_path = db_path

    def category_expense_chart(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> go.Figure:
        """Create category expense donut chart."""
        return create_category_expense_chart(start_date=start_date, end_date=end_date, db_path=self.db_path)

    def monthly_income_expense_chart(
        self,
        year: Optional[int] = None,
    ) -> go.Figure:
        """Create monthly income vs expense grouped bar chart."""
        return create_monthly_income_expense_chart(year=year, db_path=self.db_path)

    def monthly_expense_trend(
        self,
        year: Optional[int] = None,
    ) -> go.Figure:
        """Create monthly expense trend line chart."""
        return create_monthly_expense_trend(year=year, db_path=self.db_path)

    def payment_method_chart(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> go.Figure:
        """Create payment method distribution chart."""
        return create_payment_method_chart(start_date=start_date, end_date=end_date, db_path=self.db_path)

    def budget_utilization_chart(
        self,
        month: str,
    ) -> go.Figure:
        """Create budget utilization horizontal bar chart."""
        return create_budget_utilization_chart(month=month, db_path=self.db_path)

    def monthly_savings_chart(
        self,
        year: Optional[int] = None,
    ) -> go.Figure:
        """Create monthly net savings bar chart."""
        return create_monthly_savings_chart(year=year, db_path=self.db_path)
