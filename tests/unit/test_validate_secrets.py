"""Tests for the production secrets validator (bin/validate_secrets.py)."""

from __future__ import annotations

from bin import validate_secrets as vs

_FULL_ENV = {
    "YOUTUBE_API_KEY": "yt_abcdef123456",
    "NAVER_CLIENT_ID": "naver_id_xxxx",
    "NAVER_CLIENT_SECRET": "naver_secret_yyyy",
    "OPENROUTER_API_KEY": "sk-or-abcdef",
    "ADMIN_API_KEY": "admin-secret-key-1234",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/abc",
}


# --- masking ---------------------------------------------------------------


def test_mask_long_value():
    assert vs.mask("abcdefghijklmnop") == "abcd********mnop"


def test_mask_short_value_fully_hidden():
    assert vs.mask("abcd") == "****"


def test_mask_missing():
    assert vs.mask("") == "<missing>"


# --- validate --------------------------------------------------------------


def test_validate_all_required_present_passes():
    report = vs.validate(_FULL_ENV)
    assert report["ok"] is True
    assert report["required_ok"] is True
    assert report["any_of_ok"] is True


def test_validate_missing_required_fails():
    env = dict(_FULL_ENV)
    del env["YOUTUBE_API_KEY"]
    report = vs.validate(env)
    assert report["ok"] is False
    miss = [s for s in report["secrets"] if s["name"] == "YOUTUBE_API_KEY"][0]
    assert miss["status"] == "missing"


def test_validate_any_of_satisfied_by_gemini():
    env = dict(_FULL_ENV)
    del env["OPENROUTER_API_KEY"]
    env["GEMINI_API_KEY"] = "gem-123456789"
    assert vs.validate(env)["ok"] is True


def test_validate_no_ai_key_fails():
    env = dict(_FULL_ENV)
    del env["OPENROUTER_API_KEY"]
    report = vs.validate(env)
    assert report["any_of_ok"] is False
    assert report["ok"] is False


def test_validate_placeholder_counts_as_missing():
    env = dict(_FULL_ENV)
    env["YOUTUBE_API_KEY"] = "CHANGE_ME_youtube_data_api_v3_key"
    assert vs.validate(env)["ok"] is False


def test_validate_optional_missing_is_skip():
    env = dict(_FULL_ENV)
    report = vs.validate(env)
    suno = [s for s in report["secrets"] if s["name"] == "SUNO_COOKIE"][0]
    assert suno["status"] == "skip"
    assert report["ok"] is True  # optional missing doesn't fail


# --- env file parsing ------------------------------------------------------


def test_parse_env_file(tmp_path):
    p = tmp_path / ".env.production"
    p.write_text(
        "# comment\nYOUTUBE_API_KEY=abc123  # inline\n\nADMIN_API_KEY='quoted'\nBAD LINE\n",
        encoding="utf-8",
    )
    env = vs.parse_env_file(str(p))
    assert env["YOUTUBE_API_KEY"] == "abc123"
    assert env["ADMIN_API_KEY"] == "quoted"
    assert "BAD LINE" not in env


def test_parse_env_file_missing_returns_empty():
    assert vs.parse_env_file("/nonexistent/.env") == {}


# --- network checks --------------------------------------------------------


def test_network_checks_only_for_set_keys():
    calls = []

    def pinger(name, value):
        calls.append(name)
        return True

    results = vs.run_network_checks(_FULL_ENV, pinger=pinger)
    names = {r["name"] for r in results}
    assert names == {"YOUTUBE_API_KEY", "OPENROUTER_API_KEY"}  # no GEMINI key set
    assert all(r["reachable"] for r in results)


def test_network_check_failure_is_caught():
    def bad_ping(name, value):
        raise RuntimeError("boom")

    results = vs.run_network_checks(_FULL_ENV, pinger=bad_ping)
    assert all(r["reachable"] is False for r in results)


# --- report formatting + main ----------------------------------------------


def test_format_report_masks_and_shows_result():
    report = vs.validate(_FULL_ENV)
    text = vs.format_report(report)
    assert "RESULT: PASS" in text
    # full secret value never appears
    assert "naver_secret_yyyy" not in text
    assert "[OK] ADMIN_API_KEY" in text


def test_main_returns_zero_on_pass(monkeypatch):
    monkeypatch.setattr(vs, "parse_env_file", lambda p: dict(_FULL_ENV))
    monkeypatch.setattr(vs.os, "environ", {})
    assert vs.main([]) == 0


def test_main_returns_one_on_fail(monkeypatch):
    monkeypatch.setattr(vs, "parse_env_file", lambda p: {})
    monkeypatch.setattr(vs.os, "environ", {})
    assert vs.main(["--env", ".env.production"]) == 1
