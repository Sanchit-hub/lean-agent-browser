"""leanb setup / doctor / uninstall: Claude Code registration, statuses, config checks (offline).

A fake `claude` CLI (same `mcp get / add-json / remove` behavior and output format as Claude Code 2.1)
runs everywhere; the real CLI is also exercised, under a throwaway HOME, when it is installed.
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from lean_browser import claude_code, doctor, onboarding

FAKE = textwrap.dedent('''\
    #!PYTHON
    import json, os, sys
    state = os.environ["FAKE_CLAUDE_STATE"]
    d = json.load(open(state)) if os.path.exists(state) else {}
    a = sys.argv[1:]
    assert a[0] == "mcp", a
    cmd, rest = a[1], a[2:]
    def save(): json.dump(d, open(state, "w"))
    if cmd == "get":
        e = d.get(rest[0])
        if not e:
            print(f'No MCP server named "{rest[0]}".'); sys.exit(1)
        print(f"{rest[0]}:\\n  Scope: User config (available in all your projects)\\n  Status: \\u2714 Connected\\n"
              f"  Type: stdio\\n  Command: {e['command']}\\n  Args: {' '.join(e['args'])}\\n  Environment:\\n")
    elif cmd == "add-json":
        scope, name, entry = rest[1], rest[2], json.loads(rest[3])
        if name in d:
            print(f"MCP server {name} already exists in {scope} config"); sys.exit(1)
        d[name] = entry; save(); print("Added")
    elif cmd == "remove":
        if rest[0] not in d:
            sys.exit(1)
        del d[rest[0]]; save(); print("Removed")
''')


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    exe = tmp_path / "bin with space" / "claude"
    exe.parent.mkdir()
    exe.write_text(FAKE.replace("PYTHON", sys.executable))
    exe.chmod(0o755)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"other-server": {"type": "stdio", "command": "/bin/echo", "args": ["hi"], "env": {}}}))
    monkeypatch.setenv("LEANB_CLAUDE", str(exe))
    monkeypatch.setenv("FAKE_CLAUDE_STATE", str(state))
    return SimpleNamespace(exe=str(exe), state=lambda: json.loads(state.read_text()))


def test_leanb_command_is_absolute():
    cmd = claude_code.leanb_command()
    assert Path(cmd[0]).is_absolute() and Path(cmd[0]).exists()


def test_register_update_and_remove_keep_other_servers(fake_claude, monkeypatch):
    monkeypatch.setattr(claude_code, "leanb_command", lambda: ["/opt/my tools/leanb"])
    ok, msg = claude_code.register(fake_claude.exe)
    assert ok and msg.startswith("added"), msg
    st = fake_claude.state()
    assert st["lean-browser"] == {"type": "stdio", "command": "/opt/my tools/leanb", "args": ["mcp"], "env": {}}
    assert "other-server" in st
    reg = claude_code.get_registration(fake_claude.exe)
    assert reg["command"] == "/opt/my tools/leanb" and reg["args"] == ["mcp"] and reg["scope"] == "user"
    # second run: no duplicate, no change
    ok, msg = claude_code.register(fake_claude.exe)
    assert ok and "nothing to change" in msg
    # a new install location replaces the entry instead of adding a second one
    monkeypatch.setattr(claude_code, "leanb_command", lambda: ["/new/leanb"])
    ok, msg = claude_code.register(fake_claude.exe)
    assert ok and msg.startswith("updated")
    assert fake_claude.state()["lean-browser"]["command"] == "/new/leanb"
    assert sorted(fake_claude.state()) == ["lean-browser", "other-server"]
    ok, msg = claude_code.unregister(fake_claude.exe)
    assert ok and list(fake_claude.state()) == ["other-server"]
    assert claude_code.unregister(fake_claude.exe) == (True, "no 'lean-browser' entry registered")


def test_doctor_claude_check(fake_claude, monkeypatch):
    c = doctor.check_claude()
    assert c.status == doctor.WARN and "setup --client claude" in c.fix
    claude_code.register(fake_claude.exe)
    assert doctor.check_claude().status == doctor.PASS
    monkeypatch.setattr(claude_code, "leanb_command", lambda: ["/gone/leanb"])
    claude_code.register(fake_claude.exe)
    c = doctor.check_claude()
    assert c.status == doctor.FAIL and "does not exist" in c.detail
    monkeypatch.setenv("LEANB_CLAUDE", "")
    monkeypatch.setattr(claude_code.shutil, "which", lambda _: None)
    assert doctor.check_claude().status == doctor.WARN


def test_setup_claude_asks_and_never_writes_without_consent(fake_claude, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", open(os.devnull))  # not a TTY
    assert onboarding.setup_claude(yes=False, scope="user") is False
    assert "lean-browser" not in fake_claude.state()
    out = capsys.readouterr().out
    assert "claude mcp add-json -s user lean-browser" in out and "--yes" in out
    assert onboarding.setup_claude(yes=True, scope="user") is True
    assert "lean-browser" in fake_claude.state()
    assert onboarding.setup_claude(yes=True, scope="user") is True
    assert "Nothing to change" in capsys.readouterr().out


def test_setup_config_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "HOME", tmp_path)
    monkeypatch.setattr(onboarding, "CONFIG", tmp_path / "config.toml")
    onboarding.setup_config(yes=True)
    import tomllib
    assert tomllib.loads((tmp_path / "config.toml").read_text()) == {}  # all defaults, commented out
    (tmp_path / "config.toml").write_text('prefer = "chromium"\n')
    onboarding.setup_config(yes=True)
    assert (tmp_path / "config.toml").read_text() == 'prefer = "chromium"\n'


def test_config_check(tmp_path):
    p = tmp_path / "c.toml"
    assert doctor.check_config(str(p)).status == doctor.PASS
    p.write_text("prefer = ")
    assert doctor.check_config(str(p)).status == doctor.FAIL
    p.write_text('prefre = "chromium"\n')
    c = doctor.check_config(str(p))
    assert c.status == doctor.WARN and "prefre" in c.detail
    p.write_text("allow_private_network = true\n")
    assert doctor.check_config(str(p)).status == doctor.WARN
    p.write_text('prefer = "chromium"\n')
    assert doctor.check_config(str(p)).status == doctor.PASS


def test_summary_never_hides_warnings():
    C = doctor.Check
    ok, text = doctor.summary([C("a", doctor.PASS, ""), C("b", doctor.WARN, ""), C("c", doctor.WARN, "")])
    assert ok and text == "all good: 1 passed, 2 warnings"
    ok, text = doctor.summary([C("a", doctor.PASS, ""), C("b", doctor.FAIL, ""), C("c", doctor.UNSUPPORTED, "")])
    assert not ok and text == "problems found: 1 passed, 1 failed, 1 not supported"


def test_doctor_json_shortens_home(monkeypatch):
    checks = [doctor.Check("x", doctor.PASS, str(Path.home() / "secret-folder"), "")]
    data = json.loads(doctor.to_json(checks))
    assert data["ok"] is True and data["checks"][0]["detail"] == "~/secret-folder"
    assert str(Path.home()) not in doctor.to_json(checks)


def test_cli_version():
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run([str(root / ".venv/bin/leanb"), "--version"], capture_output=True, text=True)
    from lean_browser import __version__
    assert out.stdout.strip() == f"leanb {__version__}"


@pytest.mark.skipif(not shutil.which("claude"), reason="Claude Code CLI not installed")
def test_real_claude_cli_registration(tmp_path, monkeypatch):
    """The real `claude mcp` commands, against a throwaway HOME: add, no duplicate, update, remove."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LEANB_CLAUDE", raising=False)
    monkeypatch.setattr(claude_code.Path, "home", classmethod(lambda cls: tmp_path))
    claude = shutil.which("claude")
    subprocess.run([claude, "mcp", "add", "-s", "user", "other-server", "--", "/bin/echo", "hi"], check=True,
                   capture_output=True, cwd=tmp_path)
    monkeypatch.setattr(claude_code, "leanb_command", lambda: [str(tmp_path / "dir with space" / "leanb")])
    assert claude_code.register(claude)[0]
    assert claude_code.register(claude)[1].endswith("nothing to change")
    servers = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]
    assert servers["lean-browser"]["command"] == str(tmp_path / "dir with space" / "leanb")
    assert servers["other-server"]["command"] == "/bin/echo"
    assert claude_code.unregister(claude)[0]
    assert list(json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]) == ["other-server"]
