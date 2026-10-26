#!/bin/zsh
# Remove the Quick Actions, the app and the engine. Installed skills are left alone.
set -eu
TOOL_DIR="$HOME/.claude/tools/skill-installer"
if [[ -f "$TOOL_DIR/setup.py" ]]; then
  /usr/bin/python3 "$TOOL_DIR/setup.py" --remove
fi
rm -rf "$TOOL_DIR"
print "removed $TOOL_DIR"
