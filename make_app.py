#!/usr/bin/env python3
"""Create "Claude Skills.app" in ~/Applications.

Two of the actions take no input, and a macOS Service whose NSSendTypes is empty
matches no context, so it is never shown in any Services menu -- it is reachable
only by a keyboard shortcut, if that works at all. An application bundle is the
reliable home for them: Spotlight indexes it, so ⌘-space "Claude Skills" always
finds it, and it can be double-clicked or kept in the Dock.

The bundle is written locally rather than downloaded, so it carries no quarantine
flag and Gatekeeper does not object.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

APPS = Path.home() / "Applications"
APP_NAME = "Claude Skills"
BUNDLE_ID = "local.claude-skill-installer.menu"
RUNNER = "$HOME/.claude/tools/skill-installer/run.sh"

LAUNCHER = f'''#!/bin/zsh
# Front door for the two actions that take no input. Both are also reachable
# from the Services menu only in theory -- see make_app.py.
set -u

ADD="Add skill from the clipboard"
KEYS="Shortcuts…"

choice=$(/usr/bin/osascript <<'APPLESCRIPT'
set options to {{"Add skill from the clipboard", "Shortcuts…"}}
set chosen to choose from list options ¬
    with title "Claude Skills" ¬
    with prompt "What would you like to do?" ¬
    default items {{"Add skill from the clipboard"}} ¬
    OK button name "Continue" cancel button name "Close"
if chosen is false then return ""
return item 1 of chosen
APPLESCRIPT
)

case "$choice" in
  "$ADD")  exec "{RUNNER}" clipboard ;;
  "$KEYS") exec "{RUNNER}" hotkey ;;
  *)       exit 0 ;;
esac
'''

INFO = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleIdentifier": BUNDLE_ID,
    "CFBundleExecutable": "claude-skills",
    "CFBundlePackageType": "APPL",
    "CFBundleInfoDictionaryVersion": "6.0",
    "CFBundleShortVersionString": "1.0",
    "CFBundleVersion": "1",
    "LSMinimumSystemVersion": "12.0",
    # A dialog utility has no windows of its own; keep it out of the Dock.
    "LSUIElement": True,
}


def build() -> Path:
    APPS.mkdir(parents=True, exist_ok=True)
    bundle = APPS / f"{APP_NAME}.app"
    shutil.rmtree(bundle, ignore_errors=True)

    macos = bundle / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(INFO))
    launcher = macos / "claude-skills"
    launcher.write_text(LAUNCHER)
    launcher.chmod(0o755)

    # Nudge Launch Services and Spotlight so ⌘-space finds it immediately.
    subprocess.run(
        [
            "/System/Library/Frameworks/CoreServices.framework/Frameworks"
            "/LaunchServices.framework/Support/lsregister",
            "-f",
            str(bundle),
        ],
        capture_output=True,
        check=False,
    )
    subprocess.run(["mdimport", str(bundle)], capture_output=True, check=False)
    return bundle


if __name__ == "__main__":
    print(f"  created {build()}")
    sys.exit(0)
