# 01 — Project Overview
## Personal Expense Tracker with Data Visualization

---

## 🎯 Project Goal

Build a **Python-based Personal Expense Tracker** that allows users to:
- Record, categorize, and manage their daily expenses and income.
- Persist data reliably in a local SQLite database.
- Visualize spending patterns through interactive/static charts.
- Receive **ML-powered insights**: anomaly detection, spending forecasts, and category-level predictions.

---

## 🧩 Core Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | **Expense Entry** | Add expenses with amount, category, date, description |
| 2 | **Income Entry** | Log income sources and amounts |
| 3 | **Category Management** | CRUD on custom spending categories |
| 4 | **Budget Limits** | Set per-category monthly budgets with alerts |
| 5 | **Data Persistence** | SQLite database via SQLAlchemy ORM |
| 6 | **Data Visualization** | Bar, pie, line, heatmap charts via Matplotlib/Plotly |
| 7 | **Summary Reports** | Weekly/monthly/annual spending summaries |
| 8 | **ML: Anomaly Detection** | Detect unusually high expenses using Isolation Forest |
| 9 | **ML: Forecast** | Predict next-month spending per category using Linear Regression / ARIMA |
| 10 | **Export** | Export data to CSV / PDF report |
| 11 | **UI** | Tkinter GUI or Streamlit web dashboard (TBD) |

---

## 🛠️ Technology Stack

| Layer | Technology | Version (target) | Purpose |
|-------|-----------|-----------------|---------|
| **Language** | Python | 3.11+ | Core runtime |
| **Database** | SQLite | Built-in | Local persistent storage |
| **ORM** | SQLAlchemy | 2.x | DB abstraction & schema management |
| **Data Processing** | Pandas | 2.x | DataFrame operations, aggregations |
| **Numerical** | NumPy | 1.x / 2.x | Array math, statistics |
| **Visualization** | Matplotlib | 3.x | Static charts |
| **Visualization** | Plotly | 5.x | Interactive charts |
| **ML** | Scikit-learn | 1.x | Isolation Forest, Linear Regression, preprocessing |
| **ML (Time-series)** | Statsmodels | 0.14+ | ARIMA for forecasting |
| **UI** | Streamlit | 1.x | Web-based dashboard (preferred) |
| **Testing** | Pytest | 7.x | Unit & integration tests |
| **Serialization** | JSON / CSV | stdlib | Data export |

---

## 📏 Project Scope

### In Scope
- Single-user, offline, local application.
- Monthly-level budget tracking and reporting.
- Two ML tasks: anomaly detection + spending forecast.
- Visualization dashboard with at least 5 chart types.

### Out of Scope (v1)
- Multi-user support / authentication.
- Cloud sync or remote database.
- Mobile app.
- Real-time bank feed integration.

---

## 📂 Project Conventions

| Convention | Rule |
|-----------|------|
| **Date format** | `YYYY-MM-DD` (ISO 8601) |
| **Currency** | INR (₹) — configurable in `config.py` |
| **Category names** | Title-cased strings, stored in DB |
| **Module naming** | `snake_case` for files, `PascalCase` for classes |
| **Config** | All magic numbers / paths in `src/config.py` |
| **Logging** | Python `logging` module, written to `logs/app.log` |
| **Tests** | One test file per module under `tests/` |

---

## 🗓️ Development Phases

```
Phase 1 → Database layer + Data models         (Session 1-2)
Phase 2 → Data ingestion & processing          (Session 2-3)
Phase 3 → Visualization module                 (Session 3-4)
Phase 4 → ML: Anomaly Detection                (Session 4-5)
Phase 5 → ML: Forecasting                      (Session 5-6)
Phase 6 → UI / Dashboard                       (Session 6-7)
Phase 7 → Export, testing, polish              (Session 7-8)
```
