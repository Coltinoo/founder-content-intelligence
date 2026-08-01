"""Render every page headlessly against the live database and report exceptions.

Not a unit test — a pre-demo smoke check. Catches the class of bug that only
appears with real data in the tables (a None where the fixtures had a value,
a column the seed data never exercised).
"""
import _bootstrap  # noqa: F401
import pathlib
import sys

from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
pages = [ROOT / "streamlit_app.py", *sorted((ROOT / "pages").glob("*.py"))]

failures = 0
for page in pages:
    try:
        at = AppTest.from_file(str(page), default_timeout=120).run()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  {page.name}: {type(exc).__name__}: {exc}")
        failures += 1
        continue
    if at.exception:
        for e in at.exception:
            print(f"FAIL  {page.name}: {e.type}: {e.message}")
        failures += 1
    else:
        print(f"ok    {page.name}  "
              f"({len(at.markdown)} md, {len(at.metric)} metric, {len(at.button)} button)")

print(f"\n{len(pages) - failures}/{len(pages)} pages rendered clean")
sys.exit(1 if failures else 0)
