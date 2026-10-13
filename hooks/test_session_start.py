import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "session_start.py"
ROOT = str(SCRIPT.parent.parent)
SECRET = "ZZsecretZZ"


def run(**env):
    base = {k: v for k, v in os.environ.items() if k not in ("MI_DB_SMARTPHONE", "MI_MINIO")}
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True,
                       env={**base, "CLAUDE_PLUGIN_ROOT": ROOT, **env})
    assert r.returncode == 0
    out, err = r.stdout.decode("utf-8"), r.stderr.decode("utf-8", "replace")
    assert SECRET not in out and SECRET not in err
    hso = json.loads(out)["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    ctx = hso["additionalContext"]
    assert "mi-sonar:mi-sonar" in ctx and len(ctx) <= 600
    return ctx


def test_env_set_says_configured_without_values():
    ctx = run(MI_DB_SMARTPHONE=SECRET, MI_MINIO=SECRET)
    assert "환경변수 설정됨" in ctx and "install.ps1" not in ctx


def test_env_missing_names_vars_and_installer():
    ctx = run(MI_DB_SMARTPHONE=SECRET)
    assert "MI_MINIO" in ctx and "MI_DB_SMARTPHONE" not in ctx
    assert os.path.join(ROOT, "install.ps1") in ctx
    ctx = run()
    assert "MI_DB_SMARTPHONE, MI_MINIO 없음" in ctx
