# Make backend/ importable so tests can `from app.agent.sql_guard import ...`
# without installing the app as a package.
import os
import sys

BACKEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "backend")
)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
