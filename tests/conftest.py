import os
import sys
from pathlib import Path

# Ensure `app` package is importable when tests are run from repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MANAGER_EMAIL", "manager@example.com")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

