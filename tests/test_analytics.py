"""
tests/test_analytics.py — Unit & Integration Tests for Financial Analytics
===========================================================================
Covers all 26 required deterministic analytics scenarios:
  1. Correct total income
  2. Correct total expenses
  3. Correct net savings
  4. Correct savings rate
  5. Zero-income savings rate (returns 0.0)
  6. Empty database overview (zeros, 0.0 rate, 0 counts)
  7. Date-range filtering
  8. Category-wise expense totals
  9. Income exclusion from category spending
  10. Category percentage calculation (sums to 100%)
  11. Empty category summary
  12. Monthly summary calculations
  13. Chronological monthly ordering
  14. Monthly trend calculations
  15. Year filtering
  16. Payment method grouping
  17. Missing payment method handling ('Unspecified')
  18. Top expense category limit
  19. Exclusion of Income categories from top expenses
  20. Average expense and income calculations
  21. Highest and lowest transaction values
  22. Month comparison calculations
  23. Zero-value percentage comparison handling
  24. Invalid month input (raises ValueError)
  25. Imported transactions included in analytics
  26. Multiple transactions on the same date
Preserves original placeholder ML test classes for backward compatibility.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database import (
    initialise_database,
    migrate_add_duplicate_rows_column,
    migrate_add_hardening_triggers,
)
from expense_manager import add_transaction
from import_service import (
    import_transactions,
    preview_import,
)
from analytics import (
    Analytics,
    compare_months,
    get_average_transaction,
    get_category_wise_expenses,
    get_financial_overview,
    get_monthly_summary,
    get_monthly_trends,
    get_payment_method_summary,
    get_top_expense_categories,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Isolated temporary SQLite database with all tables, triggers, and seed categories."""
    db_file = tmp_path / "test_analytics.db"
    initialise_database(db_file)
    migrate_add_hardening_triggers(db_file)
    migrate_add_duplicate_rows_column(db_file)
    return db_file


@pytest.fixture
def seeded_db(temp_db: Path) -> Path:
    """
    Temporary database seeded with predictable transactions across multiple months and categories.

    Transactions:
      - 2026-09-15: Food, 100.0, Cash, Lunch, Expense
      - 2026-10-01: Salary, 30000.0, Bank Transfer, Sept Pay, Income
      - 2026-10-15: Transportation, 200.0, Card, Gas, Expense
      - 2026-10-20: Food, 300.0, None (Unspecified), Groceries, Expense
      - 2026-11-01: Salary, 50000.0, Bank Transfer, Oct Pay, Income
      - 2026-11-05: Food, 500.0, UPI, Dinner, Expense
      - 2026-11-05: Entertainment, 1000.0, Card, Concert, Expense (same date as above)
      - 2026-11-10: Healthcare, 1500.0, Card, Dentist, Expense
      - 2026-11-12: Utilities, 500.0, UPI, Power bill, Expense
    """
    add_transaction("2026-09-15", "Food", 100.0, "Cash", "Lunch", "Expense", db_path=temp_db)
    add_transaction("2026-10-01", "Salary", 30000.0, "Bank Transfer", "Sept Pay", "Income", db_path=temp_db)
    add_transaction("2026-10-15", "Transportation", 200.0, "Card", "Gas", "Expense", db_path=temp_db)
    add_transaction("2026-10-20", "Food", 300.0, None, "Groceries", "Expense", db_path=temp_db)
    add_transaction("2026-11-01", "Salary", 50000.0, "Bank Transfer", "Oct Pay", "Income", db_path=temp_db)
    add_transaction("2026-11-05", "Food", 500.0, "UPI", "Dinner", "Expense", db_path=temp_db)
    add_transaction("2026-11-05", "Shopping", 1000.0, "Card", "Shoes", "Expense", db_path=temp_db)
    add_transaction("2026-11-10", "Healthcare", 1500.0, "Card", "Dentist", "Expense", db_path=temp_db)
    add_transaction("2026-11-12", "Utilities", 500.0, "UPI", "Power bill", "Expense", db_path=temp_db)
    return temp_db


