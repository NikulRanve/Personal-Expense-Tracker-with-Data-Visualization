# 04 — Modules Reference
## Personal Expense Tracker with Data Visualization

---

## 📌 Module Map

```
src/
├── config.py
├── main.py
├── models/
│   ├── __init__.py
│   ├── base.py
│   ├── expense.py
│   ├── income.py
│   ├── category.py
│   └── budget.py
├── repositories/
│   ├── __init__.py
│   ├── expense_repository.py
│   ├── income_repository.py
│   ├── category_repository.py
│   └── budget_repository.py
├── services/
│   ├── __init__.py
│   ├── expense_service.py
│   ├── budget_service.py
│   └── report_service.py
├── ml/
│   ├── __init__.py
│   ├── anomaly_detector.py
│   └── forecaster.py
├── visualization/
│   ├── __init__.py
│   └── chart_engine.py
├── utils/
│   ├── __init__.py
│   ├── validators.py
│   ├── logger.py
│   └── exporters.py
└── pages/              ← Streamlit pages
    ├── dashboard.py
    ├── add_expense.py
    ├── reports.py
    └── settings.py
```

---

## 🔩 Module Details

---

### `config.py`
**Role:** Single source of truth for all app-wide constants.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `DATABASE_URL` | str | `"sqlite:///data/expenses.db"` | SQLAlchemy connection string |
| `CURRENCY_SYMBOL` | str | `"₹"` | Display currency |
| `DATE_FORMAT` | str | `"%Y-%m-%d"` | Standard date format |
| `LOG_FILE` | str | `"logs/app.log"` | Log output path |
| `ANOMALY_CONTAMINATION` | float | `0.05` | IsolationForest contamination ratio |
| `FORECAST_STEPS` | int | `1` | Months ahead to forecast |
| `DEFAULT_CATEGORIES` | list | `["Food", "Transport", ...]` | Seed categories |

---

### `models/base.py`
**Role:** Declares the SQLAlchemy `Base` and shared `TimestampMixin`.

```python
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(onupdate=datetime.utcnow)
```

---

### `models/expense.py`
**Role:** ORM model for the `expenses` table.

| Column | Type | Constraint | Description |
|--------|------|-----------|-------------|
| `id` | Integer | PK, AutoIncrement | Unique expense ID |
| `amount` | Float | NOT NULL, > 0 | Expense amount |
| `category_id` | Integer | FK → categories.id | Linked category |
| `date` | Date | NOT NULL | Expense date |
| `description` | String(255) | nullable | Free-text note |
| `payment_method` | String(50) | nullable | Cash/Card/UPI/etc |
| `created_at` | DateTime | auto | Record creation time |

---

### `models/income.py`
**Role:** ORM model for the `incomes` table.

| Column | Type | Constraint |
|--------|------|-----------|
| `id` | Integer | PK |
| `amount` | Float | NOT NULL |
| `source` | String(100) | NOT NULL |
| `date` | Date | NOT NULL |
| `note` | String(255) | nullable |

---

### `models/category.py`
**Role:** Lookup table for expense categories.

| Column | Type | Constraint |
|--------|------|-----------|
| `id` | Integer | PK |
| `name` | String(50) | UNIQUE, NOT NULL |
| `icon` | String(10) | nullable (emoji) |
| `color` | String(7) | nullable (hex color) |

---

### `models/budget.py`
**Role:** Monthly budget limits per category.

| Column | Type | Constraint |
|--------|------|-----------|
| `id` | Integer | PK |
| `category_id` | Integer | FK → categories.id |
| `limit_amount` | Float | NOT NULL |
| `month` | String(7) | `YYYY-MM` format |

---

### `repositories/expense_repository.py`
**Role:** All DB CRUD operations for expenses.

