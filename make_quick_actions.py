#!/usr/bin/env python3
"""Generate the Quick Action bundles in ~/Library/Services and enable them.

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
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from services import DEFAULT_RUNNER, SERVICES  # noqa: E402

SERVICES_DIR = Path.home() / "Library" / "Services"
TEMPLATE = Path(__file__).resolve().parent / "action_template.b64"

def build(template: dict, runner: str) -> list[Path]:
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)
    built = []
    for service in SERVICES:
        doc = copy.deepcopy(template)
        action = doc["actions"][0]["action"]
        action["ActionParameters"].update(
            {
                "COMMAND_STRING": service.command(runner),
                "shell": "/bin/zsh",
                "inputMethod": 0 if service.stdin else 1,
                "CheckedForUserDefaultShell": True,
            }
        )
        for key in ("UUID", "InputUUID", "OutputUUID"):
            action[key] = str(uuid.uuid4()).upper()

        doc["workflowMetaData"].update(
            {
                "inputTypeIdentifier": service.input_type,
                "serviceInputTypeIdentifier": service.input_type,
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
                    "NSMenuItem": {"default": service.menu_title},
                    "NSMessage": "runWorkflowAsService",
                    service.send_key: list(service.send_value),
                }
            ]
        }

        bundle = SERVICES_DIR / f"{service.bundle}.workflow"
        shutil.rmtree(bundle, ignore_errors=True)
        (bundle / "Contents").mkdir(parents=True)
        (bundle / "Contents" / "document.wflow").write_bytes(plistlib.dumps(doc))
        (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
        print(f"  created {bundle.name}")
        built.append(bundle)
    return built


def enable() -> None:
    """Enable every service in pbs, and drop entries for ones that no longer exist.

    macOS hides any service without an explicit presentation_modes entry, so a
    bundle that is written but not enabled never appears. Goes through `defaults
    export`/`import` because the service keys contain spaces and parentheses that
    `defaults write -dict-add` cannot parse. A shortcut the user has set on a live
    service is kept; the retired ones' (e.g. the old ⌃⌥⌘S) go with them.
    """
    with tempfile.TemporaryDirectory() as tmp:
        plist = Path(tmp) / "pbs.plist"
        subprocess.run(["defaults", "export", "pbs", str(plist)], check=True)
        prefs = plistlib.loads(plist.read_bytes()) if plist.exists() else {}
        status = prefs.setdefault("NSServicesStatus", {})
        for service in SERVICES:
            entry = status.setdefault(service.pbs_key, {})
            entry.setdefault("presentation_modes", {}).update(
                {"ContextMenu": 1, "ServicesMenu": 1, "FinderPreview": 1}
            )
        live = {s.pbs_key for s in SERVICES}
        for stale in [k for k in status if "Claude Skills" in k and k not in live]:
            del status[stale]
            print(f"  dropped pbs entry {stale}")
        plist.write_bytes(plistlib.dumps(prefs))
        subprocess.run(["defaults", "import", "pbs", str(plist)], check=True)
    print(f"  enabled {len(SERVICES)} service(s)")


def main(runner: str = DEFAULT_RUNNER) -> int:
    if not TEMPLATE.exists():
        print(f"missing {TEMPLATE}", file=sys.stderr)
        return 1
    template = plistlib.loads(base64.b64decode(TEMPLATE.read_text()))
    build(template, runner)
    enable()
    return 0


if __name__ == "__main__":
    sys.exit(main())
