# Placement & Portfolio Project Guide

## Personal Expense Tracker with Data Visualization

A comprehensive technical reference designed for technical interviews, placement presentations, code walkthroughs, and portfolio reviews.

---

## 1. 30-Second Elevator Pitch

> "I built a production-grade Personal Expense Tracker and Financial Analytics web application using Python, SQLite, and Streamlit. It solves the error-prone nature of manual spreadsheet budgeting by providing automated data ingestion with duplicate detection, real-time KPI analytics, dynamic Plotly visualizations, and publication-ready ReportLab PDF financial statements. The system is hardened against SQL injection, CSV formula injection, and XSS, backed by an automated test suite of 337 tests achieving 100% pass rates across unit, integration, and end-to-end workflows."

---

## 2. 2-Minute Technical Deep Dive

> "As software engineers, we often see personal finance apps that either depend on fragile spreadsheets or over-engineered cloud microservices that expose private financial credentials. I engineered this project to bridge that gap with a clean, privacy-first, offline-capable architecture.
>
> The system follows a modular 5-tier architecture:
> 1. A responsive **Streamlit presentation layer** organized into 7 distinct functional views.
> 2. A **business logic layer** managing transaction lifecycle, multi-category budgeting, and import batching.
> 3. A robust **data ingestion and cleaning pipeline** that handles multi-encoding CSV loading (`UTF-8`, `Latin-1`, `UTF-8-SIG`), whitespace sanitization, date normalization, and two-phase duplicate detection.
> 4. A **deterministic analytics engine** computing income/expense totals, net savings, category allocations, payment method shares, and month-over-month trends with mathematical edge-case guards such as division-by-zero protection.
> 5. A **SQLite persistence layer** leveraging strict foreign key enforcement (`PRAGMA foreign_keys = ON`), schema integrity triggers, and 100% parameterised SQL queries.
>
> For output, the system features 6 interactive Plotly charts and a ReportLab PDF reporting engine that uses a custom two-pass `NumberedCanvas` to dynamically render headers, footers, and page counts ('Page X of Y').
>
> Crucially, security and data integrity were designed upfront: user strings exported to CSV are prefixed with single quotes if they contain spreadsheet execution characters (`=`, `+`, `-`, `@`, `\t`), HTML rendering explicitly escapes user input against XSS, and database triggers strictly enforce batch accounting invariants. The entire codebase is backed by 337 automated tests with zero external production database mutations."

---

## 3. Problem Statement & Motivation

Personal finance management frequently fails due to three fundamental issues:
1. **Spreadsheet Fragility:** Manual data entry in Excel leads to formula corruption, broken date formatting, and duplicate transaction entries.
2. **Privacy Concerns:** Commercial financial trackers require connecting live bank credentials to third-party cloud servers, posing significant security and privacy risks.
3. **Lack of Actionable Insights:** Raw transaction lists fail to communicate whether spending is approaching category budget limits before the month ends.

This application provides an offline, local-first, privacy-respecting financial dashboard that automates data validation, enforces strict budgeting rules, and delivers visual clarity.

---

## 4. Technical Architecture

The codebase follows a strict **unidirectional dependency chain**:

```
Presentation (Streamlit UI)
       │
       ▼
Business Services (Expense, Budget, Import Service)
       │
       ▼
Data Cleaning & Analytics Engine
       │
       ▼
Persistence Layer (SQLite Database)
       │
       ▼
Visualizations (Plotly) & Reporting (ReportLab PDF / CSV)
```

- **Separation of Concerns:** UI files in `src/ui/` contain zero direct SQL statements; all data operations route through business managers (`expense_manager.py`, `budget_manager.py`, `import_service.py`).
- **Stateless Analytics:** `src/analytics.py` functions operate purely on query parameters or in-memory DataFrames, enabling trivial unit testing and reuse across both the web dashboard and PDF reports.
- **Cross-Platform Compatibility:** The UI gracefully detects when binary dependencies like `pyarrow` are unavailable (such as on Windows ARM64) and falls back to safe HTML table rendering with `escape=True`.

