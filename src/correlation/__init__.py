"""
Correlation engine for cross-referencing data sources and detecting fraud indicators.

Modules:
- engine: Core correlation logic and fraud detection
- post_import: Post-import analysis hook
"""

from .engine import CorrelationEngine, FraudIndicator, FlagType, Severity
from .post_import import run_post_import_analysis, quick_scan_new_data

__all__ = [
    "CorrelationEngine", 
    "FraudIndicator", 
    "FlagType", 
    "Severity",
    "run_post_import_analysis",
    "quick_scan_new_data"
]
