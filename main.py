"""
main.py — Legacy Entry Point (redirects to app.py)
====================================================
The primary Streamlit entry point is app.py.

Usage:
    streamlit run app.py
"""

import subprocess
import sys


def main() -> None:
    """Launch the Streamlit application via app.py."""
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "app.py"],
        check=True,
    )


if __name__ == "__main__":
    main()
