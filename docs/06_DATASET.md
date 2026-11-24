# 06 — Dataset
## Personal Expense Tracker with Data Visualization

---

## 📊 Dataset Strategy

This project uses **two data sources**:

| Source | Type | Used For |
|--------|------|----------|
| **User-entered data** | Live (runtime) | Primary data: real expenses & income the user logs |
| **Synthetic seed dataset** | Generated (Python) | ML model training, EDA, testing, demo mode |

---

## 🏷️ Primary Dataset: User Expenses (Runtime)

This is the live database the user populates over time.

### Schema (what gets stored per record)

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `amount` | float | `450.00` | In ₹ |
| `category` | string | `"Food"` | From predefined list |
| `date` | date | `2026-11-23` | ISO 8601 |
| `description` | string | `"Swiggy lunch"` | Optional free text |
| `payment_method` | string | `"UPI"` | Cash / Card / UPI / Net Banking |
| `created_at` | datetime | `2026-11-23T09:45:00` | Auto-generated |

### Sample Records

| id | amount | category | date | description | payment_method |
|----|--------|----------|------|-------------|---------------|
| 1 | 450.00 | Food | 2026-11-01 | Swiggy lunch | UPI |
| 2 | 150.00 | Transport | 2026-11-02 | Auto rickshaw | Cash |
| 3 | 2500.00 | Shopping | 2026-11-05 | Shoes from Myntra | Card |
| 4 | 80.00 | Food | 2026-11-07 | Tea & snacks | Cash |
| 5 | 1200.00 | Entertainment | 2026-11-10 | Movie tickets | Card |
| 6 | 500.00 | Healthcare | 2026-11-15 | Pharmacy | UPI |
| 7 | 1800.00 | Utilities | 2026-11-20 | Electricity bill | Net Banking |

---

## 🧪 Synthetic Dataset: ML Training Data

Since users start fresh with an empty database, we generate a synthetic dataset to:
1. Train the ML models before real data accumulates.
2. Run EDA notebooks.
3. Seed demo mode.

### Generation Method

```python
# notebooks/generate_synthetic_data.py
import numpy as np, pandas as pd, random
from datetime import date, timedelta

CATEGORIES   = ["Food", "Transport", "Shopping", "Entertainment",
                "Healthcare", "Utilities", "Education", "Other"]
TYPICAL_SPEND = {           # mean daily spend per category (₹)
    "Food":          400,
    "Transport":     120,
    "Shopping":      800,
    "Entertainment": 600,
    "Healthcare":    200,
    "Utilities":     100,
    "Education":     300,
    "Other":         150,
}
STD_RATIO    = 0.3          # std = 30% of mean
ANOMALY_PROB = 0.03         # 3% chance of an anomaly spike (5× mean)
START_DATE   = date(2025, 1, 1)
END_DATE     = date(2026, 10, 31)   # ~22 months of history
```

### Dataset Statistics (generated)

| Property | Value |
|----------|-------|
| Date range | Jan 2025 – Oct 2026 (22 months) |
| Total records (approx.) | ~6,000 expense rows |
| Categories | 8 |
| Anomaly records (injected) | ~180 (3%) |
| Monthly totals range | ₹8,000 – ₹35,000 |
| Distribution | Log-normal per category |

### Column Descriptions (Synthetic CSV)

| Column | Type | Description |
|--------|------|-------------|
| `date` | str `YYYY-MM-DD` | Expense date |
| `amount` | float | Expense amount in ₹ |
| `category` | str | One of 8 categories |
| `payment_method` | str | Randomly assigned |
| `is_synthetic` | bool | Always `True` — flag for filtering |
| `is_anomaly` | bool | Ground truth for anomaly evaluation |

---

## 📁 Data File Locations

```
data/
├── raw/
│   └── synthetic_expenses.csv        ← Generated synthetic dataset
├── processed/
│   ├── monthly_totals.csv            ← Aggregated per month/category
│   └── anomaly_labels.csv            ← True labels for model eval
└── exports/                          ← User-exported files (runtime)
    └── expense_YYYY_MM.csv
```

---

## 🔀 Transition: Synthetic → Real Data

| Condition | Action |
|-----------|--------|
| User has < 3 months of data | Use synthetic data to train ML models |
| User has ≥ 3 months of data | Use real data; retrain models monthly |
| Mix mode | Concatenate real + synthetic (synthetic flagged) |

The transition is handled automatically in `ml/anomaly_detector.py` and `ml/forecaster.py` by checking the number of months available in the DB.

---

## 📈 Data Quality Rules

| Rule | Check |
|------|-------|
| No future dates | `date <= today` |
| No negative amounts | `amount > 0` |
| Valid category | Must exist in `categories` table |
| No duplicates | Checked by (amount + category + date + description) hash |
| Reasonable amount | `amount <= 10,000,000` (1 crore max) |
