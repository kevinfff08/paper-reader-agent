"""Exercise Windows launcher failure paths without installing or launching apps."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows batch launcher")
@pytest.mark.parametrize("failure", ["install", "build"])
def test_build_failure_never_launches_stale_frontend(tmp_path, failure):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "start.bat").write_bytes((root / "start.bat").read_bytes())
    (tmp_path / ".env").write_text("LLM_MODE=api-key\n", encoding="ascii")
    frontend = tmp_path / "frontend"
    (frontend / "dist").mkdir(parents=True)
    (frontend / "dist/index.html").write_text("stale", encoding="ascii")
    if failure == "build":
        (frontend / "node_modules").mkdir()
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "conda.cmd").write_text("@exit /b 0\n", encoding="ascii")
    (commands / "npm.cmd").write_text("@exit /b 23\n", encoding="ascii")
    marker = tmp_path / "launched.txt"
    (commands / "python.cmd").write_text(f'@echo launched > "{marker}"\n', encoding="ascii")
    env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["SystemRoot"] + "\\System32",
               LLM_MODE="api-key", PAPERREADER_SKIP_BUILD="0")
    result = subprocess.run([os.environ["COMSPEC"], "/d", "/c", str(tmp_path / "start.bat")],
                            cwd=tmp_path, env=env, input="\n", capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "Startup cancelled" in result.stdout
    assert not marker.exists()
