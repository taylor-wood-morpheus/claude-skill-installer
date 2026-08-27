#!/bin/zsh
# Remove the Quick Actions and the engine. Installed skills are left alone.
set -eu
for name in "Add to Claude Skills" "Add Selected Text to Claude Skills" "Add Clipboard to Claude Skills"; do
  bundle="$HOME/Library/Services/$name.workflow"
  if [[ -d "$bundle" ]]; then rm -rf "$bundle"; print "removed $name.workflow"; fi
done
rm -rf "$HOME/.claude/tools/skill-installer"
print "removed ~/.claude/tools/skill-installer"
/System/Library/CoreServices/pbs -flush
print "flushed. Skills already in ~/.claude/skills were not touched."
