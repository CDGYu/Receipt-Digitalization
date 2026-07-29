"""The export path must not drag FastAPI in.

``receipts export`` builds a workbook from ORM rows. It has no business
requiring the web framework, and a machine that only runs the CLI should not
need the ``api`` extra installed. This is enforced in a subprocess because the
rest of the suite imports FastAPI freely -- once it is in ``sys.modules`` an
in-process assertion proves nothing.
"""

from __future__ import annotations

import subprocess
import sys


def _imports_cleanly(module: str, forbidden: str) -> subprocess.CompletedProcess[str]:
    code = (
        f"import {module}, sys; "
        f"assert '{forbidden}' not in sys.modules, "
        f"'{module} pulled in {forbidden}'"
    )
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )


def test_serializers_import_without_fastapi():
    result = _imports_cleanly("receipts.review.serializers", "fastapi")
    assert result.returncode == 0, result.stderr


def test_signing_imports_without_fastapi():
    result = _imports_cleanly("receipts.review.signing", "fastapi")
    assert result.returncode == 0, result.stderr
