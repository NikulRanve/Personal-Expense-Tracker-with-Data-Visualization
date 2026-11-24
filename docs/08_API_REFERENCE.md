# 08 — API Reference
## Personal Expense Tracker with Data Visualization

> This is the internal function/class API — not an HTTP API. All calls are Python function calls within the same process.

---

## 📦 `src.services.expense_service`

### Class: `ExpenseService`

```python
class ExpenseService:
    def __init__(self, session: Session): ...
```

#### `add_expense`
```python
def add_expense(
    amount: float,
    category: str,
    date: str,                    # "YYYY-MM-DD"
    description: str = "",
    payment_method: str = "Cash"
) -> dict:
    """
    Validates and persists a new expense record.

    Returns:
        {
          "status":  "success" | "error",
          "id":      int,            # new expense ID
          "budget":  {               # budget status post-add
            "spent":  float,
            "limit":  float,
            "pct":    float,
            "alert":  bool           # True if spent > 90% of limit
          },
          "message": str
        }

    Raises:
        ValueError: if any validation fails
    """
```

#### `edit_expense`
```python
def edit_expense(
    expense_id: int,
    **fields                     # any subset of add_expense params
) -> dict:
    """
    Updates an existing expense record.
    Returns same dict shape as add_expense.
    """
```

#### `delete_expense`
```python
def delete_expense(expense_id: int) -> dict:
    """
    Returns: {"status": "success" | "error", "message": str}
    """
```

#### `get_monthly_summary`
```python
def get_monthly_summary(year: int, month: int) -> pd.DataFrame:
    """
    Returns aggregated DataFrame:

    Columns: [category, total_amount, num_transactions, avg_amount]
    Index:   RangeIndex
    Sorted:  by total_amount descending
    """
```

#### `get_all_as_dataframe`
```python
def get_all_as_dataframe() -> pd.DataFrame:
    """
    Returns full expense history as DataFrame.

    Columns: [id, amount, category, date, description,
               payment_method, created_at]
    """
```

---

## 📦 `src.services.budget_service`

### Class: `BudgetService`

#### `set_budget`
```python
def set_budget(
    category: str,
    month: str,       # "YYYY-MM"
    limit: float
) -> dict:
    """
    Creates or updates a budget for a category+month.
    Returns: {"status": "success" | "error", "id": int}
    """
```

#### `check_budget`
```python
def check_budget(category: str, month: str) -> dict:
    """
    Returns:
        {
          "category": str,
          "spent":    float,
          "limit":    float,       # 0.0 if no budget set
          "pct":      float,       # percentage used (0–100+)
          "alert":    bool         # True when pct >= 90
        }
    """
```

#### `get_all_budgets`
```python
def get_all_budgets(month: str) -> list[dict]:
    """
    Returns list of check_budget dicts for all categories with budgets.
    """
```

---

## 📦 `src.services.report_service`

### Class: `ReportService`

#### `get_monthly_report`
```python
def get_monthly_report(year: int, month: int) -> dict:
    """
    Returns:
        {
          "period":        "2026-11",
          "total_income":  float,
          "total_expense": float,
          "net_savings":   float,
          "category_df":   pd.DataFrame,   # category breakdown
          "daily_df":      pd.DataFrame,   # daily trend
          "anomalies_df":  pd.DataFrame,   # flagged days
          "forecast":      dict,           # {category: predicted_amount}
          "budgets":       list[dict]
        }
    """
```

#### `get_trend_data`
```python
def get_trend_data(months: int = 6) -> pd.DataFrame:
    """
    Returns monthly totals for the last `months` months.

    Columns: [year_month, category, total_amount]
    """
```

#### `export_csv`
```python
def export_csv(year: int, month: int) -> str:
    """
    Returns: absolute file path to the exported CSV.
    """
```

---

## 📦 `src.ml.anomaly_detector`

### Class: `AnomalyDetector`

```python
class AnomalyDetector:
    def __init__(self, contamination: float = 0.05): ...
```

#### `fit`
```python
def fit(self, df: pd.DataFrame) -> "AnomalyDetector":
    """
    df must have columns: [date, amount]
    Returns self (fluent interface).
    """
```

#### `predict`
```python
def predict(self, df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns df with added columns:
      - is_anomaly:    bool
      - anomaly_score: float  (lower = more anomalous)
    """
```

#### `fit_predict`
```python
def fit_predict(self, df: pd.DataFrame) -> pd.DataFrame:
    """Fit then predict in one step."""
```

#### `save` / `load`
```python
def save(self, path: str) -> None: ...

@classmethod
def load(cls, path: str) -> "AnomalyDetector": ...
```

---

## 📦 `src.ml.forecaster`

### Class: `SpendingForecaster`

#### `fit`
```python
def fit(self, df: pd.DataFrame) -> "SpendingForecaster":
    """
    df must have columns: [date, amount, category]
    Fits one ARIMA model per category.
    """
```

#### `forecast`
```python
def forecast(self, steps: int = 1) -> dict[str, float]:
    """
    Returns: {"Food": 15200.0, "Transport": 3800.0, ...}
    """
```

---

## 📦 `src.visualization.chart_engine`

### Class: `ChartEngine`

#### `pie_chart`
```python
def pie_chart(
    series: pd.Series,              # index=category, values=amount
    title: str = "Spending by Category"
) -> plt.Figure: ...
```

#### `bar_chart`
```python
def bar_chart(
    series: pd.Series,
    title: str = "Category Totals",
    color: str = "#4ECDC4"
) -> plt.Figure: ...
```

#### `line_chart`
```python
def line_chart(
    series: pd.Series,              # DatetimeIndex, values=daily_total
    title: str = "Daily Spending Trend"
) -> plt.Figure: ...
```

#### `heatmap`
```python
def heatmap(
    pivot_df: pd.DataFrame,         # rows=month, cols=category, values=amount
    title: str = "Spending Heatmap"
) -> plt.Figure: ...
```

#### `budget_gauge`
```python
def budget_gauge(
    spent: float,
    limit: float,
    category: str
) -> go.Figure: ...               # Plotly Figure
```

#### `forecast_chart`
```python
def forecast_chart(
    actual: pd.Series,              # historical monthly totals
    forecast: dict[str, float],     # next month predictions per category
    title: str = "Spending Forecast"
) -> go.Figure: ...               # Plotly Figure
```

---

## 📦 `src.utils.validators`

```python
def validate_amount(value: Any) -> float:
    """Raises ValueError if invalid. Returns float."""

def validate_date(value: str) -> date:
    """Raises ValueError if invalid. Returns date object."""

def validate_category(name: str, session: Session) -> int:
    """Raises ValueError if not found. Returns category_id."""

def validate_description(text: str) -> str:
    """Raises ValueError if too long. Returns stripped string."""
```

---

## 📦 `src.utils.exporters`

```python
def to_csv(df: pd.DataFrame, directory: str, filename: str) -> str:
    """Writes CSV. Returns full file path."""

def to_pdf(report: dict, directory: str, filename: str) -> str:
    """Renders PDF summary. Returns full file path."""
```
