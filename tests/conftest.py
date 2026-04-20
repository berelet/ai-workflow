"""Test bootstrap. Adds repo root to sys.path so `dashboard.*` imports resolve.

We avoid importing FastAPI app or hitting the database — these are pure-unit
smoke tests for the clone-from-git feature helpers.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
