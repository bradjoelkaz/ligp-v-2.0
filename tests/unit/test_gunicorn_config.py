"""Unit tests for the Gunicorn config (Phase 16).

``gunicorn.conf.py`` lives at the repository root and has a dot in its name, so
it cannot be imported with a normal ``import`` statement; we load it from its
file path via importlib. The module is designed to import cleanly *without*
gunicorn/prometheus installed (every third-party import lives inside the hooks),
so these tests run fully offline. The hooks' lazy imports are satisfied with
small fakes injected into ``sys.modules`` / patched onto ``api.metrics``.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

_CONF_PATH = Path(__file__).resolve().parents[2] / "gunicorn.conf.py"


def _load_conf():
    """Load gunicorn.conf.py as an isolated module from its file path."""
    spec = importlib.util.spec_from_file_location("iigp_gunicorn_conf", _CONF_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def conf():
    return _load_conf()


def test_config_file_exists():
    assert _CONF_PATH.is_file(), f"missing gunicorn config at {_CONF_PATH}"


def test_settings_bindings(conf):
    """Core server settings are present with the documented defaults."""
    assert conf.bind == "0.0.0.0:8000"
    assert conf.workers == 4
    assert conf.worker_class == "uvicorn.workers.UvicornWorker"


def test_hooks_are_callable(conf):
    assert callable(conf.on_starting)
    assert callable(conf.child_exit)


def test_on_starting_calls_cleanup(conf):
    """on_starting must invoke api.metrics.cleanup_multiprocess_dir exactly once."""
    with mock.patch("api.metrics.cleanup_multiprocess_dir") as cleanup:
        conf.on_starting(server=mock.Mock())
    cleanup.assert_called_once_with()


def test_on_starting_is_exception_safe(conf):
    """A cleanup failure must never propagate out of the startup hook."""
    with mock.patch("api.metrics.cleanup_multiprocess_dir", side_effect=RuntimeError("boom")):
        # Should not raise.
        conf.on_starting(server=mock.Mock())


def test_child_exit_marks_process_dead(conf, monkeypatch):
    """child_exit must forward the dead worker PID to multiprocess.mark_process_dead."""
    fake_multiprocess = types.SimpleNamespace(mark_process_dead=mock.Mock())
    fake_pkg = types.ModuleType("prometheus_client")
    fake_pkg.multiprocess = fake_multiprocess
    monkeypatch.setitem(sys.modules, "prometheus_client", fake_pkg)

    worker = mock.Mock()
    worker.pid = 4321
    conf.child_exit(server=mock.Mock(), worker=worker)

    fake_multiprocess.mark_process_dead.assert_called_once_with(4321)


def test_child_exit_is_exception_safe(conf, monkeypatch):
    """If prometheus_client is unavailable, child_exit must swallow the error."""
    # Ensure the import fails inside the hook.
    monkeypatch.setitem(sys.modules, "prometheus_client", None)
    # Should not raise even though `from prometheus_client import multiprocess` fails.
    conf.child_exit(server=mock.Mock(), worker=mock.Mock(pid=1))
