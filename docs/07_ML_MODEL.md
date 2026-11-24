# 07 — ML Model Documentation
## Personal Expense Tracker with Data Visualization

---

## 🤖 Overview of ML in This Project

Two ML tasks are implemented:

| Task | Algorithm | Library | Purpose |
|------|-----------|---------|---------|
| **Anomaly Detection** | Isolation Forest | scikit-learn | Flag unusually high spending days |
| **Spending Forecast** | ARIMA | statsmodels | Predict next month's spend per category |

---

---

# Task 1: Anomaly Detection

## 🧠 Algorithm: Isolation Forest

### Intuition
Isolation Forest isolates anomalies by randomly splitting data with decision trees. Anomalies, being few and extreme, are isolated in **fewer splits** (shorter path length). Normal points require many splits (longer paths).

```
Path length ≈ short  →  anomaly (easy to isolate)
Path length ≈ long   →  normal  (hard to isolate)
```

### Hyperparameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `n_estimators` | 100 | Number of isolation trees |
| `contamination` | 0.05 | Expected fraction of anomalies (5%) |
| `max_samples` | `'auto'` | Subsample size per tree |
| `random_state` | 42 | Reproducibility |

### Feature Engineering

Before training, the raw `expenses` DataFrame is transformed:

```
Raw: [date, amount, category]

Engineered features:
  1. daily_total      = SUM(amount) per date
  2. rolling_7d_avg   = 7-day rolling mean of daily_total
  3. rolling_7d_std   = 7-day rolling std
  4. z_score          = (daily_total - rolling_7d_avg) / rolling_7d_std
  5. day_of_week      = date.weekday()   (0=Mon … 6=Sun)
  6. is_weekend       = day_of_week ∈ {5, 6}
  7. month_of_year    = date.month

Feature matrix X shape: (n_days, 7)
```

### Training Pipeline

```
Step 1: Load all historical expense records → DataFrame

Step 2: Aggregate to daily totals
        df_daily = df.groupby('date')['amount'].sum().reset_index()

Step 3: Feature engineering (above)

Step 4: Handle NaN (first 6 days have no rolling stats)
        → Fill NaN with column means

Step 5: Fit IsolationForest
        model.fit(X)

Step 6: Cache trained model in memory
        self._model = model
        self._is_fitted = True
```

### Prediction / Inference

```
Step 1: Take new DataFrame (can be a single day or a date range)

Step 2: Apply same feature engineering

Step 3: model.predict(X) → [-1 = anomaly, 1 = normal]

Step 4: model.decision_function(X) → anomaly scores (lower = more anomalous)

Step 5: Attach results:
        df['is_anomaly']    = predictions == -1
        df['anomaly_score'] = decision_scores
```

### Model Evaluation Metrics

> Used on the **synthetic dataset** (which has ground-truth `is_anomaly` labels):

| Metric | Expected Range |
|--------|---------------|
| Precision | ≥ 0.70 |
| Recall | ≥ 0.60 |
| F1 Score | ≥ 0.65 |

---

---

# Task 2: Spending Forecast

## 🧠 Algorithm: ARIMA (AutoRegressive Integrated Moving Average)

### Intuition
ARIMA models a time series by combining three components:

```
AR(p)  → uses p past values to predict the next value
         (AutoRegressive: "my spend this month depends on past months")

I(d)   → differences the series d times to make it stationary
         (Integrated: "removes trends so the mean is stable")

MA(q)  → uses q past forecast errors to correct future predictions
         (Moving Average: "correct for recent mistakes in my forecasts")
```

### Model Order: ARIMA(p=2, d=1, q=1)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `p` | 2 | Use last 2 months' spending |
| `d` | 1 | First-difference to remove trend |
| `q` | 1 | Correct for last 1 month's forecast error |

> These are starting values. Optimal (p, d, q) can be auto-selected using AIC minimization in `auto_arima` (pmdarima library) if installed.

### Training Pipeline

```
Step 1: Load historical expenses → DataFrame

Step 2: Aggregate to monthly totals per category
        df_monthly = df.groupby(['year_month', 'category'])['amount'].sum()

        Result shape:
        year_month  category   amount
        2025-01     Food       12400
        2025-01     Transport   3200
        ...

Step 3: For each category, extract time series
        series = df_monthly[category]   → pd.Series with DatetimeIndex

Step 4: Check stationarity (ADF test)
        adf_result = adfuller(series)
        → if p-value > 0.05: apply differencing (d=1)

Step 5: Fit ARIMA model per category
        model = ARIMA(series, order=(p, d, q))
        result = model.fit()
        self._models[category] = result

Step 6: Cache all fitted models
```

### Forecast / Inference

```
Step 1: For each category:
        forecast = self._models[category].forecast(steps=1)
        predicted_amount = forecast.iloc[0]

Step 2: Apply floor: max(predicted_amount, 0)
        (can't have negative spending)

Step 3: Return dict:
        {
          "Food":          15200.50,
          "Transport":      3800.00,
          "Shopping":       9500.00,
          ...
        }
```

### Model Evaluation Metrics

| Metric | Description | Expected Range |
|--------|-------------|---------------|
| MAE | Mean Absolute Error (₹) | < ₹1,500 per category |
| MAPE | Mean Absolute Percentage Error | < 20% |
| RMSE | Root Mean Squared Error | < ₹2,000 |

> Evaluation is done by **walk-forward validation** on the synthetic dataset:
> - Train on months 1–18, predict month 19.
> - Train on months 1–19, predict month 20.
> - Average error across held-out months.

---

## 🔄 Model Lifecycle

```
App startup
  │
  ├─ [< 3 months real data] → load pre-trained model from synthetic data
  │
  └─ [≥ 3 months real data] → retrain on real data
                                (triggered once per month automatically)

User uses dashboard
  │
  └─ Anomaly: fit_predict() called on each dashboard load (fast, seconds)
     Forecast: forecast() called on "Reports" page load (cached monthly)
```

---

## 💾 Model Persistence

| Item | Storage Location | Format |
|------|-----------------|--------|
| Anomaly detector | `data/models/anomaly_model.pkl` | Python pickle |
| ARIMA per category | `data/models/arima_{category}.pkl` | statsmodels save |
| Feature scaler | `data/models/scaler.pkl` | sklearn pickle |
| Last trained date | `data/models/metadata.json` | JSON |

---

## 🧪 Notebooks

| Notebook | Purpose |
|----------|---------|
| `notebooks/01_eda.ipynb` | Exploratory data analysis on synthetic data |
| `notebooks/02_anomaly_training.ipynb` | Train, evaluate, tune IsolationForest |
| `notebooks/03_arima_forecast.ipynb` | Train, evaluate, tune ARIMA per category |
