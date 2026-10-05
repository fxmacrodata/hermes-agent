"""Plugin-registered computer_use backends: ``computer_use.backend`` selects the driver per profile, the built-in
cua-driver stays the default, and an unregistered name fails loudly instead of falling back."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import hermes_yaml as yaml
from hermes_constants import reset_hermes_home_override, set_hermes_home_override

_PLUGIN = '''
from tools.computer_use.backend import ActionResult, ComputerUseBackend, ComputerUseProvider

CALLS = []

class FakeBackend(ComputerUseBackend):
    def __init__(self, tag, mode):
        self.tag, self.mode = tag, mode
    def start(self): CALLS.append((self.tag, "start", self.mode))
    def stop(self): CALLS.append((self.tag, "stop", None))
    def is_available(self): return True
    def capture(self, mode="som", app=None, pid=None, window_id=None): raise NotImplementedError
    def click(self, **kw):
        CALLS.append((self.tag, "click", kw.get("element")))
        return ActionResult(ok=True, action="click")
    def drag(self, **kw): return ActionResult(ok=True, action="drag")
    def scroll(self, **kw): return ActionResult(ok=True, action="scroll")
    def type_text(self, text, **kw): return ActionResult(ok=True, action="type")
    def key(self, keys, **kw): return ActionResult(ok=True, action="key")
    def list_apps(self): return [{"backend": self.tag, "home": __file__}]
    def focus_app(self, app, raise_window=False): return ActionResult(ok=True, action="focus_app")
    def set_value(self, value, element=None): return ActionResult(ok=True, action="set_value")

class FakeProvider(ComputerUseProvider):
    def __init__(self, tag): self._tag = tag
    @property
    def name(self): return self._tag
    def create_backend(self, *, permission_mode): return FakeBackend(self._tag, permission_mode)

def register(ctx):
    ctx.register_computer_use_provider(FakeProvider("alpha"))
    ctx.register_computer_use_provider(FakeProvider("beta"))
'''


def _home(home: Path, plugin: str, backend: str | None) -> Path:
    (plugin_dir := home / "plugins" / plugin).mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(yaml.safe_dump({"name": plugin, "version": "0.1.0"}))
    (plugin_dir / "__init__.py").write_text(_PLUGIN)
    cfg: dict = {"plugins": {"enabled": [plugin]}}
    if backend:
        cfg["computer_use"] = {"backend": backend}
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    return home


def _list_apps(session_id: str = "s1") -> list:
    from tools.computer_use.tool import handle_computer_use
    out = json.loads(handle_computer_use({"action": "list_apps"}, session_id=session_id))
    assert "apps" in out, out
    return out["apps"]


@pytest.fixture(autouse=True)
def _clean():
    from agent import computer_use_registry
    from tools.computer_use.tool import reset_backend_for_tests
    reset_backend_for_tests()
    yield
    reset_backend_for_tests()
    with computer_use_registry._registry._lock:
        computer_use_registry._registry._scoped_providers.clear()  # plugin registrations; the built-in cua stays


def test_plugin_backend_selected_by_config_receives_tool_calls(tmp_path, grant_computer_use_approvals):
    home = _home(tmp_path / "home", "fake-cu", "beta")
    tok = set_hermes_home_override(str(home))
    try:
        from tools.computer_use.tool import check_computer_use_requirements, handle_computer_use
        assert check_computer_use_requirements() is True
        assert _list_apps()[0]["backend"] == "beta"
        assert json.loads(handle_computer_use({"action": "click", "element": 3}, session_id="s1"))["ok"] is True
        from agent.computer_use_registry import get_active_provider
        calls = sys.modules[type(get_active_provider()).__module__].CALLS
        assert ("beta", "start", "standard") in calls and ("beta", "click", 3) in calls
        assert not any(tag == "alpha" for tag, *_ in calls)
    finally:
        reset_hermes_home_override(tok)


def test_unregistered_backend_errors_naming_configured_and_available(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(yaml.safe_dump({"computer_use": {"backend": "nope"}}))
    tok = set_hermes_home_override(str(home))
    try:
        from tools.computer_use.tool import check_computer_use_requirements, handle_computer_use
        out = json.loads(handle_computer_use({"action": "list_apps"}, session_id="s1"))
        assert "'nope'" in out["error"] and "available: cua" in out["error"]
        assert "hint" not in out  # the cua-driver install hint would mislead here
        assert check_computer_use_requirements() is True  # the tool stays visible so the call can say why
    finally:
        reset_hermes_home_override(tok)


@pytest.mark.parametrize("backend", [None, "cua"])
def test_builtin_cua_is_default_and_explicitly_selectable(tmp_path, backend):
    home = _home(tmp_path / "home", "fake-cu", backend)  # a plugin backend is registered but not selected
    tok = set_hermes_home_override(str(home))
    try:
        from agent.computer_use_registry import get_active_provider
        from tools.computer_use.cua_backend import CuaDriverBackend
        from tools.computer_use.tool import _new_backend
        assert get_active_provider().name == "cua"
        assert isinstance(_new_backend("standard"), CuaDriverBackend)
    finally:
        reset_hermes_home_override(tok)


def test_each_profile_gets_its_own_configured_backend(tmp_path):
    home_a = _home(tmp_path / "profiles" / "a", "fake-cu-a", "alpha")
    home_b = _home(tmp_path / "profiles" / "b", "fake-cu-b", "beta")
    for home, expected in ((home_a, "alpha"), (home_b, "beta"), (home_a, "alpha")):
        tok = set_hermes_home_override(str(home))
        try:
            app = _list_apps(session_id="shared")[0]
            assert app["backend"] == expected and str(home) in app["home"]
        finally:
            reset_hermes_home_override(tok)
