# GitHub Release Checklist & Safe Deployment Assessment

## Personal Expense Tracker with Data Visualization

This document details repository preparation, privacy audits, licensing recommendations, and a formal security assessment regarding public web deployment.

---

## 1. GitHub Release Preparation

### 1.1 Recommended Repository Metadata
- **Recommended Repository Name:** `personal-expense-tracker` or `personal-finance-tracker-python`
- **Short Description (About section):**
  > "A production-grade Personal Finance & Expense Tracker built with Python, SQLite, and Streamlit. Features automated CSV validation, budget alerts, interactive Plotly charts, and ReportLab PDF financial reporting."
- **Suggested Repository Topics (Tags):**
  `python`, `streamlit`, `sqlite`, `data-visualization`, `plotly`, `reportlab`, `financial-analytics`, `expense-tracker`, `budgeting`, `personal-finance`, `data-engineering`, `pdf-generation`
- **Recommended Initial Release Version:** `v1.0.0`
- **Suggested Initial Commit Message:**
  ```text
  feat: initial release v1.0.0 - personal expense tracker with data visualization

  - Complete transaction CRUD with calendar-aware date validation
  - Two-phase CSV import pipeline with duplicate detection and batch tracking
  - Budget management with utilization gauges and 80%/100% breach alerts
  - Deterministic analytics engine with zero-division and MoM edge case handling
  - 6 interactive Plotly financial charts with empty-state resilience
  - Publication-ready ReportLab PDF reports with NumberedCanvas pagination
  - Sanitized CSV data exports neutralizing spreadsheet formula injection
  - 7-page Streamlit web dashboard with deep-linking support
  - 337 automated unit, integration, and E2E tests (100% passing)
  - Synthetic 38-row demonstration dataset with zero personal data
  ```

---

## 2. Repository Privacy & Pre-Release Verification

Before publishing or creating a remote repository, the following checklist was verified:

| Checkpoint | Status | Verification Detail |
|------------|:------:|---------------------|
| **Production Database Cleanliness** | ✅ Verified | `data/expense_tracker.db` contains 8 seeded categories, 0 transactions, 0 budgets, 0 batches. |
| **No Private Financial Records** | ✅ Verified | Only `data/sample/demo_transactions.csv` exists; all records are 100% synthetic (fictional names, standard sample amounts). |
| **Secrets & Credentials Excluded** | ✅ Verified | `.streamlit/secrets.toml` and `.streamlit/credentials.toml` are explicitly ignored in `.gitignore`. |
| **Generated Exports Excluded** | ✅ Verified | `outputs/exports/*.csv` and `reports/transaction_reports/` are ignored in `.gitignore`. |
| **Database Binary Files Ignored** | ✅ Verified | `*.db`, `*.sqlite`, `*.sqlite3` are matched in `.gitignore`. |
| **Virtual Environments Excluded** | ✅ Verified | `.venv/`, `venv/`, `env/`, `.home/` are excluded in `.gitignore`. |
| **Bytecode & Test Caches Excluded** | ✅ Verified | `__pycache__/`, `.pytest_cache/`, `.cache/` are ignored. |
| **Minimal Dependencies** | ✅ Verified | `requirements.txt` contains only 7 active libraries (`pandas`, `numpy`, `plotly`, `streamlit`, `reportlab`, `pypdf`, `pytest`). Legacy unreferenced packages (`matplotlib`, `seaborn`, `scikit-learn`, `statsmodels`) removed. |

---

## 3. Open-Source License Options

Per instructions, **no license has been automatically selected or applied**. The user must choose an appropriate license before public release. Below are the three standard options recommended for this project:

1. **MIT License (Recommended for Portfolios):**
   - *Characteristics:* Extremely permissive. Allows anyone to view, fork, run, modify, and use the code for commercial or non-commercial purposes with minimal attribution.
   - *Best For:* Maximizing portfolio visibility, student showcases, placement evaluations, and technical interviews.
2. **Apache License 2.0:**
   - *Characteristics:* Permissive with explicit grants of patent rights and trademark restrictions. Requires documentation of modifications.
   - *Best For:* Projects intended for broader open-source contribution or enterprise utility.
3. **GNU General Public License v3 (GPLv3):**
   - *Characteristics:* Strong copyleft. Any derivative work or modified distribution must also be open-sourced under GPLv3.
   - *Best For:* Ensuring that the code and any improvements remain permanently open-source.

---

## 4. Safe Deployment Assessment

### 4.1 Evaluation of Direct Public Deployment (e.g. Streamlit Community Cloud)

> ⚠️ **CRITICAL FINDING: The application in its current architecture SHOULD NOT be deployed publicly with write-enabled SQLite storage.**

#### Analysis of Risks:
1. **Lack of User Authentication:**
   - The current application does not implement user login (OAuth2, JWT, or session credentials).
   - If deployed directly to a public URL (e.g., `share.streamlit.io`), anyone with the link can view, insert, edit, or delete stored financial transactions.
2. **Shared SQLite Ledger (No Tenant Isolation):**
   - SQLite is a single local file. On Streamlit Community Cloud, all concurrent web visitors share the same server process and the same SQLite database file.
   - Visitor A would see transactions entered by Visitor B, creating a severe data privacy violation if users enter real personal data.
3. **Ephemeral Ephemerality on Container Restarts:**
   - Streamlit Community Cloud containers are ephemeral. Any local SQLite database written to disk is destroyed when the container sleeps, restarts, or deploys a new commit.
4. **Concurrent Write Lockouts:**
   - SQLite uses file-level locking for writes. Multiple simultaneous public users submitting transactions or importing CSVs will encounter `sqlite3.OperationalError: database is locked`.

---

## 5. Recommended Safe Deployment Approaches

If public deployment is desired for portfolio demonstrations, one of the following two safe architectures should be adopted:

### Option A: Read-Only Portfolio Demo Mode (Recommended for Streamlit Cloud)
- **Concept:** Configure the cloud application to point to a pre-populated, read-only SQLite database loaded with the synthetic demo dataset (`data/sample/demo_transactions.csv`).
- **Implementation:**
  - Disable or hide the "Save", "Update", "Delete", and "Confirm Import" buttons in the cloud instance (or set an environment variable `DEMO_MODE=True`).
  - Visitors can freely interact with filters, explore the 6 Plotly charts, inspect budget utilization, test report generation, and download sample PDFs and CSVs without corrupting data or sharing personal transactions.

### Option B: Ephemeral Per-Session Database (In-Memory or `/tmp`)
- **Concept:** When a new user session begins in Streamlit, initialize an independent, isolated SQLite database in `tempfile.NamedTemporaryFile` or SQLite in-memory (`:memory:`) tied exclusively to `st.session_state["db_path"]`.
- **Implementation:**
  - Automatically populate the session database with the synthetic demo dataset on first load.
  - The visitor can add, edit, import, and delete transactions with full functionality.
  - No data is shared across users; when the visitor closes their browser tab, their session database is automatically garbage-collected and destroyed.

---

## 6. Pre-Push Operational Rules
1. **Do not create a remote repository or push commits** without explicit confirmation from the repository owner.
2. **Keep production database empty** (`data/expense_tracker.db`) when creating initial git commits.
3. **Select and create `LICENSE`** only after user approval.
