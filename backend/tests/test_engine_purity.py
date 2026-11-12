"""`engine/` is pure Python: it must not import Django (it is tested and run without a database)."""

import re
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
DJANGO_IMPORT = re.compile(r"^\s*(from|import)\s+(django|apps)\b", re.MULTILINE)


def test_engine_does_not_import_django_or_apps():
    offenders = [p.name for p in ENGINE_DIR.rglob("*.py") if DJANGO_IMPORT.search(p.read_text())]
    assert offenders == []
