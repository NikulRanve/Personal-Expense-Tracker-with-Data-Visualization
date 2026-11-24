"""
src/ui/import_history.py — Import History and Batch Inspection Page
===================================================================
Displays historical CSV import batches and inspects individual batch transactions.
Consumes src.import_service history functions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd
import streamlit as st

from src.import_service import (
    get_batch_transactions,
    get_import_batch,
    get_import_history,
)
from src.ui.common import format_inr, get_active_db_path, render_dataframe


def render_import_history(db_path: Optional[Union[Path, str]] = None) -> None:
    """Render the Import History and Batch Inspector page."""
    active_path = db_path or get_active_db_path()

    st.title("📜 Import History")
    st.markdown("Review past CSV import batches and inspect transactions imported in each batch.")

    try:
        raw_history = get_import_history(db_path=active_path)
        history_df = pd.DataFrame(raw_history)
    except Exception as exc:
        st.error(f"❌ Failed to load import history: {exc}")
        return

    if history_df.empty:
        st.info("No CSV import batches recorded yet. Use the 'Import CSV' page to upload transactions.")
        return

    # Display History Table
    st.subheader("All Import Batches")
    render_dataframe(
        history_df,
        hide_index=True,
    )

    st.divider()

    # -----------------------------------------------------------------------
    # Batch Inspector Section
    # -----------------------------------------------------------------------
    st.subheader("🔎 Inspect Import Batch")
    batch_ids = list(history_df["id"])

    selected_batch_id = st.selectbox(
        "Select Batch to Inspect",
        options=batch_ids,
        format_func=lambda b_id: f"Batch #{b_id} — {history_df.loc[history_df['id'] == b_id, 'filename'].values[0]}",
        key="inspect_batch_id",
    )

    if selected_batch_id:
        batch_meta = get_import_batch(selected_batch_id, db_path=active_path)
        if not batch_meta:
            st.warning(f"Batch #{selected_batch_id} not found.")
            return

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Filename", batch_meta["filename"])
        with c2:
            st.metric("Import Date", batch_meta["imported_at"][:19])
        with c3:
            st.metric("Status", batch_meta["status"].capitalize())
        with c4:
            st.metric("Imported / Total", f"{batch_meta['successful_rows']} / {batch_meta['total_rows']}")

        st.markdown(f"**Transactions in Batch #{selected_batch_id}:**")
        batch_txns = get_batch_transactions(selected_batch_id, db_path=active_path)

        if not batch_txns.empty:
            display_txns = batch_txns.copy()
            display_txns["amount"] = display_txns["amount"].apply(format_inr)
            render_dataframe(
                display_txns[["id", "date", "category", "amount", "payment_method", "description", "type"]],
                hide_index=True,
            )
        else:
            st.info(f"No transactions associated with Batch #{selected_batch_id}.")
