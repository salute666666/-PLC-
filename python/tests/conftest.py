"""Test fixtures.

DSH runs commands at low integrity on this machine, and pytest's own
``tmp_path``/``basetemp`` machinery creates directories it then cannot list.
The ``workdir`` fixture creates plain directories under the repository
instead, which works in both sandboxed and normal shells.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1] / ".testwork"


@pytest.fixture()
def workdir() -> Path:
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / uuid.uuid4().hex[:10]
    os.makedirs(path, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
