"""
src/ui/common.py — Shared UI Utilities and Helpers
===================================================
Provides shared formatting, category lookups, and session management.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import streamlit as st

from src.database import DEFAULT_DB_PATH, get_connection

PAYMENT_METHODS = ["UPI", "Card", "Cash", "Bank Transfer", "Net Banking", "Other"]


def get_active_db_path() -> Optional[Union[Path, str]]:
    """Retrieve the database path configured in session state, defaulting to DEFAULT_DB_PATH."""
    return st.session_state.get("db_path", DEFAULT_DB_PATH)


def get_categories(
    trans_type: Optional[str] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> list[str]:
    """
    Fetch category names from SQLite, optionally filtered by type (Expense/Income).

    Returns sorted list of category names.
    """
    active_path = db_path or get_active_db_path()
    with get_connection(active_path) as conn:
        if trans_type:
            rows = conn.execute(
                "SELECT name FROM categories WHERE type = ? ORDER BY name ASC;",
                (trans_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name FROM categories ORDER BY name ASC;"
            ).fetchall()
    return [r["name"] for r in rows]


def format_inr(amount: Union[float, int]) -> str:
    """Format numeric currency values in Indian Rupees (₹)."""
    try:
        val = float(amount)
        return f"₹{val:,.2f}"
    except (ValueError, TypeError):
        return "₹0.00"


def format_pct(percentage: Optional[Union[float, int]]) -> str:
    """Format percentage values cleanly or return 'N/A' if None."""
    if percentage is None:
        return "N/A"
    return f"{float(percentage):.1f}%"


def render_dataframe(df, hide_index: bool = True) -> None:
    """
    Render a pandas DataFrame in Streamlit with graceful pyarrow fallback and strict HTML escaping.

    Attempts native st.dataframe(); on platforms lacking binary pyarrow wheels
    (such as Windows ARM64), seamlessly falls back to styled HTML table rendering.
    Enforces escape=True to protect against XSS and HTML/JS injection from user descriptions.
    """
    try:
        st.dataframe(df, use_container_width=True, hide_index=hide_index)
    except ModuleNotFoundError as err:
        if "pyarrow" in str(err):
            st.markdown(
                df.to_html(escape=True, index=not hide_index, classes="dataframe", border=0),
                unsafe_allow_html=True,
            )
        else:
            raise
