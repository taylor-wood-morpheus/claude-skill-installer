"""The one place the Quick Actions are described.

The generator writes a .workflow bundle for each and enables each in pbs; setup
removes each. Keeping one list means a service cannot be written but never
enabled, which leaves it invisible.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# What the bundles call when setup.py is not told otherwise: the run.sh in this
# directory. Fine for a checkout install, whose directory is real. Homebrew passes
# its stable opt/ path explicitly, because this file cannot recover it --
# Python resolves symlinks when it builds sys.path[0], so __file__ here is
# already the versioned Cellar path that the next `brew upgrade` deletes.
DEFAULT_RUNNER = str(Path(__file__).resolve().parent / "run.sh")


@dataclass(frozen=True)
class Service:
    bundle: str          # .workflow directory name
    menu_title: str      # what appears in the Services menu
    trigger: str         # run.sh argument
    input_type: str      # com.apple.Automator.* service input identifier
    send_key: str        # Info.plist key: NSSendFileTypes or NSSendTypes
    send_value: tuple[str, ...]
    stdin: bool          # True = pipe input to stdin, False = pass as "$@"

    def command(self, runner: str) -> str:
        args = ' "$@"' if not self.stdin and self.input_type.endswith("Object") else ""
        return f'exec "{runner}" {self.trigger}{args}'

    @property
    def pbs_key(self) -> str:
        # pbs keys services by menu title, so every title must be distinct --
        # two bundles sharing one title collapse into a single entry and only
        # one of them can be enabled.
        return f"(null) - {self.menu_title} - runWorkflowAsService"


SERVICES = (
    Service(
        bundle="Add Selected Text to Claude Skills",
        menu_title="Add Selected Text to Claude Skills",
        trigger="text",
        input_type="com.apple.Automator.text",
        send_key="NSSendTypes",
        send_value=("NSStringPboardType",),
        stdin=True,
    ),
)

# Bundles and apps that earlier versions installed, removed whenever setup runs.
RETIRED_BUNDLES = (
    "Add to Claude Skills",
    "Add Clipboard to Claude Skills",
    "Set Claude Skills Hotkey",
)
RETIRED_APPS = ("Claude Skills",)

assert len({s.menu_title for s in SERVICES}) == len(SERVICES), "menu titles must be unique"
