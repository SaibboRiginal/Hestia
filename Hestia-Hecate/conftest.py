"""Pytest configuration — adds the app/ directory to sys.path so internal
service imports (``from providers.registry import ...``, etc.) resolve
without needing to run from inside the app/ directory."""
import os
import sys

# Ensure Hestia-Hecate/app is on sys.path so intra-app imports work.
_app_dir = os.path.join(os.path.dirname(__file__), "app")
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)
