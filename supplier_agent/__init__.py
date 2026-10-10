"""Supplier Integrity Desk — explainable supplier duplicate and data-quality review."""

__version__ = "1.0.0"

from .detector import DetectionConfig, DuplicateDetector
from .io import load_supplier_master
from .triage import ScanResult, scan_suppliers

__all__ = [
    "DetectionConfig",
    "DuplicateDetector",
    "ScanResult",
    "__version__",
    "load_supplier_master",
    "scan_suppliers",
]


def __getattr__(name: str):
    # The LangGraph workflow is imported lazily so a plain scan stays light.
    if name == "build_investigation_graph":
        from .workflow import build_investigation_graph

        return build_investigation_graph
    raise AttributeError(name)
