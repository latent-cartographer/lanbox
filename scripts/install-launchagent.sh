#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${LANBOX_LAUNCHD_LABEL:-com.latent-cartographer.lanbox}"
PORT="${LANBOX_PORT:-8787}"
ACCESS_CODE="${LANBOX_ACCESS_CODE:-off}"
PYTHON_BIN="${LANBOX_PYTHON:-$(command -v python3)}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

"$PYTHON_BIN" - "$PLIST" "$LABEL" "$PROJECT_DIR" "$PYTHON_BIN" "$PORT" "$ACCESS_CODE" "$LOG_DIR" <<'PY'
import plistlib
import shlex
import sys

plist_path, label, project_dir, python_bin, port, access_code, log_dir = sys.argv[1:]
command = f"cd {shlex.quote(project_dir)} && exec {shlex.quote(python_bin)} server.py"
plist = {
    "Label": label,
    "ProgramArguments": ["/bin/zsh", "-lc", command],
    "EnvironmentVariables": {
        "LANBOX_ACCESS_CODE": access_code,
        "LANBOX_PORT": port,
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    },
    "WorkingDirectory": project_dir,
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 5,
    "StandardOutPath": f"{log_dir}/lanbox.out.log",
    "StandardErrorPath": f"{log_dir}/lanbox.err.log",
}
with open(plist_path, "wb") as out:
    plistlib.dump(plist, out)
PY

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "LanBox LaunchAgent installed: $PLIST"
echo "Label: $LABEL"
echo "Port: $PORT"
echo "Access code: $ACCESS_CODE"
