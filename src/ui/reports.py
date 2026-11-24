"""
src/ui/reports.py — Financial Reporting and Export Interface
============================================================
Streamlit page for generating and downloading professional PDF reports
and sanitized CSV transaction exports.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional, Union

import streamlit as st

from src.analytics import get_financial_overview
from src.report_generator import (
    export_all_transactions_csv,
    export_transactions_csv,
    generate_custom_period_report,
    generate_monthly_report,
    generate_transaction_report,
)
from src.ui.common import (
    PAYMENT_METHODS,
    format_inr,
    get_active_db_path,
    get_categories,
    render_dataframe,
)


def render_reports(db_path: Optional[Union[Path, str]] = None) -> None:
    """Render the Financial Reports & Data Export dashboard."""
    active_path = db_path or get_active_db_path()

    st.title("📑 Reports & Data Export")
    st.markdown(
        "Generate publication-quality PDF financial statements and export CSV transaction data "
        "with built-in spreadsheet injection security."
    )

    tab_monthly, tab_custom, tab_trans_pdf, tab_csv = st.tabs([
        "📅 Monthly PDF Report",
        "📆 Custom Period PDF",
        "📋 Transaction Listing PDF",
        "💾 CSV Data Export",
    ])

    # -------------------------------------------------------------------------
    # 1. Monthly PDF Report
    # -------------------------------------------------------------------------
    with tab_monthly:
        st.subheader("Generate Monthly Financial Statement")
        st.markdown(
            "Includes executive financial summary KPIs, category spending breakdowns, "
            "payment channel distribution, budget variance analysis, and itemized transaction log."
        )

        col_m1, col_m2 = st.columns([2, 1])
        with col_m1:
            default_month = datetime.date.today().strftime("%Y-%m")
            selected_month = st.text_input(
                "Month (YYYY-MM)",
                value=default_month,
                help="Format: YYYY-MM (e.g., 2026-11)",
                key="report_monthly_input",
            ).strip()

        with col_m2:
            st.write("")
            st.write("")
            btn_gen_monthly = st.button("Generate Monthly PDF", key="btn_gen_monthly", type="primary")

        if btn_gen_monthly:
            if not selected_month:
                st.error("Please enter a valid month in YYYY-MM format.")
            else:
                try:
                    with st.spinner("Generating PDF report..."):
                        pdf_path = generate_monthly_report(
                            month=selected_month,
                            db_path=active_path,
                        )
                        pdf_bytes = pdf_path.read_bytes()
                        st.session_state["monthly_pdf_data"] = pdf_bytes
                        st.session_state["monthly_pdf_filename"] = f"monthly_financial_report_{selected_month}.pdf"
                    st.success(f"Report for {selected_month} successfully generated!")
                except ValueError as exc:
                    st.error(f"Invalid input: {exc}")
                except Exception as exc:
                    st.error(f"Failed to generate report: {exc}")

        if "monthly_pdf_data" in st.session_state and st.session_state.get("monthly_pdf_data"):
            st.download_button(
                label=f"⬇️ Download {st.session_state.get('monthly_pdf_filename', 'monthly_report.pdf')}",
                data=st.session_state["monthly_pdf_data"],
                file_name=st.session_state.get("monthly_pdf_filename", "monthly_report.pdf"),
                mime="application/pdf",
                key="download_monthly_pdf",
            )

    # -------------------------------------------------------------------------
    # 2. Custom Period PDF Report
    # -------------------------------------------------------------------------
    with tab_custom:
        st.subheader("Generate Custom Date Range Report")
        st.markdown("Consolidates financial metrics and activity across an arbitrary date span.")

        col_c1, col_c2, col_c3 = st.columns([2, 2, 1])
        with col_c1:
            c_start = st.date_input(
                "Start Date",
                value=datetime.date.today().replace(day=1),
                key="custom_start_date",
            )
        with col_c2:
            c_end = st.date_input(
                "End Date",
                value=datetime.date.today(),
                key="custom_end_date",
            )
        with col_c3:
            st.write("")
            st.write("")
            btn_gen_custom = st.button("Generate Range PDF", key="btn_gen_custom", type="primary")

        if btn_gen_custom:
            start_str = c_start.strftime("%Y-%m-%d")
            end_str = c_end.strftime("%Y-%m-%d")

            if c_start > c_end:
                st.error("Start date must be earlier than or equal to End date.")
            else:
                try:
                    with st.spinner("Generating custom period PDF..."):
                        pdf_path = generate_custom_period_report(
                            start_date=start_str,
                            end_date=end_str,
                            db_path=active_path,
                        )
                        pdf_bytes = pdf_path.read_bytes()
                        st.session_state["custom_pdf_data"] = pdf_bytes
                        st.session_state["custom_pdf_filename"] = f"financial_report_{start_str}_to_{end_str}.pdf"
                    st.success(f"Report for {start_str} to {end_str} generated successfully!")
                except ValueError as exc:
                    st.error(f"Invalid input: {exc}")
                except Exception as exc:
                    st.error(f"Failed to generate report: {exc}")

        if "custom_pdf_data" in st.session_state and st.session_state.get("custom_pdf_data"):
            st.download_button(
                label=f"⬇️ Download {st.session_state.get('custom_pdf_filename', 'custom_period_report.pdf')}",
                data=st.session_state["custom_pdf_data"],
                file_name=st.session_state.get("custom_pdf_filename", "custom_period_report.pdf"),
                mime="application/pdf",
                key="download_custom_pdf",
            )

    # -------------------------------------------------------------------------
    # 3. Transaction Listing PDF
    # -------------------------------------------------------------------------
    with tab_trans_pdf:
        st.subheader("Filtered Transaction Listing (PDF)")
        st.markdown("Export a clean, paginated PDF report of transactions matching specific criteria.")

        all_cats = ["All"] + get_categories(db_path=active_path)
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            t_type = st.selectbox("Type", options=["All", "Expense", "Income"], key="pdf_t_type")
            t_cat = st.selectbox("Category", options=all_cats, key="pdf_t_cat")
        with col_t2:
            t_pm = st.selectbox("Payment Method", options=["All"] + PAYMENT_METHODS, key="pdf_t_pm")
            t_use_dates = st.checkbox("Filter by Date Range", value=False, key="pdf_t_use_dates")
        with col_t3:
            t_start = st.date_input("From", value=datetime.date.today().replace(day=1), disabled=not t_use_dates, key="pdf_t_start")
            t_end = st.date_input("To", value=datetime.date.today(), disabled=not t_use_dates, key="pdf_t_end")

        btn_gen_trans_pdf = st.button("Generate Transaction PDF", key="btn_gen_trans_pdf", type="primary")

        if btn_gen_trans_pdf:
            try:
                s_date = t_start.strftime("%Y-%m-%d") if t_use_dates else None
                e_date = t_end.strftime("%Y-%m-%d") if t_use_dates else None
                cat_val = None if t_cat == "All" else t_cat
                type_val = None if t_type == "All" else t_type
                pm_val = None if t_pm == "All" else t_pm

                with st.spinner("Generating transaction listing PDF..."):
                    pdf_path = generate_transaction_report(
                        start_date=s_date,
                        end_date=e_date,
                        category=cat_val,
                        transaction_type=type_val,
                        payment_method=pm_val,
                        db_path=active_path,
                    )
                    pdf_bytes = pdf_path.read_bytes()
                    st.session_state["trans_pdf_data"] = pdf_bytes
                    st.session_state["trans_pdf_filename"] = "transactions_report.pdf"
                st.success("Transaction PDF report generated successfully!")
            except Exception as exc:
                st.error(f"Failed to generate transaction report: {exc}")

        if "trans_pdf_data" in st.session_state and st.session_state.get("trans_pdf_data"):
            st.download_button(
                label="⬇️ Download Transaction Listing (PDF)",
                data=st.session_state["trans_pdf_data"],
                file_name=st.session_state.get("trans_pdf_filename", "transactions_report.pdf"),
                mime="application/pdf",
                key="download_trans_pdf",
            )

    # -------------------------------------------------------------------------
    # 4. CSV Data Export
    # -------------------------------------------------------------------------
    with tab_csv:
        st.subheader("CSV Spreadsheet Export")
        st.markdown(
            "Export raw data for Excel / Google Sheets analysis. "
            "Encoded in **UTF-8 with BOM** and pre-sanitized against spreadsheet formula injection."
        )

        col_csv1, col_csv2 = st.columns(2)

        with col_csv1:
            st.markdown("#### 📁 Filtered CSV Export")
            st.caption("Apply filters before exporting.")
            csv_type = st.selectbox("Type Filter", options=["All", "Expense", "Income"], key="csv_type")
            csv_cat = st.selectbox("Category Filter", options=all_cats, key="csv_cat")
            csv_pm = st.selectbox("Payment Method Filter", options=["All"] + PAYMENT_METHODS, key="csv_pm")
            csv_use_date = st.checkbox("Date Range Filter", value=False, key="csv_use_date")
            csv_s = st.date_input("Start", value=datetime.date.today().replace(day=1), disabled=not csv_use_date, key="csv_s")
            csv_e = st.date_input("End", value=datetime.date.today(), disabled=not csv_use_date, key="csv_e")

            if st.button("Prepare Filtered CSV", key="btn_prep_filtered_csv"):
                try:
                    s_str = csv_s.strftime("%Y-%m-%d") if csv_use_date else None
                    e_str = csv_e.strftime("%Y-%m-%d") if csv_use_date else None
                    c_val = None if csv_cat == "All" else csv_cat
                    t_val = None if csv_type == "All" else csv_type
                    p_val = None if csv_pm == "All" else csv_pm

                    csv_content = export_transactions_csv(
                        output_path=None,
                        db_path=active_path,
                        start_date=s_str,
                        end_date=e_str,
                        category=c_val,
                        transaction_type=t_val,
                        payment_method=p_val,
                    )
                    st.session_state["filtered_csv_data"] = csv_content.encode("utf-8-sig") if isinstance(csv_content, str) else csv_content
                    st.success("Filtered CSV is ready for download.")
                except Exception as exc:
                    st.error(f"Failed to prepare filtered CSV: {exc}")

            if "filtered_csv_data" in st.session_state and st.session_state.get("filtered_csv_data"):
                st.download_button(
                    label="⬇️ Download Filtered CSV",
                    data=st.session_state["filtered_csv_data"],
                    file_name="transactions_filtered.csv",
                    mime="text/csv",
                    key="download_filtered_csv",
                )

        with col_csv2:
            st.markdown("#### 📦 Full Database Export")
            st.caption("Export all transactions currently stored in the database.")

            try:
                all_csv_str = export_all_transactions_csv(output_path=None, db_path=active_path)
                all_csv_bytes = all_csv_str.encode("utf-8-sig") if isinstance(all_csv_str, str) else all_csv_str

                st.download_button(
                    label="⬇️ Download All Transactions (CSV)",
                    data=all_csv_bytes,
                    file_name="all_transactions.csv",
                    mime="text/csv",
                    key="download_all_csv",
                    type="primary",
                )
            except Exception as exc:
                st.error(f"Failed to prepare complete CSV export: {exc}")