---

## 5. Important Implementation Decisions

| Decision | Alternative Considered | Engineering Justification |
|----------|------------------------|---------------------------|
| **Direct SQLite via `sqlite3`** | SQLAlchemy ORM | Eliminates heavy ORM overhead, provides full visibility over query performance, ensures explicit parameterisation, and allows custom SQLite triggers. |
| **Plotly** | Matplotlib / Seaborn | Enables interactive tooltips, hover states, dynamic legend toggling, responsive resizing, and clean integration into Streamlit without server-side image re-rendering. |
| **ReportLab + NumberedCanvas** | WeasyPrint / wkhtmltopdf | Zero external binary or headless browser dependencies; pure Python cross-platform PDF generation capable of exact point-level layout control and dynamic "Page X of Y" pagination. |
| **Font-Safe Currency (`Rs.`) in PDF** | Unicode Rupee Symbol (`₹`) | Standard ReportLab Type 1 fonts (Helvetica) use `WinAnsiEncoding`, which crashes when attempting to encode Unicode `₹`. Using `Rs. {:,.2f}` guarantees 100% crash-free PDF compilation across all operating systems. |
| **Two-Phase CSV Import** | Instant Blind Import | Users review validation summaries, invalid rows, and detected duplicate candidates *before* any database commit occurs, preventing accidental ledger corruption. |

---

## 6. Database Design & Schema Explanation

The schema is normalized to 3NF across 4 relational tables:

```
categories (1) ───< transactions (N)
categories (1) ───< budgets (N)
import_batches (1) ───< transactions (N)
```

1. **`categories`:**
   - Primary key `id INTEGER`, unique category `name TEXT`, `type TEXT CHECK (type IN ('Expense', 'Income'))`.
   - Seeded with 8 canonical categories (6 Expense, 2 Income).
2. **`import_batches`:**
   - Audit ledger recording `filename`, `imported_at`, `total_rows`, `successful_rows`, `rejected_rows`, `duplicate_rows`.
   - Enforced by database triggers: `total_rows == successful_rows + rejected_rows + duplicate_rows`.
3. **`transactions`:**
   - Central ledger storing `date` (`YYYY-MM-DD`), `category_id` (FK), `amount` (`CHECK (amount > 0)`), `payment_method`, `description`, `type`, `import_batch_id` (FK `ON DELETE SET NULL`), `created_at`.
4. **`budgets`:**
   - Stores category spending targets per month.
   - Enforces `UNIQUE(category_id, month)` to guarantee single-record upsert semantics per category per month.

---

## 7. Data Cleaning & Duplicate Detection

The ingestion pipeline in `src/data_cleaner.py` and `src/import_service.py` executes a multi-stage validation:

1. **Encoding Auto-Detection:** Automatically attempts `UTF-8`, `UTF-8-SIG` (BOM), and `Latin-1`.
2. **Schema Normalization:** Maps column names case-insensitively and strips outer whitespace (e.g. `" Date "` → `"date"`).
3. **Type Coercion & Date Validation:** Validates ISO calendar validity. Dates like `"2026-02-31"` or `"2026-11-31"` are rejected with descriptive error strings.
4. **Two-Tier Duplicate Detection:**
   - **Intra-CSV:** Generates a hash signature `(date, category_lower, amount, type, payment_method, description)` and flags identical occurrences within the uploaded file.
   - **Database Check:** Cross-references signatures against all existing transactions in SQLite. Detected duplicates are isolated into an exportable candidates DataFrame without breaking the batch.
5. **Atomic Commit:** Valid rows are inserted in a single SQLite transaction. If any write fails, SQLite issues an automatic `ROLLBACK`.

---

## 8. Financial Calculations & Edge Cases

