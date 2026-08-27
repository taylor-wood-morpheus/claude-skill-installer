#!/bin/zsh
# Launcher for the Quick Actions in ~/Library/Services.
#
# Services inherit a minimal PATH and no login shell, so two things have to be
# established here rather than assumed: an interpreter new enough for install.py
# (match statements and tarfile's data filter need 3.12+; the stock
# /usr/bin/python3 is 3.9), and a PATH that can find `claude` and `gh`.

set -u
HERE="${0:A:h}"
LOG="$HERE/install.log"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

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

# Which credential the frontmatter-synthesis call will bill is worth recording:
# it differs between a terminal run and a Quick Action run, because launchd does
# not source .zshrc. Presence only -- never log the value.
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  AUTH="api-key-env"
elif [[ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
  AUTH="auth-token-env"
else
  AUTH="claude-login"
fi

print -r -- "$(date '+%F %T') INFO    run.sh: interpreter=$PYTHON trigger=$1 claude_auth=$AUTH" >> "$LOG"
exec "$PYTHON" "$HERE/install.py" "$@"
