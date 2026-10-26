#!/bin/zsh
# Launcher for the Quick Action in ~/Library/Services.
#
# Services inherit a minimal PATH and no login shell, so the interpreter has to
# be found here rather than assumed: install.py needs 3.12+, and the stock
# /usr/bin/python3 is 3.9.

set -u
HERE="${0:A:h}"
# Outside the code directory: Homebrew replaces that wholesale on upgrade.
export SKILL_INSTALLER_LOG="$HOME/Library/Logs/claude-skill-installer/install.log"
LOG="$SKILL_INSTALLER_LOG"
mkdir -p "${LOG:h}"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

PYTHON=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$HOME/.local/bin/python3" /usr/bin/python3; do
  if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  print -r -- "$(date '+%F %T') FATAL   run.sh: no python >= 3.12 found on PATH=$PATH" >> "$LOG"
  /usr/bin/osascript -e 'display alert "Add to Claude Skills" message "No Python 3.12 or newer was found. Install one with: brew install python" as warning' >/dev/null 2>&1
  exit 1
fi

print -r -- "$(date '+%F %T') INFO    run.sh: interpreter=$PYTHON trigger=${1:-}" >> "$LOG"
exec "$PYTHON" "$HERE/install.py" "$@"
