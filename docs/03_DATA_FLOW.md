# 03 — Data Flow
## Personal Expense Tracker with Data Visualization

---

## 🔄 High-Level Data Flow

```
[User Input]
     │
     ▼
[UI Layer]  ──validates──►  [Validators]
     │
     ▼
[Service Layer]
     │
     ├──► [ORM Repository] ──► [SQLite DB]  ◄── (persist & retrieve)
     │
     ├──► [Pandas DataFrame] ──► [ML Layer]   ──► [Predictions / Flags]
     │
     └──► [Pandas DataFrame] ──► [Viz Layer]  ──► [Figures / Charts]
                                                        │
                                                        ▼
                                               [Dashboard / Export]
```

---

## 📥 Data Entry Flow (Write Path)

```
Step 1: User fills expense form
        Fields: amount, category, date, description, payment_method

Step 2: UI calls ExpenseService.add_expense(**fields)

Step 3: validators.validate_expense(fields)
        ├─ Check: amount > 0
        ├─ Check: date is valid ISO format
        ├─ Check: category exists in DB
        └─ Check: description length ≤ 255 chars

Step 4: ORM creates Expense object
        expense = Expense(
            amount     = 500.0,
            category   = "Food",
            date       = date(2026, 11, 23),
            description= "Lunch at office",
            created_at = datetime.utcnow()
        )

Step 5: ExpenseRepository.add(expense)
        └─ session.add(expense) → session.commit()

Step 6: BudgetService.check_budget(category="Food", month="2026-11")
        └─ Queries total spent this month vs budget limit
        └─ Returns (spent=3200, limit=5000, alert=False)

Step 7: Service returns response dict → UI renders feedback
```

---

## 📤 Data Retrieval Flow (Read Path)

```
Step 1: User requests "Monthly Report — November 2026"

Step 2: ReportService.get_monthly_report(year=2026, month=11)

Step 3: ExpenseRepository.get_by_month(year, month)
        └─ SQL: SELECT * FROM expenses WHERE strftime('%Y-%m', date) = '2026-11'
        └─ Returns: List[Expense ORM objects]

Step 4: Service converts ORM objects → Pandas DataFrame
        df = pd.DataFrame([e.__dict__ for e in expenses])

Step 5: Aggregation Pipeline
        ├─ df.groupby('category')['amount'].sum()   → category totals
        ├─ df.groupby('date')['amount'].sum()        → daily trend
        └─ df['amount'].describe()                  → statistics

Step 6a: ML Pipeline (see §ML Data Flow below)
Step 6b: Visualization Pipeline (see §Viz Data Flow below)

Step 7: Merged result dict returned to UI for rendering
```

---

## 🤖 ML Data Flow

```
Input: DataFrame with columns [date, amount, category]

──────────────────────────────────────────────────────────
ANOMALY DETECTION FLOW
──────────────────────────────────────────────────────────
DataFrame
  │
  ▼
Feature Engineering
  ├─ daily_total     = df.groupby('date')['amount'].sum()
  ├─ rolling_7d_avg  = daily_total.rolling(7).mean()
  └─ z_score         = (daily_total - mean) / std

  ▼
IsolationForest(n_estimators=100, contamination=0.05)
  .fit(X)   ← X = [[daily_total, rolling_avg, z_score], ...]
  .predict(X)   → [-1 = anomaly, 1 = normal]

  ▼
Output: DataFrame with extra column [is_anomaly: bool]
        Returns to Service → UI highlights anomalous days

──────────────────────────────────────────────────────────
FORECAST FLOW
──────────────────────────────────────────────────────────
Historical monthly totals per category
  │
  ▼
Time-series preparation
  └─ monthly_series = df.groupby(['year_month','category'])['amount'].sum()

  ▼
Per-category ARIMA(p,d,q) model
  .fit(series)
  .forecast(steps=1)   → predicted amount for next month

  ▼
Output: Dict { category → predicted_amount }
        Returns to Service → UI shows forecast card
```

---

## 📊 Visualization Data Flow

```
Input: Aggregated DataFrame from Service Layer

──────────────────────────────────────────────────────────
CHART RENDERING FLOW
──────────────────────────────────────────────────────────
Aggregated DataFrame
  │
  ├──► ChartEngine.pie_chart(category_totals)
  │      └─ matplotlib.pyplot.pie(...)  → Figure
  │
  ├──► ChartEngine.bar_chart(category_totals)
  │      └─ matplotlib.pyplot.bar(...)  → Figure
  │
  ├──► ChartEngine.line_chart(daily_trend)
  │      └─ matplotlib.pyplot.plot(...)  → Figure
  │
  ├──► ChartEngine.heatmap(day_x_category_pivot)
  │      └─ seaborn.heatmap(...)  → Figure
  │
  └──► ChartEngine.forecast_chart(actual_series, forecast_point)
         └─ plotly.graph_objects.Figure(...)  → Plotly Figure

All Figures passed to Presentation Layer
  └─ Streamlit: st.pyplot(fig) or st.plotly_chart(fig)
```

---

## 💾 Database I/O Summary

| Operation | Trigger | SQL Pattern |
|-----------|---------|-------------|
| INSERT expense | `add_expense()` | `INSERT INTO expenses ...` |
| INSERT income | `add_income()` | `INSERT INTO incomes ...` |
| SELECT monthly | `get_monthly_report()` | `WHERE strftime('%Y-%m', date) = ?` |
| SELECT category | `get_by_category()` | `WHERE category_id = ?` |
| UPDATE budget | `set_budget()` | `UPDATE budgets SET limit = ? WHERE ...` |
| DELETE expense | `delete_expense()` | `DELETE FROM expenses WHERE id = ?` |
| Aggregate | `get_summary()` | `GROUP BY category`, `SUM(amount)` |

---

## 🔁 Export Data Flow

```
User clicks "Export CSV"
  → ReportService.export_csv(year, month)
    → Queries DB → DataFrame
    → df.to_csv("exports/expense_2026_11.csv", index=False)
    → returns file path → UI shows download link / opens folder
```
