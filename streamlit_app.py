"""Entry point for `streamlit run streamlit_app.py` and Streamlit Community Cloud.

The interface lives in supplier_agent/app.py so it also ships with the package
(`supplier-desk app`).
"""

import runpy
from pathlib import Path

import supplier_agent

runpy.run_path(str(Path(supplier_agent.__file__).resolve().parent / "app.py"), run_name="__main__")
