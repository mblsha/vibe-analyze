import os
import sys
import pathlib


def pytest_sessionstart(session):
    # Ensure src/ is importable
    root = pathlib.Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    # Provide a dummy Gemini key in case something leaks
    os.environ.setdefault("GOOGLE_API_KEY", "DUMMY")
