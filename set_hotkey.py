#!/usr/bin/env python3
"""Change the keyboard shortcut for "Add Clipboard to Claude Skills".

Reachable as its own Quick Action so the hotkey can be changed without a trip
through System Settings. Also owns the pbs write used at install time, so the
encoding lives in exactly one place.

    set_hotkey.py                    interactive picker
    set_hotkey.py --set ctrl-opt-cmd-K
    set_hotkey.py --set none         remove the shortcut
    set_hotkey.py --show             print the current binding
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

SERVICE_KEY = "(null) - Add Clipboard to Claude Skills - runWorkflowAsService"
DEFAULT = "^~@s"

# pbs encodes modifiers as sigils. Order matters only for display consistency.
MODIFIERS = (
    ("^", "control", "⌃", ("ctrl", "control", "⌃")),
    ("~", "option", "⌥", ("opt", "option", "alt", "⌥")),
    ("$", "shift", "⇧", ("shift", "⇧")),
    ("@", "command", "⌘", ("cmd", "command", "⌘")),
)

PRESETS = ["^~@s", "^~@k", "^~@v", "~@s", "$@l"]


class HotkeyError(Exception):
    """A message fit to show the user."""


# --------------------------------------------------------------------------- #
# Encoding
# --------------------------------------------------------------------------- #


def describe(equivalent: str | None) -> str:
    """Render a pbs key equivalent as symbols, e.g. '^~@s' -> '⌃⌥⌘S'."""
    if not equivalent:
        return "(none)"
    sigils = {sigil for sigil, *_ in MODIFIERS if sigil in equivalent}
    symbols = "".join(sym for sigil, _, sym, _ in MODIFIERS if sigil in sigils)
    key = equivalent.lstrip("".join(s for s, *_ in MODIFIERS))
    return f"{symbols}{key.upper()}"


def parse(text: str) -> str:
    """Parse 'ctrl-opt-cmd-K', '⌃⌥⌘K' or '^~@k' into a pbs key equivalent."""
    raw = text.strip()
    if not raw:
        raise HotkeyError("No shortcut given.")

    sigils: list[str] = []
    remainder = raw

    # Symbol and sigil forms: strip recognised prefixes character by character.
    changed = True
    while changed:
        changed = False
        for sigil, _, symbol, _ in MODIFIERS:
            for token in (sigil, symbol):
                if remainder.startswith(token):
                    if sigil not in sigils:
                        sigils.append(sigil)
                    remainder = remainder[len(token) :]
                    changed = True

    # Word form: cmd-opt-K, ctrl+option+k, "cmd opt k".
    if remainder and not remainder.isalnum():
        parts = [p for p in remainder.replace("+", "-").replace(" ", "-").split("-") if p]
    else:
        parts = [remainder] if remainder else []
    if len(parts) > 1:
        *words, remainder = parts
        for word in words:
            match = next(
                (s for s, _, _, aliases in MODIFIERS if word.lower() in aliases), None
            )
            if match is None:
                raise HotkeyError(f"Unrecognised modifier {word!r}.")
            if match not in sigils:
                sigils.append(match)

    key = remainder.strip()
    if len(key) != 1 or not key.isalnum():
        raise HotkeyError(
            f"Expected a single letter or digit, got {key!r}.\n\n"
            "Examples:  ctrl-opt-cmd-K   ⌃⌥⌘K   cmd-shift-L"
        )
    if not sigils:
        raise HotkeyError(
            "A shortcut with no modifier key would fire while you type.\n\n"
            "Include at least one of control, option, shift or command."
        )

    ordered = "".join(s for s, *_ in MODIFIERS if s in sigils)
    return f"{ordered}{key.lower()}"


# --------------------------------------------------------------------------- #
# pbs
# --------------------------------------------------------------------------- #


def read_current() -> str | None:
    prefs = _load()
    entry = prefs.get("NSServicesStatus", {}).get(SERVICE_KEY, {})
    return entry.get("key_equivalent")


def _load() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        plist = Path(tmp) / "pbs.plist"
        subprocess.run(["defaults", "export", "pbs", str(plist)], check=True)
        return plistlib.loads(plist.read_bytes()) if plist.exists() else {}


def write_key_equivalent(equivalent: str | None) -> None:
    """Set (or with None, clear) the clipboard action's shortcut, then re-register.

    Goes through `defaults export`/`import` because the service key contains
    spaces and parentheses that `defaults write -dict-add` cannot parse, and
    because the round trip uses the preferences API rather than fighting
    cfprefsd's cache of the on-disk plist.
    """
    prefs = _load()
    status = prefs.setdefault("NSServicesStatus", {})
    entry = status.setdefault(SERVICE_KEY, {})
    if equivalent:
        entry["key_equivalent"] = equivalent
    else:
        entry.pop("key_equivalent", None)
    entry.setdefault("presentation_modes", {}).update(
        {"ContextMenu": 1, "ServicesMenu": 1}
    )
    # Keep the two context-menu services visible wherever they can appear.
    for title in ("Add to Claude Skills", "Add Clipboard to Claude Skills"):
        other = status.setdefault(f"(null) - {title} - runWorkflowAsService", {})
        other.setdefault("presentation_modes", {}).update(
            {"ContextMenu": 1, "ServicesMenu": 1, "FinderPreview": 1}
        )

    with tempfile.TemporaryDirectory() as tmp:
        plist = Path(tmp) / "pbs.plist"
        plist.write_bytes(plistlib.dumps(prefs))
        subprocess.run(["defaults", "import", "pbs", str(plist)], check=True)
    subprocess.run(
        ["/System/Library/CoreServices/pbs", "-flush"], capture_output=True, check=False
    )


# --------------------------------------------------------------------------- #
# Dialogs
# --------------------------------------------------------------------------- #


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript(script: str) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(0)  # dismissed
    return proc.stdout.strip()


def notify(message: str) -> None:
    subprocess.run(
        ["osascript", "-e", f'display notification {_q(message)} with title "Claude Skills hotkey"'],
        capture_output=True,
        check=False,
    )


def alert(message: str) -> None:
    subprocess.run(
        ["osascript", "-e", f'display alert "Claude Skills hotkey" message {_q(message)} as warning'],
        capture_output=True,
        check=False,
    )


CUSTOM = "Type my own…"
REMOVE = "Remove the shortcut"


def pick(current: str | None) -> str | None:
    labels: dict[str, str | None] = {}
    for preset in PRESETS:
        label = describe(preset) + ("   (current)" if preset == current else "")
        labels[label] = preset
    labels[CUSTOM] = CUSTOM
    labels[REMOVE] = None

    listing = ", ".join(_q(k) for k in labels)
    default = next((_q(k) for k, v in labels.items() if v == current), _q(CUSTOM))
    chosen = _osascript(
        f"set chosen to choose from list {{{listing}}} "
        f'with title "Claude Skills hotkey" '
        f'with prompt "Shortcut for pasting a skill from the clipboard.'
        f'\\n\\nCurrently: {describe(current)}" '
        f"default items {{{default}}}\n"
        'if chosen is false then return ""\n'
        "return item 1 of chosen"
    )
    if not chosen:
        raise SystemExit(0)
    if chosen not in labels:
        raise HotkeyError(f"Unexpected selection {chosen!r}.")
    if labels[chosen] != CUSTOM:
        return labels[chosen]

    typed = _osascript(
        f"text returned of (display dialog "
        f'"Type the shortcut — modifiers then one letter or digit.'
        f'\\n\\nFor example:  ctrl-opt-cmd-K    or    cmd-shift-L" '
        f'with title "Claude Skills hotkey" '
        f"default answer {_q(describe(current) if current else 'ctrl-opt-cmd-K')} "
        f'buttons {{"Cancel", "Set"}} default button "Set")'
    )
    return parse(typed)


def main(argv: list[str]) -> int:
    try:
        if "--show" in argv:
            print(describe(read_current()))
            return 0

        if "--set" in argv:
            value = argv[argv.index("--set") + 1]
            chosen = None if value.lower() in ("none", "off", "") else parse(value)
        else:
            chosen = pick(read_current())

        write_key_equivalent(chosen)
        message = (
            f"Shortcut is now {describe(chosen)}"
            if chosen
            else "Shortcut removed. The action stays in the Services menu."
        )
        if "--set" in argv:
            print(message)
        else:
            notify(message)
        return 0
    except HotkeyError as exc:
        if "--set" in argv:
            print(f"error: {exc}", file=sys.stderr)
        else:
            alert(str(exc))
        return 1
    except IndexError:
        print("error: --set needs a value", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
