"""
src/ui/import_csv.py — CSV Transaction Import Workflow Page
============================================================
Handles CSV upload, validation preview, inspection of valid, rejected,
and duplicate rows, downloading rejected/duplicate records, and persistent import.
Consumes src.import_service functions exclusively.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Union

import streamlit as st

from src.import_service import (
    export_duplicate_candidates,
    export_rejected_transactions,
    import_transactions,
    preview_import,
)
from src.ui.common import get_active_db_path, render_dataframe


def render_import_csv(db_path: Optional[Union[Path, str]] = None) -> None:
    """Render the CSV Import and Preview workflow."""
    active_path = db_path or get_active_db_path()

    st.title("📥 Import CSV Transactions")
    st.markdown(
        "Upload a CSV file containing transactions (`date`, `category`, `amount`, "
        "`payment_method`, `description`, `type`). Data is validated and previewed "
        "before anything is saved to the database."
    )

    uploaded_file = st.file_uploader("Select CSV File", type=["csv"], key="csv_uploader")

    if uploaded_file is None:
        st.info("Please upload a CSV file to begin the import workflow.")
        # Clear preview state when file is removed
        st.session_state.pop("current_preview", None)
        st.session_state.pop("last_imported_filename", None)
        return

    # Read uploaded file content into memory buffer
    file_bytes = uploaded_file.getvalue()
    file_buffer = io.BytesIO(file_bytes)

    # Generate preview without mutating the database
    with st.spinner("Analyzing and validating CSV transactions..."):
        try:
            preview = preview_import(file_buffer, db_path=active_path)
            st.session_state["current_preview"] = preview
        except Exception as exc:
            st.error(f"❌ Failed to parse CSV: {exc}")
            return

    if preview.total_rows == 0:
        st.warning("⚠️ The uploaded CSV file has no records. Please upload a file with data.")
        return

    # -----------------------------------------------------------------------
    # Summary KPI Cards
    # -----------------------------------------------------------------------
    st.subheader("📊 Import Validation Summary")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Rows", preview.total_rows)
    with col2:
        st.metric("Valid Rows", preview.valid_count)
    with col3:
        st.metric("Rejected Rows", preview.rejected_count)
    with col4:
        st.metric("Duplicate Rows", preview.duplicate_count)

    # -----------------------------------------------------------------------
    # Data Inspection Tabs
    # -----------------------------------------------------------------------
    tab_valid, tab_rejected, tab_dupes = st.tabs([
        f"✅ Valid ({preview.valid_count})",
        f"❌ Rejected ({preview.rejected_count})",
        f"⚠️ Duplicates ({preview.duplicate_count})",
    ])

    with tab_valid:
        if not preview.valid_transactions.empty:
            render_dataframe(preview.valid_transactions, hide_index=True)
        else:
            st.info("No valid transactions found in this CSV.")

    with tab_rejected:
        if not preview.rejected_transactions.empty:
            render_dataframe(preview.rejected_transactions, hide_index=True)
            rejected_csv = export_rejected_transactions(preview)
            st.download_button(
                label="📥 Download Rejected Rows (CSV)",
                data=rejected_csv,
                file_name=f"rejected_{uploaded_file.name}",
                mime="text/csv",
            )
        else:
            st.success("No rejected rows in this file.")

    with tab_dupes:
        if not preview.duplicate_candidates.empty:
            render_dataframe(preview.duplicate_candidates, hide_index=True)
            dupe_csv = export_duplicate_candidates(preview)
            st.download_button(
                label="📥 Download Duplicate Rows (CSV)",
                data=dupe_csv,
                file_name=f"duplicates_{uploaded_file.name}",
                mime="text/csv",
            )
        else:
            st.success("No duplicate candidates detected.")

    st.divider()

    # -----------------------------------------------------------------------
    # Confirmation & Persistence Section
    # -----------------------------------------------------------------------
    st.subheader("🚀 Confirm Import")

    # Guard against repeat import on rerun
    already_imported = (st.session_state.get("last_imported_filename") == uploaded_file.name)
    if already_imported:
        st.success(
            f"✅ Batch from '{uploaded_file.name}' was already imported. "
            "To import another file or re-import, upload a different file or reset."
        )
        return

    if preview.valid_count == 0:
        st.warning("Cannot import: there are 0 valid rows in this file.")
        return

    confirm_box = st.checkbox(
        f"I confirm that I want to import {preview.valid_count} valid transaction(s) from '{uploaded_file.name}'.",
        key=f"confirm_import_{uploaded_file.name}",
    )

    if st.button("💾 Confirm and Import Valid Transactions", disabled=not confirm_box, type="primary"):
        with st.spinner("Persisting transactions to database..."):
            try:
                result = import_transactions(
                    cleaning_result=preview,
                    filename=uploaded_file.name,
                    db_path=active_path,
                )
                st.session_state["last_imported_filename"] = uploaded_file.name
                st.success(
                    f"🎉 Import complete! Batch #{result.batch_id} saved: "
                    f"{result.successful_rows} transactions imported successfully, "
                    f"{result.rejected_rows} rejected, {result.duplicate_rows} duplicates skipped."
                )
            except Exception as exc:
                st.error(f"❌ Import failed during database persistence: {exc}")
