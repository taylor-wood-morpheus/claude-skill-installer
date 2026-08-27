"""The one place the four Quick Actions are described.

Both the bundle generator and the hotkey editor need this list -- the generator
to write the .workflow bundles, the editor to enable every service in pbs. When
it was duplicated, a service added to one list stayed invisible because the
other never enabled it.
"""

from __future__ import annotations

from dataclasses import dataclass

RUNNER = "$HOME/.claude/tools/skill-installer/run.sh"


@dataclass(frozen=True)
class Service:
    bundle: str          # .workflow directory name
    menu_title: str      # what appears in the Services menu
    trigger: str         # run.sh argument
    input_type: str      # com.apple.Automator.* service input identifier
    send_key: str        # Info.plist key: NSSendFileTypes or NSSendTypes
    send_value: tuple[str, ...]
    stdin: bool          # True = pipe input to stdin, False = pass as "$@"

    @property
    def command(self) -> str:
        args = ' "$@"' if not self.stdin and self.input_type.endswith("Object") else ""
        return f'exec "{RUNNER}" {self.trigger}{args}'

    @property
    def pbs_key(self) -> str:
        # pbs keys services by menu title, so every title must be distinct --
        # two bundles sharing one title collapse into a single entry and only
        # one of them can be enabled.
        return f"(null) - {self.menu_title} - runWorkflowAsService"


SERVICES = (
    Service(
        bundle="Add to Claude Skills",
        menu_title="Add to Claude Skills",
        trigger="files",
        input_type="com.apple.Automator.fileSystemObject",
        send_key="NSSendFileTypes",
        # Matching is by UTI conformance, so these three cover folders, every
        # archive flavour, and anything text-like. Services cannot match on a
        # filename, so "only SKILL.md" is not expressible.
        send_value=("public.folder", "public.archive", "public.plain-text"),
        stdin=False,
    ),
    Service(
        bundle="Add Selected Text to Claude Skills",
        menu_title="Add Selected Text to Claude Skills",
        trigger="text",
        input_type="com.apple.Automator.text",
        send_key="NSSendTypes",
        send_value=("NSStringPboardType",),
        stdin=True,
    ),
    Service(
        bundle="Add Clipboard to Claude Skills",
        menu_title="Add Clipboard to Claude Skills",
        trigger="clipboard",
        input_type="com.apple.Automator.nothing",
        send_key="NSSendTypes",
        send_value=(),
        stdin=True,
    ),
    Service(
        bundle="Set Claude Skills Hotkey",
        menu_title="Set Claude Skills Hotkey",
        trigger="hotkey",
        input_type="com.apple.Automator.nothing",
        send_key="NSSendTypes",
        send_value=(),
        stdin=True,
    ),
)

# The service the keyboard shortcut is attached to.
HOTKEY_SERVICE = next(s for s in SERVICES if s.trigger == "clipboard")

assert len({s.menu_title for s in SERVICES}) == len(SERVICES), "menu titles must be unique"