All metrics in `src/analytics.py` are strictly deterministic:
- **Net Savings:** $\text{Net Savings} = \text{Total Income} - \text{Total Expenses}$
- **Savings Rate:** $\text{Savings Rate} = \frac{\text{Net Savings}}{\text{Total Income}} \times 100\%$
  - *Zero-Income Edge Case:* If Total Income is ₹0.00, savings rate strictly returns `0.0%` rather than raising a `ZeroDivisionError`.
- **Month-Over-Month Comparison:**
  - When comparing Month A to Month B:
    $$\Delta\% = \frac{\text{Month B} - \text{Month A}}{\text{Month A}} \times 100\%$$
  - *Zero-Baseline Policy:* If Month A value is ₹0.00 and Month B is positive, returning $\infty\%$ or $100\%$ is mathematically misleading. The engine strictly returns `None`, allowing the UI to display `"New Activity"` or a dash (`—`).

---

## 9. Budget Utilization & Alert Logic

In `src/budget_manager.py`:
- **Upsert Semantics:** If a budget exists for `(category_id, month)`, it updates the amount in-place and preserves its original primary key `id`.
- **Utilization Formula:**
  $$\text{Utilization} = \frac{\text{Actual Spending in Month}}{\text{Allocated Budget}} \times 100\%$$
- **Alert Status Thresholds:**
  - 🟢 **Normal (`utilization < 80%`):** Spending is well within limits.
  - 🟡 **Warning (`80% <= utilization <= 100%`):** Approaching budget limit; yellow warning indicator displayed.
  - 🔴 **Exceeded (`utilization > 100%`):** Budget breached; red alert badge and overspend amount displayed.

---

## 10. CSV Import and Export Pipeline

- **Import:** Coordinated via `import_service.py`. Raw CSV files are never written directly to the database without validation. Rejected rows and duplicate rows can be exported as separate audit CSVs (`outputs/exports/`).
- **Export:** Implemented in `report_generator.py`:
  - Supports filtered exports (matching active UI filters) or full database backups.
  - Generates UTF-8 with BOM (`utf-8-sig`) for native compatibility with Microsoft Excel and LibreOffice Calc.
  - **Formula Injection Defense:** Any string field beginning with `=`, `+`, `-`, `@`, `\t`, or `\r` is escaped with a leading single quote (`'`). Database records are NEVER mutated; sanitization occurs strictly in the exported projection.

---

## 11. PDF Report Generation

`src/report_generator.py` produces publication-grade financial statements:
- **`NumberedCanvas` Pattern:** Standard ReportLab cannot calculate total page counts on a single pass. A custom two-pass canvas intercepts `showPage()` and `save()`, accumulating total page count and stamping `"Page X of Y"` and running footers on the second pass.
- **Dynamic End-of-Month Computation:** Uses `calendar.monthrange(year, month)[1]` to ensure leap years and 30-day months (e.g. November 30) compute exact valid calendar dates.
- **Three Report Types:**
  1. *Monthly Financial Statement*: KPI cards, category expense table, payment method shares, budget performance, and transaction log.
  2. *Custom Period Report*: Date-range statements with income/expense summaries.
  3. *Transaction Listing Report*: Paginated, filtered transaction audit logs.

---

## 12. Security Measures Matrix

| Threat Vector | Mitigation Strategy | Verification / Implementation |
|---------------|---------------------|-------------------------------|
| **SQL Injection** | Strict parameterisation | All queries use `?` placeholders. Parameter concatenation is strictly prohibited. Verified in `test_security.py`. |
| **CSV Formula Injection** | Character neutralization | User text fields starting with `=`, `+`, `-`, `@`, `\t` are prefixed with `'` during export. |
| **Cross-Site Scripting (XSS)** | HTML entity escaping | `render_dataframe()` in `src/ui/common.py` sets `escape=True` on all `to_html()` calls. `<script>` tags render as literal text. |
| **Referential Integrity Loss** | Foreign Key Pragma | `PRAGMA foreign_keys = ON;` executed on every SQLite connection. Category deletions blocked when transactions exist. |
| **Batch Accounting Fraud** | SQLite Schema Triggers | Triggers verify `total_rows == successful_rows + rejected_rows + duplicate_rows` on insert and update. |
| **Production Data Leakage** | Complete Test Isolation | Pytest fixtures exclusively create temporary SQLite databases in `tmp_path`. Production database `data/expense_tracker.db` is never modified during tests. |

