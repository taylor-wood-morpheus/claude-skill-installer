#!/bin/zsh
# Install the "Add Selected Text to Claude Skills" Quick Action for the current user.
# Idempotent: safe to re-run to pick up changes.

set -eu
HERE="${0:A:h}"
TOOL_DIR="$HOME/.claude/tools/skill-installer"

print "Checking prerequisites…"

if [[ "$(uname)" != "Darwin" ]]; then
  print -u2 "  ✗ macOS only: this installs macOS Quick Actions (Services)."
  exit 1
fi

PYTHON=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$HOME/.local/bin/python3" /usr/bin/python3; do
  if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PYTHON="$candidate"; break
  fi
done
if [[ -z "$PYTHON" ]]; then
  print -u2 "  ✗ No Python 3.12+ found. Install one:  brew install python"
  exit 1
fi
print "  ✓ python $($PYTHON -c 'import sys; print(sys.version.split()[0])') at $PYTHON"

print "\nInstalling engine to $TOOL_DIR…"
mkdir -p "$TOOL_DIR"
for f in install.py run.sh setup.py make_quick_actions.py; do
  install -m 755 "$HERE/$f" "$TOOL_DIR/$f"
done
for f in services.py action_template.b64; do
  install -m 644 "$HERE/$f" "$TOOL_DIR/$f"
done
print "  ✓ copied"

# Run the installed copy, not this checkout: the bundles point at the run.sh
# beside whichever setup.py generated them.
print
"$PYTHON" "$TOOL_DIR/setup.py"

cat <<'DONE'

Installed. Select a skill's text anywhere, right-click, then
  Services  →  Add Selected Text to Claude Skills

The text must start with frontmatter giving the skill's name and description.
Log:  ~/Library/Logs/claude-skill-installer/install.log
DONE