| Method | Input | Output | Description |
|--------|-------|--------|-------------|
| `add(expense)` | `Expense` obj | `Expense` | Persist new record |
| `get_by_id(id)` | int | `Expense \| None` | Fetch single record |
| `get_by_month(year, month)` | int, int | `List[Expense]` | All expenses in month |
| `get_by_category(category_id)` | int | `List[Expense]` | Filter by category |
| `update(expense)` | `Expense` obj | `Expense` | Save changes |
| `delete(id)` | int | bool | Remove record |
| `get_all()` | — | `List[Expense]` | All records |

---

### `services/expense_service.py`
**Role:** Orchestrates expense business logic.

| Method | Description |
|--------|-------------|
| `add_expense(amount, category, date, ...)` | Validates + persists + checks budget |
| `edit_expense(id, **fields)` | Validates + updates record |
| `delete_expense(id)` | Removes record by ID |
| `get_monthly_summary(year, month)` | Returns aggregated DataFrame |
| `get_all_as_dataframe()` | Full history as DataFrame |

---

### `services/budget_service.py`
**Role:** Budget management and alert logic.

| Method | Description |
|--------|-------------|
| `set_budget(category, month, limit)` | Create/update budget row |
| `check_budget(category, month)` | Returns `{spent, limit, pct, alert}` |
| `get_all_budgets(month)` | All budgets for a month |

---

### `services/report_service.py`
**Role:** Generates aggregated reports by calling Repositories + ML + Viz.

| Method | Description |
|--------|-------------|
| `get_monthly_report(year, month)` | Full report dict for a month |
| `get_category_breakdown(year, month)` | Category-level totals DataFrame |
| `get_trend_data(months=6)` | Multi-month trend DataFrame |
| `export_csv(year, month)` | Writes CSV, returns file path |

---

### `ml/anomaly_detector.py`
**Role:** Detect abnormal spending days using IsolationForest.

| Method | Description |
|--------|-------------|
| `fit(df)` | Train model on historical DataFrame |
| `predict(df)` | Returns DataFrame with `is_anomaly` column |
| `fit_predict(df)` | Fit and return predictions in one step |

**Inputs:** DataFrame with columns `[date, amount]`
**Outputs:** Same DataFrame + `is_anomaly: bool` column

---

### `ml/forecaster.py`
**Role:** Predict next month's spending per category using ARIMA.

| Method | Description |
|--------|-------------|
| `fit(df)` | Fit one ARIMA model per category |
| `forecast()` | Return dict `{category: predicted_amount}` |

**Inputs:** DataFrame with columns `[year_month, category, amount]`
**Outputs:** `Dict[str, float]`

---

### `visualization/chart_engine.py`
**Role:** Produce all charts as Figure objects.

| Method | Input | Output |
|--------|-------|--------|
| `pie_chart(series)` | `pd.Series` (category totals) | `plt.Figure` |
| `bar_chart(series)` | `pd.Series` | `plt.Figure` |
| `line_chart(series)` | `pd.Series` (date index) | `plt.Figure` |
| `heatmap(pivot_df)` | `pd.DataFrame` | `plt.Figure` |
| `budget_gauge(spent, limit)` | floats | `plotly.Figure` |
| `forecast_chart(actual, forecast)` | Series, dict | `plotly.Figure` |

---

### `utils/validators.py`
**Role:** Pure validation functions, raise `ValueError` on failure.

| Function | Checks |
|----------|--------|
| `validate_amount(v)` | Is float, > 0, ≤ 10,000,000 |
| `validate_date(d)` | Is string, matches `%Y-%m-%d`, not future |
| `validate_category(c, session)` | Category exists in DB |
| `validate_description(d)` | length ≤ 255, no control chars |

---

### `utils/exporters.py`
**Role:** File export utilities.

| Function | Output |
|----------|--------|
| `to_csv(df, path)` | Writes `path/expenses_YYYY_MM.csv` |
| `to_pdf(report_dict, path)` | Writes PDF summary with tables |

---

### `utils/logger.py`
**Role:** Configure and return a module-level logger.

```python
logger = get_logger(__name__)
logger.info("Expense added: ₹500 → Food")
logger.warning("Budget 90% reached: Food")
logger.error("DB write failed: ...")
```