# ---------------------------------------------------------------------------
# Test Suites
# ---------------------------------------------------------------------------

class TestFinancialOverview:
    """Tests for get_financial_overview()."""

    def test_correct_totals_and_net_savings(self, seeded_db: Path):
        ov = get_financial_overview(db_path=seeded_db)
        # Total income: 30000 + 50000 = 80000.0
        # Total expenses: 100 + 200 + 300 + 500 + 1000 + 1500 + 500 = 4100.0
        # Net savings: 80000 - 4100 = 75900.0
        assert ov["total_income"] == 80000.0
        assert ov["total_expenses"] == 4100.0
        assert ov["net_savings"] == 75900.0
        assert ov["transaction_count"] == 9
        assert ov["income_transaction_count"] == 2
        assert ov["expense_transaction_count"] == 7

    def test_correct_savings_rate(self, seeded_db: Path):
        ov = get_financial_overview(db_path=seeded_db)
        # savings_rate = (75900 / 80000) * 100 = 94.875 -> 94.88%
        assert ov["savings_rate"] == 94.88

    def test_zero_income_savings_rate(self, temp_db: Path):
        # Add expenses only
        add_transaction("2026-11-01", "Food", 100.0, "Cash", "Lunch", "Expense", db_path=temp_db)
        ov = get_financial_overview(db_path=temp_db)
        assert ov["total_income"] == 0.0
        assert ov["total_expenses"] == 100.0
        assert ov["net_savings"] == -100.0
        assert ov["savings_rate"] == 0.0

    def test_empty_database_overview(self, temp_db: Path):
        ov = get_financial_overview(db_path=temp_db)
        assert ov["total_income"] == 0.0
        assert ov["total_expenses"] == 0.0
        assert ov["net_savings"] == 0.0
        assert ov["savings_rate"] == 0.0
        assert ov["transaction_count"] == 0
        assert ov["income_transaction_count"] == 0
        assert ov["expense_transaction_count"] == 0

    def test_date_range_filtering(self, seeded_db: Path):
        ov = get_financial_overview(
            start_date="2026-10-01",
            end_date="2026-10-31",
            db_path=seeded_db,
        )
        # October: Income 30000, Expenses 200 + 300 = 500
        assert ov["total_income"] == 30000.0
        assert ov["total_expenses"] == 500.0
        assert ov["net_savings"] == 29500.0
        assert ov["transaction_count"] == 3


class TestCategoryWiseExpenses:
    """Tests for get_category_wise_expenses() and get_top_expense_categories()."""

    def test_category_wise_expense_totals(self, seeded_db: Path):
        df = get_category_wise_expenses(db_path=seeded_db)
        # Expected categories: Healthcare (1500), Shopping (1000), Food (100+300+500=900), Utilities (500), Transportation (200)
        assert len(df) == 5
        cat_map = dict(zip(df["category"], df["total_expenses"]))
        assert cat_map["Healthcare"] == 1500.0
        assert cat_map["Shopping"] == 1000.0
        assert cat_map["Food"] == 900.0
        assert cat_map["Utilities"] == 500.0
        assert cat_map["Transportation"] == 200.0

    def test_income_exclusion_from_category_spending(self, seeded_db: Path):
        df = get_category_wise_expenses(db_path=seeded_db)
        assert "Salary" not in df["category"].values

    def test_category_percentage_calculation(self, seeded_db: Path):
        df = get_category_wise_expenses(db_path=seeded_db)
        # Total expenses = 4100.0
        # Healthcare: 1500 / 4100 = 36.59%
        pct_sum = round(df["percentage_of_total"].sum(), 1)
        assert pct_sum == 100.0

    def test_empty_category_summary(self, temp_db: Path):
        df = get_category_wise_expenses(db_path=temp_db)
        assert df.empty
        assert list(df.columns) == ["category", "total_expenses", "transaction_count", "percentage_of_total"]

    def test_top_expense_categories_limit(self, seeded_db: Path):
        top3 = get_top_expense_categories(limit=3, db_path=seeded_db)
        assert len(top3) == 3
        # Sorted descending: Healthcare (1500), Shopping (1000), Food (900)
        assert list(top3["category"]) == ["Healthcare", "Shopping", "Food"]

    def test_top_categories_excludes_income(self, seeded_db: Path):
        top = get_top_expense_categories(limit=10, db_path=seeded_db)
        assert "Salary" not in top["category"].values


