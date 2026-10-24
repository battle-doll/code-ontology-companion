"""Actual filesystem permissions for synthetic test-only identity fixtures."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_windows_validation import protect_private_path

__all__ = ["protect_private_path"]
