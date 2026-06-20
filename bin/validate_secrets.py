"""Production secrets validation (Phase 13).

Scans ``.env.production`` (and/or OS environment) for the credentials the live
platform needs across collection, AI, publishing, alerting and security, and
prints a structured, **masked** report. Optionally runs lightweight live health
pings per channel when ``--check-network`` is passed and the network is open.

Usage:
    python -m bin.validate_secrets [--env .env.production] [--check-network]

Exit code is 0 when all *required* secrets (and at least one AI key) are present,
1 otherwise \u2014 suitable as a deploy pre-flight gate. Secret values are never
printed in full: only the first/last 4 characters are shown.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any

# (name, group, level): level in {"required", "any_of", "optional"}.
SPECS: list[tuple[str, str, str]] = [
    ("YOUTUBE_API_KEY", "collection", "required"),
    ("NAVER_CLIENT_ID", "collection", "required"),
    ("NAVER_CLIENT_SECRET", "collection", "required"),
    ("OPENROUTER_API_KEY", "ai", "any_of"),
    ("GEMINI_API_KEY", "ai", "any_of"),
    ("ADMIN_API_KEY", "security", "required"),
    ("SLACK_WEBHOOK_URL", "alerting", "optional"),
    ("TISTORY_ACCESS_TOKEN", "publishing", "optional"),
    ("SUBSTACK_API_KEY", "publishing", "optional"),
    ("MAILCHIMP_API_KEY", "publishing", "optional"),
    ("SUNO_COOKIE", "publishing", "optional"),
    ("WORDPRESS_APP_PASSWORD", "publishing", "optional"),
]

# Placeholder values from the example file that should count as "not set".
_PLACEHOLDER_MARKERS = ("change_me", "your_", "...", "here")


def mask(value: str) -> str:
    """Mask a secret, revealing only the first and last 4 characters."""
    if not value:
        return "<missing>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def _is_set(value: str | None) -> bool:
    if not value or not value.strip():
        return False
    return not any(m in value.lower() for m in _PLACEHOLDER_MARKERS)


def parse_env_file(path: str) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` .env file into a dict (ignores comments/blanks)."""
    env: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                # strip inline comments + surrounding quotes/space
                val = val.split("#", 1)[0].strip().strip("'\"")
                env[key.strip()] = val
    except FileNotFoundError:
        return {}
    return env


def validate(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Validate required/optional secrets in ``env`` (defaults to os.environ)."""
    env = dict(os.environ) if env is None else env

    secrets: list[dict[str, Any]] = []
    groups_any_ok: dict[str, bool] = {}
    required_ok = True

    for name, group, level in SPECS:
        present = _is_set(env.get(name))
        if level == "required":
            status = "ok" if present else "missing"
            if not present:
                required_ok = False
        elif level == "any_of":
            status = "ok" if present else "absent"
            groups_any_ok[group] = groups_any_ok.get(group, False) or present
        else:  # optional
            status = "ok" if present else "skip"
        secrets.append(
            {
                "name": name,
                "group": group,
                "level": level,
                "present": present,
                "status": status,
                "masked": mask(env.get(name, "")),
            }
        )

    any_of_ok = all(groups_any_ok.values()) if groups_any_ok else True
    overall_ok = required_ok and any_of_ok
    return {
        "ok": overall_ok,
        "required_ok": required_ok,
        "any_of_ok": any_of_ok,
        "secrets": secrets,
        "groups_any_of": groups_any_ok,
    }


def run_network_checks(
    env: dict[str, str], pinger: Callable[[str, str], bool] | None = None
) -> list[dict[str, Any]]:
    """Run lightweight per-channel health pings (only for keys that are set)."""
    ping = pinger or _default_ping
    results: list[dict[str, Any]] = []
    for name in ("YOUTUBE_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        value = env.get(name, "")
        if not _is_set(value):
            continue
        try:
            ok = bool(ping(name, value))
        except Exception:  # noqa: BLE001 - a failed ping must not crash validation
            ok = False
        results.append({"name": name, "reachable": ok})
    return results


def _default_ping(name: str, value: str) -> bool:  # pragma: no cover - real network
    """Best-effort live health ping for a channel key."""
    import httpx

    try:
        with httpx.Client(timeout=10.0) as client:
            if name == "YOUTUBE_API_KEY":
                r = client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={"part": "id", "chart": "mostPopular", "maxResults": 1, "key": value},
                )
                return r.status_code == 200
            if name == "GEMINI_API_KEY":
                r = client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": value},
                )
                return r.status_code == 200
            if name == "OPENROUTER_API_KEY":
                r = client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {value}"},
                )
                return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False
    return False


def format_report(report: dict[str, Any], network: list[dict[str, Any]] | None = None) -> str:
    """Render a human-readable, masked report for terminal + server logs."""
    lines = ["=== IIGP Secrets Validation ==="]
    by_group: dict[str, list[dict[str, Any]]] = {}
    for s in report["secrets"]:
        by_group.setdefault(s["group"], []).append(s)
    icons = {"ok": "[OK]", "missing": "[MISSING]", "absent": "[--]", "skip": "[skip]"}
    for group in sorted(by_group):
        lines.append(f"\n# {group}")
        for s in by_group[group]:
            icon = icons.get(s["status"], "[?]")
            lines.append(f"  {icon} {s['name']} = {s['masked']} ({s['level']})")
    if network:
        lines.append("\n# network health")
        for n in network:
            lines.append(f"  {'[OK]' if n['reachable'] else '[UNREACHABLE]'} {n['name']}")
    lines.append(f"\nRESULT: {'PASS' if report['ok'] else 'FAIL'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: validate, print masked report, return exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    env_path = ".env.production"
    check_network = "--check-network" in argv
    if "--env" in argv:
        env_path = argv[argv.index("--env") + 1]

    merged = parse_env_file(env_path)
    merged.update({k: v for k, v in os.environ.items()})  # OS env overrides file

    report = validate(merged)
    network = run_network_checks(merged) if check_network else None
    print(format_report(report, network))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