class TestMonthlySummaryAndTrends:
    """Tests for get_monthly_summary() and get_monthly_trends()."""

    def test_monthly_summary_calculations(self, seeded_db: Path):
        df = get_monthly_summary(db_path=seeded_db)
        assert len(df) == 3  # Sept, Oct, Nov

        row_nov = df[df["month"] == "2026-11"].iloc[0]
        assert row_nov["total_income"] == 50000.0
        assert row_nov["total_expenses"] == 3500.0  # 500+1000+1500+500
        assert row_nov["net_savings"] == 46500.0
        assert row_nov["savings_rate"] == 93.0

    def test_chronological_monthly_ordering(self, seeded_db: Path):
        df = get_monthly_summary(db_path=seeded_db)
        months = list(df["month"])
        assert months == sorted(months)
        assert months == ["2026-09", "2026-10", "2026-11"]

    def test_monthly_trends_format(self, seeded_db: Path):
        trends = get_monthly_trends(db_path=seeded_db)
        assert list(trends.columns) == ["month", "income", "expenses", "net_savings"]
        assert len(trends) == 3
        assert trends.iloc[0]["month"] == "2026-09"
        assert trends.iloc[0]["expenses"] == 100.0

    def test_year_filtering_in_monthly_summary(self, seeded_db: Path):
        df_2026 = get_monthly_summary(year=2026, db_path=seeded_db)
        assert len(df_2026) == 3

        df_2025 = get_monthly_summary(year=2025, db_path=seeded_db)
        assert df_2025.empty


class TestPaymentMethodSummary:
    """Tests for get_payment_method_summary()."""

    def test_payment_method_grouping(self, seeded_db: Path):
        df = get_payment_method_summary(db_path=seeded_db)
        # Methods in seeded_db:
        # Card: 200 (Trans) + 1000 (Entert) + 1500 (Health) = 2700.0 (3 txns)
        # UPI: 500 (Food) + 500 (Util) = 1000.0 (2 txns)
        # Unspecified: 300 (Food) (1 txn)
        # Cash: 100 (Food) (1 txn)
        pm_map = dict(zip(df["payment_method"], df["total_expenses"]))
        assert pm_map["Card"] == 2700.0
        assert pm_map["UPI"] == 1000.0
        assert pm_map["Unspecified"] == 300.0
        assert pm_map["Cash"] == 100.0

    def test_missing_payment_method_displays_unspecified(self, seeded_db: Path):
        df = get_payment_method_summary(db_path=seeded_db)
        assert "Unspecified" in df["payment_method"].values


class TestAverageAndExtremes:
    """Tests for get_average_transaction()."""

    def test_average_and_extreme_calculations(self, seeded_db: Path):
        stats = get_average_transaction(db_path=seeded_db)
        # Incomes: 30000, 50000 -> Avg: 40000.0, Max: 50000.0, Min: 30000.0
        assert stats["average_income"] == 40000.0
        assert stats["highest_income"] == 50000.0
        assert stats["lowest_income"] == 30000.0

        # Expenses: 100, 200, 300, 500, 500, 1000, 1500 -> Sum: 4100 / 7 = 585.71
        assert stats["average_expense"] == 585.71
        assert stats["highest_expense"] == 1500.0
        assert stats["lowest_expense"] == 100.0

    def test_empty_database_averages(self, temp_db: Path):
        stats = get_average_transaction(db_path=temp_db)
        assert stats["average_income"] == 0.0
        assert stats["average_expense"] == 0.0
        assert stats["highest_income"] == 0.0
        assert stats["highest_expense"] == 0.0


