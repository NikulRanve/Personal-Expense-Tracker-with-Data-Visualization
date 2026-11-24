# Demonstration & Walkthrough Guide

This guide provides a step-by-step walkthrough for demonstrating the **Personal Expense Tracker with Data Visualization** using the included synthetic dataset.

---

## 1. Quick Demonstration Setup

1. **Launch the Application:**
   ```bash
   streamlit run app.py
   ```
2. The application opens automatically in your default browser at `http://localhost:8501`.
3. The production database initializes automatically at `data/expense_tracker.db` with 8 seeded financial categories (Food, Transportation, Shopping, Utilities, Healthcare, Housing, Salary, Other Income) and 0 transactions.

---

## 2. Step-by-Step Demo Flow

### Step 1: Importing the Sample CSV Dataset
- Navigate to **"Import CSV"** in the sidebar.
- Click **"Browse files"** and select `data/sample/demo_transactions.csv`.
- Observe the **Validation Summary & Preview**:
  - Total Rows: `38`
  - Valid Rows: `38`
  - Rejected Rows: `0`
  - Duplicate Candidates: `0`
- Inspect the data preview table showing sanitized transaction dates, categories, types, amounts, and payment methods.
- Click **"Confirm & Import 38 Transactions"**.
- A success toast confirms batch insertion with a generated Batch ID (e.g., `#1`).

### Step 2: Exploring Analytics on the Dashboard
- Navigate to **"Dashboard"** in the sidebar.
- View the updated **Key Performance Indicators (KPIs)**:
  - **Total Income:** ₹1,55,000.00
  - **Total Expenses:** ₹80,180.00
  - **Net Savings:** ₹74,820.00
  - **Savings Rate:** ~48.27%
- Scroll through the 6 interactive Plotly charts:
  1. *Category-wise Expense Breakdown* (Donut chart)
  2. *Monthly Income vs Expenses* (Grouped bar chart)
  3. *Daily/Monthly Expense Trend* (Line chart with markers)
  4. *Payment Method Distribution* (Horizontal bar chart)
  5. *Budget Utilization & Thresholds* (Progress bars with 80% & 100% alert lines)
  6. *Monthly Savings Variance* (Green/red delta bars)
- Toggle the **"Filter by Date Range"** checkbox in the top filter expander to inspect specific months (e.g., September 2026 vs November 2026).

### Step 3: Manual Transaction Management (Add, Edit, Delete)
- **Add a Transaction:**
  - Navigate to **"Add Transaction"**.
  - Choose **Expense** or **Income**.
  - Select category (e.g., `Food`), enter amount (e.g., `450.00`), select date, payment method (`UPI`), and description (`"Team lunch"`).
  - Click **"Save Transaction"**. Notice immediate database insertion.
- **Edit & Filter Transactions:**
  - Navigate to **"Transactions"**.
  - Use the top search bar to find `"Team lunch"` or filter by Category `Food`.
  - Expand the transaction editor expander, adjust the amount or description, and click **"Update"**.
  - Use the **"Delete"** button with confirmation to remove a transaction and verify the table updates immediately.

### Step 4: Configuring Monthly Budgets & Breach Alerts
- Navigate to **"Budgets"**.
- Select target month: `2026-11`.
- Set budget for `Food`: Enter `₹12,000.00` and click **"Set Budget"**.
- Set budget for `Shopping`: Enter `₹8,000.00` and click **"Set Budget"**.
- Set budget for `Transportation`: Enter `₹5,000.00` and click **"Set Budget"**.
- Observe the **Budget Utilization Table & Visual Gauges**:
  - Green indicator for spending `< 80%`.
  - Yellow warning for spending `80% – 100%` (Approaching Limit).
  - Red alert badge for spending `> 100%` (Exceeded Target).

### Step 5: Generating Financial PDF Reports
- Navigate to **"Reports"**.
- **Tab 1 — Monthly PDF Report:**
  - Select month `2026-11`.
  - Click **"Generate Monthly Statement (PDF)"**.
  - Inspect the download button and download the publication-ready A4 PDF report with custom tables, font-safe currency (`Rs. {:,.2f}`), and "Page X of Y" pagination.
- **Tab 2 — Custom Period PDF:**
  - Select a date range spanning `2026-09-01` to `2026-11-20`.
  - Click **"Generate Date-Range Report (PDF)"**.
- **Tab 3 — Transaction Listing PDF:**
  - Apply filters (e.g. Category = `Shopping`), generate a paginated audit listing PDF.

### Step 6: Exporting Transactions to CSV
- Navigate to **"Reports"** → **Tab 4 — CSV Data Export**.
- **Filtered Export:** Download CSV matching active filters.
- **Full Database Export:** Click **"Export Full Database (CSV)"** to obtain complete transaction records.
- Note security property: All text fields starting with `=`, `+`, `-`, `@`, or tab characters are prefixed with single quotes (`'`) to neutralize CSV formula injection in spreadsheet applications (Excel / Calc).

---

## 3. Data Safety & Privacy Guarantee

- The sample dataset `data/sample/demo_transactions.csv` is **100% synthetic**.
- No personal bank statements, account numbers, or real identities are included or stored.
- Testing and demo routines run on isolated temporary databases, leaving the primary application database pristine.