---

## 13. Testing Strategy

The test suite consists of **337 tests across 12 modules**, running in under 20 seconds:

| Test Module | Test Count | Scope |
|-------------|------------|-------|
| `test_database.py` | 34 | Schema creation, triggers, foreign keys, migrations |
| `test_data_loader.py` | 20 | Multi-encoding CSV reading, missing files, empty files |
| `test_data_cleaner.py` | 24 | Type conversion, whitespace trimming, intra-CSV duplicates |
| `test_expense_manager.py` | 40 | CRUD, calendar validation, multi-filter queries |
| `test_import_service.py` | 32 | Two-phase import, duplicate isolation, batch accounting |
| `test_analytics.py` | 26 | Totals, savings rate, zero-income handling, MoM comparisons |
| `test_budget_manager.py` | 32 | Upsert logic, threshold status, deletion safety |
| `test_visualizations.py` | 19 | Figure generation, empty database boundaries, data ordering |
| `test_report_generator.py` | 10 | PDF generation, NumberedCanvas pagination, custom ranges |
| `test_csv_export.py` | 10 | Formula injection defense, BOM encoding, filtered export |
| `test_streamlit_app.py` | 22 | Navigation routing, UI state, XSS escaping, page loaders |
| `test_end_to_end.py` | 20 | Complete workflows, CRUD metrics sync, demo CSV import |
| **Total** | **337** | **100% Passed, 0 Failed, 0 Errors** |

---

## 14. Technical Limitations & Non-Goals

To maintain high architectural quality and deliver a finished system, explicit non-goals were established:
1. **Single-User Scope:** The application is architected for single-user local deployment; multi-tenant user authentication (OAuth/JWT) is omitted.
2. **Local SQLite Storage:** Uses a local SQLite file instead of cloud databases (PostgreSQL/MySQL).
3. **No Machine Learning:** Predictive forecasting (ARIMA) and anomaly detection (Isolation Forest) were excluded in favor of deterministic, verifiable financial math.
4. **No Direct Bank APIs:** Open Banking / Plaid integrations were omitted to avoid handling sensitive live banking credentials.

---

## 15. Future Roadmap

- [ ] **Multi-Tenant Authentication:** Integrate Auth0 or Supabase for secure user authentication and per-user database schemas.
- [ ] **Cloud Database Migration:** Add PostgreSQL connection backend for multi-device synchronization.
- [ ] **Bank Statement Parsers:** Add support for OFX, QIF, and CAMT.053 bank statement standards.
- [ ] **Deterministic Recurring Transactions:** Automated scheduling engine for monthly subscriptions and recurring salary credits.
- [ ] **Multi-Currency Support:** Historical FX rate conversions via local caching.

---

## 16. 20 Technical Interview Questions & Answers

### Q1: Why did you choose SQLite instead of an ORM like SQLAlchemy?
**Answer:** While SQLAlchemy is excellent for multi-database enterprise applications, SQLite with Python’s built-in `sqlite3` driver was chosen intentionally. It gives complete transparency over query execution, allows custom SQLite triggers and constraints (such as `CHECK (amount > 0)` and batch row accounting triggers), guarantees zero external driver dependencies, and enforces explicit SQL parameterisation (`?` placeholders).

### Q2: How does your application prevent SQL Injection?
**Answer:** Every database operation in `database.py`, `expense_manager.py`, and `budget_manager.py` uses parameterised SQL queries where user inputs are passed as separate tuples to `cursor.execute(sql, params)`. String concatenation and f-strings are strictly forbidden in SQL construction.

