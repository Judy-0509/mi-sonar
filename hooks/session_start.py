"""mi-sonar SessionStart hook: tells the agent to use the skill and whether env vars are set.

Stdlib only. Checks env var presence, never prints values. Never raises.
"""
import json
import os
import sys

ENV_VARS = ("MI_DB_SMARTPHONE", "MI_MINIO")


def context() -> str:
    text = (
        "mi-sonar 플러그인 활성. MI 시장 데이터(스마트폰·스마트워치·증권사 레포트) 조회와 보고 자료 작성 요청은 "
        "사용자가 스킬 이름을 말하지 않아도 `mi-sonar:mi-sonar` 스킬을 먼저 읽고 그 절차대로 진행한다. "
        "숫자는 지어내지 않고 query.py 로만 조회한다. "
    )
    missing = [k for k in ENV_VARS if not os.environ.get(k)]
    if not missing:
        return text + "환경변수 설정됨."
    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    install = os.path.join(root, "install.ps1") if root else "install.ps1"
    return text + (
        f"환경변수 {', '.join(missing)} 없음 → PowerShell 에서 "
        f'`powershell -ExecutionPolicy Bypass -File "{install}"` 실행을 안내할 것 (값을 묻거나 출력하지 않는다).'
    )


def main() -> None:
    try:
        ctx = context()
    except Exception:
        ctx = "mi-sonar 플러그인 활성. MI 시장 데이터 요청은 `mi-sonar:mi-sonar` 스킬을 먼저 읽는다."
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}
    try:
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
        sys.stdout.flush()
    except Exception:
        pass


if __name__ == "__main__":
    main()
