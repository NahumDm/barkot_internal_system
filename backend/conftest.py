"""Shared pytest fixtures for the Barkot backend.

pytest-django configuration lives in pyproject.toml
([tool.pytest.ini_options]). Phase 0A adds no test database fixtures: the
backend has no models yet, so the test suite runs without touching a
database. Cross-domain fixtures are added here from Phase 1 onward.
"""
