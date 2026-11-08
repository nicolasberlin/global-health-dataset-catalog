"""Stable project and fixture paths, independent of test module depth."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = PROJECT_ROOT / "tests"
FIXTURES_ROOT = TEST_ROOT / "fixtures"
