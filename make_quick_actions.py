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


def bind_hotkey(combination: str = "^~@s") -> None:
    """Give the clipboard action a global key equivalent.

    This lives in the `pbs` domain under a key containing spaces and parens that
    `defaults write -dict-add` cannot parse, hence the export/modify/import round
    trip -- which also goes through the preferences API instead of fighting
    cfprefsd's cache.
    """
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        plist = Path(tmp) / "pbs.plist"
        subprocess.run(["defaults", "export", "pbs", str(plist)], check=True)
        prefs = plistlib.loads(plist.read_bytes()) if plist.exists() else {}
        status = prefs.setdefault("NSServicesStatus", {})
        status["(null) - Add Clipboard to Claude Skills - runWorkflowAsService"] = {
            "key_equivalent": combination,
            "presentation_modes": {"ContextMenu": 1, "ServicesMenu": 1},
        }
        for title in ("Add to Claude Skills", "Add Clipboard to Claude Skills"):
            entry = status.setdefault(f"(null) - {title} - runWorkflowAsService", {})
            modes = entry.setdefault("presentation_modes", {})
            modes.update({"ContextMenu": 1, "ServicesMenu": 1, "FinderPreview": 1})
        plist.write_bytes(plistlib.dumps(prefs))
        subprocess.run(["defaults", "import", "pbs", str(plist)], check=True)
    print(f"  bound hotkey {combination} (control-option-command-S)")


def main() -> int:
    if not TEMPLATE.exists():
        print(f"missing {TEMPLATE}", file=sys.stderr)
        return 1
    template = plistlib.loads(base64.b64decode(TEMPLATE.read_text()))
    build(template)
    bind_hotkey()
    return 0


if __name__ == "__main__":
    sys.exit(main())
