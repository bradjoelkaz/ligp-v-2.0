"""Tests for production-mode runtime helpers (utils/runtime.py)."""

from __future__ import annotations

from utils import runtime


def test_is_production_from_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert runtime.is_production() is True
    assert runtime.app_env() == "production"


def test_not_production_default(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    assert runtime.is_production() is False


def test_mock_allowed_outside_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("IIGP_ALLOW_MOCK", raising=False)
    assert runtime.mock_allowed() is True


def test_mock_blocked_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("IIGP_ALLOW_MOCK", raising=False)
    assert runtime.mock_allowed() is False


def test_mock_override_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("IIGP_ALLOW_MOCK", "1")
    assert runtime.mock_allowed() is True
