#!/usr/bin/env python3
"""Generate the three Quick Action bundles in ~/Library/Services.

The Run Shell Script action plist carries a dozen undocumented AM* keys, so the
known-good structure is shipped alongside this script in action_template.b64
rather than hand-authored here or scavenged from whatever workflows happen to
exist on the target machine.

Generating the bundles locally also sidesteps Gatekeeper: a .workflow that
arrives inside a download is quarantined and refuses to run, one written by this
script is not.
"""

from __future__ import annotations

import base64
import copy
import plistlib
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import set_hotkey  # noqa: E402  (same directory, installed alongside)

SERVICES = Path.home() / "Library" / "Services"
RUNNER = "$HOME/.claude/tools/skill-installer/run.sh"
TEMPLATE = Path(__file__).resolve().parent / "action_template.b64"

# bundle name, menu title, shell command, service input UTI,
# (Info.plist send-types key, value), inputMethod (0 = stdin, 1 = "$@")
SPECS = [
    (
        "Add to Claude Skills",
        "Add to Claude Skills",
        f'exec "{RUNNER}" files "$@"',
        "com.apple.Automator.fileSystemObject",
        # Matching is by UTI conformance, so these three cover folders, every
        # archive flavour, and anything text-like. Services cannot match on a
        # filename, so "only SKILL.md" is not expressible.
        ("NSSendFileTypes", ["public.folder", "public.archive", "public.plain-text"]),
        1,
    ),
    (
        "Add Selected Text to Claude Skills",
        "Add to Claude Skills",
        f'exec "{RUNNER}" text',
        "com.apple.Automator.text",
        ("NSSendTypes", ["NSStringPboardType"]),
        0,
    ),
    (
        "Add Clipboard to Claude Skills",
        "Add Clipboard to Claude Skills",
        f'exec "{RUNNER}" clipboard',
        "com.apple.Automator.nothing",
        ("NSSendTypes", []),
        0,
    ),
    (
        "Set Claude Skills Hotkey",
        "Set Claude Skills Hotkey",
        f'exec "{RUNNER}" hotkey',
        "com.apple.Automator.nothing",
        ("NSSendTypes", []),
        0,
    ),
]


def build(template: dict) -> list[Path]:
    SERVICES.mkdir(parents=True, exist_ok=True)
    built = []
    for name, title, command, input_type, (send_key, send_value), method in SPECS:
        doc = copy.deepcopy(template)
        action = doc["actions"][0]["action"]
        action["ActionParameters"].update(
            {
                "COMMAND_STRING": command,
                "shell": "/bin/zsh",
                "inputMethod": method,
                "CheckedForUserDefaultShell": True,
            }
        )
        for key in ("UUID", "InputUUID", "OutputUUID"):
            action[key] = str(uuid.uuid4()).upper()

        doc["workflowMetaData"].update(
            {
                "inputTypeIdentifier": input_type,
                "serviceInputTypeIdentifier": input_type,
                "outputTypeIdentifier": "com.apple.Automator.nothing",
                "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
                "useAutomaticInputType": False,
                "processesInput": False,
                "serviceProcessesInput": False,
            }
        )
        for stale in ("systemImageName", "backgroundColorName"):
            doc["workflowMetaData"].pop(stale, None)

        info = {
            "NSServices": [
                {
                    "NSMenuItem": {"default": title},
                    "NSMessage": "runWorkflowAsService",
                    send_key: send_value,
                }
            ]
        }

        bundle = SERVICES / f"{name}.workflow"
        shutil.rmtree(bundle, ignore_errors=True)
        (bundle / "Contents").mkdir(parents=True)
        (bundle / "Contents" / "document.wflow").write_bytes(plistlib.dumps(doc))
        (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
        print(f"  created {bundle.name}")
        built.append(bundle)
    return built


def main() -> int:
    if not TEMPLATE.exists():
        print(f"missing {TEMPLATE}", file=sys.stderr)
        return 1
    template = plistlib.loads(base64.b64decode(TEMPLATE.read_text()))
    build(template)
    set_hotkey.write_key_equivalent(set_hotkey.read_current() or set_hotkey.DEFAULT)
    print(f"  hotkey: {set_hotkey.describe(set_hotkey.read_current())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