### Q3: What is CSV Formula Injection, and how did you resolve it?
**Answer:** CSV Formula Injection (DDE injection) occurs when untrusted spreadsheet cells starting with characters like `=`, `+`, `-`, or `@` are opened in Excel, causing Excel to execute external system commands or exfiltrate data. I implemented `sanitize_csv_value()` in `report_generator.py`, which inspects string fields and prefixes any trigger character (including raw `\t` and `\r`) with a single quote (`'`). Crucially, this sanitization is applied only to the exported DataFrame projection, leaving the underlying SQLite database records completely uncorrupted.

### Q4: How do you handle Cross-Site Scripting (XSS) in Streamlit?
**Answer:** On platforms where `pyarrow` is unavailable (such as Windows ARM64), Streamlit falls back to HTML table rendering. In `src/ui/common.py`, the `render_dataframe()` function forces `escape=True` on `df.to_html()`. This ensures that malicious payloads such as `<script>alert('XSS')</script>` are rendered as literal text entities (`&lt;script&gt;...`) rather than being executed by the browser DOM.

### Q5: How does your two-pass PDF page numbering (`NumberedCanvas`) work?
**Answer:** In ReportLab, the total number of pages is unknown until document compilation completes. Standard flowables cannot look into the future. I created a custom `NumberedCanvas` class inheriting from `canvas.Canvas` that overrides `showPage()` to stash page objects in memory. When `save()` is invoked at the end of compilation, the canvas computes the total page count $N$, iterates back through each saved page, draws the `"Page X of Y"` footer in the margin, and finally writes the PDF stream.

### Q6: Why did you choose `Rs.` instead of `₹` in PDF generation?
**Answer:** Standard ReportLab core fonts (Helvetica, Times) use `WinAnsiEncoding`, which does not include the Indian Rupee glyph (`₹`, Unicode U+20B9). Attempting to render `₹` without embedding an external TTF font triggers an unhandled `UnicodeEncodeError`. To ensure 100% reliable, zero-dependency cross-platform execution on any machine, all PDF currency formatting uses `Rs. {:,.2f}`, while the web UI displays `₹`.

### Q7: How does your duplicate transaction detection work during CSV import?
**Answer:** Duplicate detection operates on two levels:
1. **Intra-file:** As the CSV is read, each row generates a composite signature tuple: `(date, category_name_lower, round(amount, 2), type_lower, payment_method_lower, description_lower)`. Any duplicate within the file is flagged.
2. **Database check:** The candidate signatures are cross-referenced against all existing transactions in SQLite. If a match is found, the row is partitioned into an exportable duplicates table rather than inserted.

### Q8: What happens if a CSV import contains invalid rows? Does the whole import fail?
**Answer:** The system uses a two-phase workflow. In Phase 1 (Preview), rows are validated and partitioned into `valid_df`, `rejected_df`, and `duplicate_candidates_df`. The user is shown an exact summary of rejected reasons. In Phase 2 (Confirmation), valid rows are inserted inside a single atomic SQLite transaction (`conn.commit()`), while rejected and duplicate rows can be exported as separate audit CSVs. If an unexpected database exception occurs during insertion, SQLite rolls back the entire batch.

### Q9: How do you enforce referential integrity when deleting import batches?
**Answer:** In the `transactions` table, the foreign key referencing `import_batches(id)` is configured with `ON DELETE SET NULL`. If an import batch audit log is cleared, the historical transactions are preserved in the ledger with `import_batch_id = NULL` rather than being accidentally destroyed.

### Q10: How does the month-over-month calculation handle a baseline of zero?
**Answer:** If Month A has ₹0.00 expenses and Month B has ₹5,000.00 expenses, traditional percentage formulas divide by zero ($\frac{5000 - 0}{0}$). Returning `100%` or $\infty$ is mathematically misleading. My `compare_months()` function in `analytics.py` explicitly returns `None` for percentage change when the baseline is zero, enabling the UI to display `"New Activity"` or a dash (`—`).

