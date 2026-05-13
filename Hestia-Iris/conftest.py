"""Pytest configuration — adds the app/ directory to sys.path so internal
service imports (``from utils import ...``, etc.) resolve correctly when
running tests from the Hestia-Iris root."""
import os
import sys

_app_dir = os.path.join(os.path.dirname(__file__), "app")
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)
