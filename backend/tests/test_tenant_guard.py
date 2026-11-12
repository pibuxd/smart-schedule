"""API code must read company data only through the tenant context (`ctx.qs(...)` / `for_company(...)`).

Any `.objects.` in an `apps/*/api.py` file must be followed by `for_company(`. A line that really needs
a global query (e.g. the login flow looking up a phone number) is marked with `# tenant-ok: <reason>`.
"""

import re
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent / "apps"
UNSCOPED = re.compile(r"\.objects\.(?!for_company\()")


def find_unscoped_queries() -> list[str]:
    problems = []
    for path in sorted(APPS_DIR.glob("*/api.py")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if UNSCOPED.search(line) and "# tenant-ok:" not in line:
                problems.append(f"{path.relative_to(APPS_DIR.parent)}:{number}: {line.strip()}")
    return problems


def test_api_code_reads_company_data_only_through_tenant_context():
    assert find_unscoped_queries() == []


def test_guard_pattern_catches_plain_objects():
    assert UNSCOPED.search("Location.objects.filter(id=x)")
    assert UNSCOPED.search("Location.objects.all()")
    assert not UNSCOPED.search("Location.objects.for_company(ctx.company).filter(id=x)")
    assert not UNSCOPED.search("ctx.qs(Location).filter(id=x)")
