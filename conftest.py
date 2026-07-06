"""Repo-root conftest: makes the suite location-independent.

- Puts the repo root on sys.path so `import scoring` etc. resolve.
- chdirs every test to the repo root so tests may open
  `data/mock_leads.csv` with a relative path regardless of where
  pytest was invoked from.
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


@pytest.fixture(autouse=True)
def _run_from_repo_root(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
