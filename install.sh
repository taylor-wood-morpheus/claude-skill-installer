#!/bin/zsh
# Install the "Add to Claude Skills" Quick Actions for the current user.
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

if command -v claude >/dev/null 2>&1; then
  print "  ✓ claude CLI found (used to name skills that arrive without frontmatter)"
else
  print "  ! claude CLI not on PATH — skills pasted without name/description will be rejected"
fi

if command -v gh >/dev/null 2>&1 && gh auth token >/dev/null 2>&1; then
  print "  ✓ gh authenticated (private repos and higher GitHub rate limits)"
else
  print "  ! gh not authenticated — public GitHub only, 60 requests/hour"
fi

print "\nInstalling engine to $TOOL_DIR…"
mkdir -p "$TOOL_DIR"
install -m 755 "$HERE/install.py" "$TOOL_DIR/install.py"
install -m 755 "$HERE/run.sh"     "$TOOL_DIR/run.sh"
install -m 755 "$HERE/set_hotkey.py" "$TOOL_DIR/set_hotkey.py"
install -m 644 "$HERE/services.py"   "$TOOL_DIR/services.py"
print "  ✓ install.py, run.sh, set_hotkey.py, services.py"

print "\nGenerating Quick Actions…"
"$PYTHON" "$HERE/make_quick_actions.py"

print "\nBuilding Claude Skills.app…"
"$PYTHON" "$HERE/make_app.py"

print "\nRegistering with the Services system…"
/System/Library/CoreServices/pbs -flush
print "  ✓ flushed"

cat <<'DONE'

Installed. Four ways in:

  1. Finder      right-click a zip / folder / .md  →  Add to Claude Skills
  2. Any text    select it  →  right-click  →  Services
                 →  Add Selected Text to Claude Skills
  3. Clipboard   copy a GitHub URL or skill text  →  press  ⌃⌥⌘S
  4. Anywhere    ⌘-space  →  "Claude Skills"  →  add from clipboard, or
                 view and change the shortcuts

Actions 1 and 2 are Services and appear in the context menu. Action 3 takes no
input, so macOS will not list it in any Services menu -- the hotkey and the app
in 4 are the ways to reach it.
Log:  ~/.claude/tools/skill-installer/install.log
DONE
