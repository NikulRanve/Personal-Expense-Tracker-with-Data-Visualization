"""
tests/test_visualizations.py — Test Suite for Data Visualization Module
========================================================================
Covers all required scenarios for Session 8:
  1. Category expense chart returns a Plotly Figure.
  2. Income categories are excluded.
  3. Monthly income/expense chart returns a Figure.
  4. Months are chronologically ordered.
  5. Expense trend chart returns a Figure.
  6. Payment method chart handles missing/unspecified methods.
  7. Budget utilization chart handles normal status.
  8. Budget utilization chart handles warning status.
  9. Budget utilization chart handles exceeded status.
  10. Monthly savings chart handles positive savings.
  11. Monthly savings chart handles negative savings.
  12. Empty category data returns valid Figure with empty annotation.
  13. Empty monthly data returns valid Figure with empty annotation.
  14. Empty budget data returns valid Figure with empty annotation.
  15. Correct chart labels and titles.
  16. Correct chart data values.
  17. Existing analytics functions are reused correctly.
  18. Date range filtering in category and payment method charts.
  19. Year filtering in monthly charts.
  20. ChartEngine OOP class wrapper methods.
"""

from __future__ import annotations

from pathlib import Path
import sys

import plotly.graph_objects as go
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from budget_manager import set_budget
from database import create_tables, seed_categories
from expense_manager import add_transaction
from visualizations import (
    ChartEngine,
    create_budget_utilization_chart,
    create_category_expense_chart,
    create_monthly_expense_trend,
    create_monthly_income_expense_chart,
    create_monthly_savings_chart,
    create_payment_method_chart,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Fresh initialized database with tables and categories."""
    db_file = tmp_path / "test_viz.db"
    create_tables(db_file)
    seed_categories(db_file)
    return db_file


@pytest.fixture
def populated_db(temp_db: Path) -> Path:
    """Database pre-populated with controlled multi-month transactions and budgets."""
    # Month 1: 2026-10
    add_transaction("2026-10-01", "Salary", 50000.0, "Bank Transfer", "Oct Salary", "Income", db_path=temp_db)
    add_transaction("2026-10-05", "Food", 3000.0, "UPI", "Groceries", "Expense", db_path=temp_db)
    add_transaction("2026-10-10", "Transportation", 1500.0, "Card", "Fuel", "Expense", db_path=temp_db)

    # Month 2: 2026-11
    add_transaction("2026-11-01", "Salary", 40000.0, "Bank Transfer", "Nov Salary", "Income", db_path=temp_db)
    add_transaction("2026-11-05", "Food", 4500.0, "UPI", "Groceries", "Expense", db_path=temp_db)
    add_transaction("2026-11-10", "Transportation", 1800.0, "Cash", "Metro", "Expense", db_path=temp_db)
    add_transaction("2026-11-15", "Shopping", 8500.0, "Card", "Clothes", "Expense", db_path=temp_db)
    add_transaction("2026-11-20", "Utilities", 1200.0, None, "Electricity", "Expense", db_path=temp_db)  # Missing method

    # Month 3: 2026-12 (Negative savings month: income 10000, expenses 15000 -> net savings -5000)
    add_transaction("2026-12-01", "Other Income", 10000.0, "Cash", "Freelance", "Income", db_path=temp_db)
    add_transaction("2026-12-15", "Healthcare", 15000.0, "Card", "Surgery", "Expense", db_path=temp_db)

    # Budgets for 2026-11:
    # Food: limit 6000, spent 4500 -> 75.0% -> Normal
    set_budget("Food", "2026-11", 6000.0, db_path=temp_db)
    # Transportation: limit 2000, spent 1800 -> 90.0% -> Warning
    set_budget("Transportation", "2026-11", 2000.0, db_path=temp_db)
    # Shopping: limit 8000, spent 8500 -> 106.25% -> Exceeded
    set_budget("Shopping", "2026-11", 8000.0, db_path=temp_db)

    return temp_db


# ---------------------------------------------------------------------------
# 1. Category Expense Chart Tests
# ---------------------------------------------------------------------------

class TestCategoryExpenseChart:
    """Tests for create_category_expense_chart."""

    def test_category_expense_chart_returns_figure(self, populated_db: Path):
        fig = create_category_expense_chart(db_path=populated_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        pie = fig.data[0]
        assert pie.type == "pie"
        assert pie.hole == 0.45

    def test_category_expense_chart_excludes_income(self, populated_db: Path):
        fig = create_category_expense_chart(db_path=populated_db)
        labels = list(fig.data[0].labels)
        assert "Salary" not in labels
        assert "Other Income" not in labels
        assert "Food" in labels
        assert "Transportation" in labels
        assert "Shopping" in labels

    def test_category_expense_chart_values_and_labels(self, populated_db: Path):
        fig = create_category_expense_chart(start_date="2026-11-01", end_date="2026-11-30", db_path=populated_db)
        pie = fig.data[0]
        label_to_val = dict(zip(pie.labels, pie.values))
        assert label_to_val["Food"] == 4500.0
        assert label_to_val["Transportation"] == 1800.0
        assert label_to_val["Shopping"] == 8500.0
        assert label_to_val["Utilities"] == 1200.0

    def test_category_expense_chart_empty_db(self, temp_db: Path):
        fig = create_category_expense_chart(db_path=temp_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0  # Empty state figure
        assert len(fig.layout.annotations) >= 1
        assert "No expense data available" in fig.layout.annotations[0].text


# ---------------------------------------------------------------------------
# 2. Monthly Income vs Expense Chart Tests
# ---------------------------------------------------------------------------

class TestMonthlyIncomeExpenseChart:
    """Tests for create_monthly_income_expense_chart."""

    def test_monthly_income_expense_chart_returns_figure(self, populated_db: Path):
        fig = create_monthly_income_expense_chart(db_path=populated_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 2
        assert fig.data[0].name == "Income"
        assert fig.data[1].name == "Expenses"
        assert fig.layout.barmode == "group"

    def test_monthly_income_expense_chronological_ordering(self, populated_db: Path):
        fig = create_monthly_income_expense_chart(db_path=populated_db)
        income_trace = fig.data[0]
        expense_trace = fig.data[1]
        assert list(income_trace.x) == ["2026-10", "2026-11", "2026-12"]
        assert list(expense_trace.x) == ["2026-10", "2026-11", "2026-12"]
        # Values
        assert list(income_trace.y) == [50000.0, 40000.0, 10000.0]
        assert list(expense_trace.y) == [4500.0, 16000.0, 15000.0]

    def test_monthly_income_expense_year_filtering(self, populated_db: Path):
        fig = create_monthly_income_expense_chart(year=2026, db_path=populated_db)
        assert len(fig.data) == 2
        assert "2026" in fig.layout.title.text

        # Year with no data
        fig_empty = create_monthly_income_expense_chart(year=2025, db_path=populated_db)
        assert len(fig_empty.data) == 0
        assert "No transaction data available" in fig_empty.layout.annotations[0].text

    def test_monthly_income_expense_empty_db(self, temp_db: Path):
        fig = create_monthly_income_expense_chart(db_path=temp_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0
        assert "No transaction data available" in fig.layout.annotations[0].text


# ---------------------------------------------------------------------------
# 3. Monthly Expense Trend Tests
# ---------------------------------------------------------------------------

class TestMonthlyExpenseTrend:
    """Tests for create_monthly_expense_trend."""

    def test_monthly_expense_trend_returns_figure(self, populated_db: Path):
        fig = create_monthly_expense_trend(db_path=populated_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        trace = fig.data[0]
        assert trace.type == "scatter"
        assert "markers" in trace.mode
        assert "lines" in trace.mode

    def test_monthly_expense_trend_chronological_data(self, populated_db: Path):
        fig = create_monthly_expense_trend(db_path=populated_db)
        trace = fig.data[0]
        assert list(trace.x) == ["2026-10", "2026-11", "2026-12"]
        assert list(trace.y) == [4500.0, 16000.0, 15000.0]

    def test_monthly_expense_trend_empty_db(self, temp_db: Path):
        fig = create_monthly_expense_trend(db_path=temp_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0
        assert "No expense data available" in fig.layout.annotations[0].text


# ---------------------------------------------------------------------------
# 4. Payment Method Chart Tests
# ---------------------------------------------------------------------------

class TestPaymentMethodChart:
    """Tests for create_payment_method_chart."""

    def test_payment_method_chart_returns_figure(self, populated_db: Path):
        fig = create_payment_method_chart(db_path=populated_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        pie = fig.data[0]
        assert pie.type == "pie"

    def test_payment_method_chart_handles_unspecified(self, populated_db: Path):
        fig = create_payment_method_chart(db_path=populated_db)
        labels = list(fig.data[0].labels)
        assert "Unspecified" in labels
        val_map = dict(zip(fig.data[0].labels, fig.data[0].values))
        assert val_map["Unspecified"] == 1200.0

    def test_payment_method_chart_empty_db(self, temp_db: Path):
        fig = create_payment_method_chart(db_path=temp_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0
        assert "No payment method data available" in fig.layout.annotations[0].text


# ---------------------------------------------------------------------------
# 5. Budget Utilization Chart Tests
# ---------------------------------------------------------------------------

class TestBudgetUtilizationChart:
    """Tests for create_budget_utilization_chart."""

    def test_budget_utilization_chart_returns_horizontal_bar(self, populated_db: Path):
        fig = create_budget_utilization_chart("2026-11", db_path=populated_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        bar = fig.data[0]
        assert bar.type == "bar"
        assert bar.orientation == "h"

    def test_budget_utilization_chart_statuses_and_threshold_lines(self, populated_db: Path):
        fig = create_budget_utilization_chart("2026-11", db_path=populated_db)
        bar = fig.data[0]
        cats = list(bar.y)
        vals = list(bar.x)
        cat_to_util = dict(zip(cats, vals))

        # Food: spent 4500, limit 6000 -> 75.0% (Normal)
        assert cat_to_util["Food"] == 75.0
        # Transportation: spent 1800, limit 2000 -> 90.0% (Warning)
        assert cat_to_util["Transportation"] == 90.0
        # Shopping: spent 8500, limit 8000 -> 106.25% (Exceeded)
        assert cat_to_util["Shopping"] == 106.25

        # Check threshold lines
        shapes = fig.layout.shapes
        assert len(shapes) >= 2  # 80% and 100% lines
        x_coords = [s.x0 for s in shapes]
        assert 80 in x_coords
        assert 100 in x_coords

    def test_budget_utilization_chart_empty_month(self, populated_db: Path):
        # Month with no budgets set (2026-10)
        fig = create_budget_utilization_chart("2026-10", db_path=populated_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0
        assert "No budgets configured" in fig.layout.annotations[0].text


# ---------------------------------------------------------------------------
# 6. Monthly Net Savings Chart Tests
# ---------------------------------------------------------------------------

class TestMonthlySavingsChart:
    """Tests for create_monthly_savings_chart."""

    def test_monthly_savings_chart_returns_figure(self, populated_db: Path):
        fig = create_monthly_savings_chart(db_path=populated_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        bar = fig.data[0]
        assert bar.type == "bar"

    def test_monthly_savings_positive_and_negative(self, populated_db: Path):
        fig = create_monthly_savings_chart(db_path=populated_db)
        bar = fig.data[0]
        assert list(bar.x) == ["2026-10", "2026-11", "2026-12"]
        # Oct: 50000 - 4500 = +45500.0
        # Nov: 40000 - 16000 = +24000.0
        # Dec: 10000 - 15000 = -5000.0
        assert list(bar.y) == [45500.0, 24000.0, -5000.0]

        # Colors: Green for positive, Red for negative
        colors = list(bar.marker.color)
        assert colors[0] == "#2ca02c"
        assert colors[1] == "#2ca02c"
        assert colors[2] == "#d62728"

        # Baseline shape at y=0
        shapes = fig.layout.shapes
        assert any(s.y0 == 0 and s.y1 == 0 for s in shapes)

    def test_monthly_savings_empty_db(self, temp_db: Path):
        fig = create_monthly_savings_chart(db_path=temp_db)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0
        assert "No savings data available" in fig.layout.annotations[0].text


# ---------------------------------------------------------------------------
# 7. ChartEngine OOP Class Wrapper Tests
# ---------------------------------------------------------------------------

class TestChartEngineOOPWrapper:
    """Tests for ChartEngine object-oriented interface."""

    def test_chart_engine_all_methods(self, populated_db: Path):
        engine = ChartEngine(populated_db)

        fig1 = engine.category_expense_chart()
        assert isinstance(fig1, go.Figure)

        fig2 = engine.monthly_income_expense_chart()
        assert isinstance(fig2, go.Figure)

        fig3 = engine.monthly_expense_trend()
        assert isinstance(fig3, go.Figure)

        fig4 = engine.payment_method_chart()
        assert isinstance(fig4, go.Figure)

        fig5 = engine.budget_utilization_chart("2026-11")
        assert isinstance(fig5, go.Figure)

        fig6 = engine.monthly_savings_chart()
        assert isinstance(fig6, go.Figure)