class TestMonthComparison:
    """Tests for compare_months()."""

    def test_month_comparison_calculations(self, seeded_db: Path):
        cmp = compare_months("2026-10", "2026-11", db_path=seeded_db)
        # Oct: Income 30000, Expenses 500, Savings 29500
        # Nov: Income 50000, Expenses 3500, Savings 46500
        assert cmp["first_month_income"] == 30000.0
        assert cmp["second_month_income"] == 50000.0
        assert cmp["first_month_expenses"] == 500.0
        assert cmp["second_month_expenses"] == 3500.0
        assert cmp["first_month_savings"] == 29500.0
        assert cmp["second_month_savings"] == 46500.0

        # Income change: ((50000 - 30000) / 30000) * 100 = 66.67%
        assert cmp["income_change"] == 66.67
        # Expense change: ((3500 - 500) / 500) * 100 = 600.0%
        assert cmp["expense_change"] == 600.0
        # Savings change: ((46500 - 29500) / 29500) * 100 = 57.63%
        assert cmp["savings_change"] == 57.63

    def test_zero_baseline_month_comparison(self, seeded_db: Path):
        # 2026-09 had 0 income, 100 expenses, savings = -100
        # 2026-10 had 30000 income, 500 expenses, savings = 29500
        cmp = compare_months("2026-09", "2026-10", db_path=seeded_db)
        assert cmp["first_month_income"] == 0.0
        assert cmp["second_month_income"] == 30000.0
        # Zero baseline policy: returns None for percentage change, while retaining absolute change
        assert cmp["income_change"] is None
        assert cmp["income_change_abs"] == 30000.0
        # Expense change: 100 to 500 -> +400.0%
        assert cmp["expense_change"] == 400.0
        assert cmp["expense_change_abs"] == 400.0
        # Savings change: -100 to 29500 -> ((29500 - (-100)) / abs(-100)) * 100 = 29600.0%
        assert cmp["savings_change"] == 29600.0
        assert cmp["savings_change_abs"] == 29600.0

    def test_month_comparison_edge_cases(self, temp_db: Path):
        # 1. Zero to zero: both 0 -> percentage is None, abs is 0.0
        cmp_zero = compare_months("2026-01", "2026-02", db_path=temp_db)
        assert cmp_zero["income_change"] is None
        assert cmp_zero["income_change_abs"] == 0.0
        assert cmp_zero["expense_change"] is None
        assert cmp_zero["expense_change_abs"] == 0.0
        assert cmp_zero["savings_change"] is None
        assert cmp_zero["savings_change_abs"] == 0.0

        # 2. Positive to zero
        add_transaction("2026-01-10", "Salary", 5000.0, "UPI", "Pay", "Income", db_path=temp_db)
        add_transaction("2026-01-15", "Food", 2000.0, "Cash", "Groceries", "Expense", db_path=temp_db)
        # Month 1: inc 5000, exp 2000, sav 3000
        # Month 2: inc 0, exp 0, sav 0
        cmp_pos_to_zero = compare_months("2026-01", "2026-02", db_path=temp_db)
        assert cmp_pos_to_zero["income_change"] == -100.0
        assert cmp_pos_to_zero["income_change_abs"] == -5000.0
        assert cmp_pos_to_zero["expense_change"] == -100.0
        assert cmp_pos_to_zero["expense_change_abs"] == -2000.0
        assert cmp_pos_to_zero["savings_change"] == -100.0
        assert cmp_pos_to_zero["savings_change_abs"] == -3000.0

        # 3. Savings changing from positive to negative
        # 2026-03: inc 1000, exp 3000 -> sav -2000
        add_transaction("2026-03-05", "Salary", 1000.0, "UPI", "Pay", "Income", db_path=temp_db)
        add_transaction("2026-03-10", "Food", 3000.0, "Cash", "Food", "Expense", db_path=temp_db)
        cmp_pos_to_neg = compare_months("2026-01", "2026-03", db_path=temp_db)
        # sav: 3000 -> -2000: ((-2000 - 3000) / 3000) * 100 = -166.67%
        assert cmp_pos_to_neg["first_month_savings"] == 3000.0
        assert cmp_pos_to_neg["second_month_savings"] == -2000.0
        assert cmp_pos_to_neg["savings_change"] == -166.67
        assert cmp_pos_to_neg["savings_change_abs"] == -5000.0

        # 4. Savings changing from negative to positive
        cmp_neg_to_pos = compare_months("2026-03", "2026-01", db_path=temp_db)
        # sav: -2000 -> 3000: ((3000 - (-2000)) / abs(-2000)) * 100 = +250.0%
        assert cmp_neg_to_pos["first_month_savings"] == -2000.0
        assert cmp_neg_to_pos["second_month_savings"] == 3000.0
        assert cmp_neg_to_pos["savings_change"] == 250.0
        assert cmp_neg_to_pos["savings_change_abs"] == 5000.0

    def test_invalid_month_format_rejected(self, temp_db: Path):
        with pytest.raises(ValueError, match="Invalid month"):
            compare_months("2026-13", "2026-11", db_path=temp_db)

        with pytest.raises(ValueError, match="Invalid month"):
            compare_months("11-2026", "2026-11", db_path=temp_db)


