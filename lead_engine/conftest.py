"""Shared deterministic fixtures for the lead-engine test suite.

Production still requires explicit Airtable credentials. Tests that exercise
URL construction use an inert base identifier unless they deliberately remove
or override it to test missing-configuration behavior.
"""
import pytest


@pytest.fixture(autouse=True)
def _default_airtable_base_for_url_only_tests(monkeypatch):
    monkeypatch.setenv("AIRTABLE_BASE_ID", "app12345678901234")