### Q11: How do you prevent division-by-zero when calculating the savings rate?
**Answer:** In `get_financial_overview()`, the savings rate is calculated as $(\text{Net Savings} / \text{Total Income}) \times 100$. If `Total Income == 0`, the function immediately short-circuits to return `0.0%`, completely avoiding runtime mathematical exceptions.

### Q12: How does the budget manager handle duplicate budget entries for the same category and month?
**Answer:** The `budgets` table has a composite unique constraint `UNIQUE(category_id, month)`. The `set_budget()` function implements an idempotent UPSERT: it attempts an `INSERT ... ON CONFLICT(category_id, month) DO UPDATE SET amount = excluded.amount` (or an explicit query-then-update pattern). Furthermore, it returns the stable existing budget primary key `id` rather than a stale `lastrowid`.

### Q13: What are the three budget utilization thresholds, and how are they visualized?
**Answer:** Budget utilization is categorized into:
- `Normal` (< 80%): Green indicator.
- `Warning` (80% to 100%): Yellow indicator (Approaching Limit).
- `Exceeded` (> 100%): Red badge (Overspent).
In Plotly (`create_budget_utilization_chart`), it is rendered as horizontal bar charts with explicit dashed threshold lines at 80% and 100% for immediate visual recognition.

### Q14: How do your tests guarantee that the production database is never corrupted?
**Answer:** All 337 tests use Pytest fixtures with temporary directory isolation (`tmp_path`). Test databases are created dynamically in temporary paths and destroyed after test completion. A dedicated regression test in `test_end_to_end.py` explicitly verifies that `data/expense_tracker.db` remains isolated with 0 user transactions.

### Q15: How does `app.py` handle navigation and deep linking?
**Answer:** `app.py` maintains an active sidebar radio widget. In addition, it inspects `st.query_params.get("page")`. If a valid page name (e.g., `?page=Budgets`) is passed in the URL, `app.py` automatically initializes session state to that page, enabling automated headless browser testing, deep-linking, and reproducible screenshot generation.

### Q16: Why did you implement database triggers for batch accounting?
**Answer:** In financial software, batch audit logs must never desynchronize from transaction records. I added a SQLite trigger `trg_validate_batch_counts` that executes before insert or update on `import_batches`. It enforces that `total_rows == successful_rows + rejected_rows + duplicate_rows`. Any violation raises a SQLite `ABORT`, preventing inconsistent ledger states.

### Q17: How did you handle date parsing across varying user CSV formats?
**Answer:** In `data_cleaner.py`, the date parsing routine tests multiple candidate date formats sequentially (`%Y-%m-%d`, `%d-%m-%Y`, `%d/%m/%Y`, `%m/%d/%Y`). Furthermore, it validates calendar reality: leap-year awareness is enforced, and non-existent dates like February 30th or November 31st are cleanly caught and rejected.

### Q18: What is your strategy for handling empty states in the dashboard?
**Answer:** A common flaw in data dashboards is crashing or rendering broken charts when the database is empty. Every visualization function in `visualizations.py` includes an empty-state guard: if the incoming DataFrame has zero rows, it returns a clean Plotly figure annotated with a centered message (e.g., *"No expense data available for this period"*), preventing blank screens or unhandled exceptions.

### Q19: What is the computational complexity of your financial overview analytics?
**Answer:** Because transaction filtering and aggregation are delegated directly to SQLite’s indexed B-Tree engine (`INDEX` on date and category), total calculations run in $O(\log N + K)$ time, where $N$ is total transactions and $K$ is the matching slice size. Grouped aggregations (monthly trends, category totals) execute in a single SQL pass using `GROUP BY` and `SUM()`.

### Q20: If you had another sprint, what single architectural improvement would you implement?
**Answer:** I would migrate the single-user SQLite backend to a client-server relational architecture using PostgreSQL with connection pooling (e.g., SQLAlchemy 2.0 with asyncpg) and implement row-level security (RLS) coupled with JWT/OAuth2 authentication. This would allow secure multi-user deployment and mobile companion apps while preserving our existing analytics and reporting engines.