class TestIntegrationAndEdgeCases:
    """Import integration, multiple transactions on same date, and OOP wrapper."""

    def test_multiple_transactions_on_same_date(self, temp_db: Path):
        add_transaction("2026-11-05", "Food", 50.0, "Cash", "Breakfast", "Expense", db_path=temp_db)
        add_transaction("2026-11-05", "Food", 150.0, "UPI", "Lunch", "Expense", db_path=temp_db)
        add_transaction("2026-11-05", "Food", 300.0, "Card", "Dinner", "Expense", db_path=temp_db)

        df = get_category_wise_expenses(db_path=temp_db)
        assert len(df) == 1
        assert df.iloc[0]["total_expenses"] == 500.0
        assert df.iloc[0]["transaction_count"] == 3

    def test_imported_transactions_included_in_analytics(self, temp_db: Path, tmp_path: Path):
        csv_file = tmp_path / "imported_batch.csv"
        csv_file.write_text(
            "date,category,amount,payment_method,description,type\n"
            "2026-11-20,Healthcare,2500.0,Card,Hospital,Expense\n"
            "2026-11-25,Salary,60000.0,Bank Transfer,Bonus Pay,Income\n",
            encoding="utf-8",
        )
        preview = preview_import(csv_file, db_path=temp_db)
        import_transactions(preview, filename="imported_batch.csv", db_path=temp_db)

        ov = get_financial_overview(db_path=temp_db)
        assert ov["total_income"] == 60000.0
        assert ov["total_expenses"] == 2500.0
        assert ov["net_savings"] == 57500.0

    def test_analytics_oop_wrapper(self, seeded_db: Path):
        analytics = Analytics(seeded_db)
        ov = analytics.get_financial_overview()
        assert ov["total_income"] == 80000.0
        assert ov["total_expenses"] == 4100.0

        cats = analytics.get_top_expense_categories(limit=2)
        assert len(cats) == 2


# ---------------------------------------------------------------------------
# Preserved Placeholder Tests from Session 1
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_expense_df():
    data = {
        "date": ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"],
        "amount": [400.0, 150.0, 2500.0, 80.0, 1200.0],
        "category": ["Food", "Transport", "Shopping", "Food", "Entertainment"],
        "payment_method": ["UPI", "Cash", "Card", "Cash", "Card"],
        "description": ["Lunch", "Auto", "Shoes", "Tea", "Movie"],
    }
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    return df


class TestMonthlyAnalytics:
    def test_placeholder_monthly_summary(self, sample_expense_df):
        assert sample_expense_df is not None

    def test_placeholder_category_breakdown(self, sample_expense_df):
        assert len(sample_expense_df) == 5

    def test_placeholder_daily_trend(self, sample_expense_df):
        assert "amount" in sample_expense_df.columns


class TestMLAnalytics:
    def test_placeholder_anomaly_detection(self, sample_expense_df):
        assert True

    def test_placeholder_forecasting(self, sample_expense_df):
        assert True
