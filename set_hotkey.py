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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from services import HOTKEY_SERVICE, SERVICES  # noqa: E402

SERVICE_KEY = HOTKEY_SERVICE.pbs_key
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


def read_current(service=HOTKEY_SERVICE) -> str | None:
    return read_all().get(service.menu_title)


def read_all() -> dict[str, str | None]:
    """Current shortcut for every service, keyed by menu title."""
    status = _load().get("NSServicesStatus", {})
    return {
        s.menu_title: status.get(s.pbs_key, {}).get("key_equivalent")
        for s in SERVICES
    }


def summary() -> str:
    """The whole picture, for the dialog prompt and for --show."""
    width = max(len(s.menu_title) for s in SERVICES)
    bindings = read_all()
    lines = []
    for service in SERVICES:
        shown = describe(bindings[service.menu_title])
        note = "" if service.bindable else "   (this dialog)"
        lines.append(f"{service.menu_title.ljust(width)}   {shown}{note}")
    return "\n".join(lines)


def _load() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        plist = Path(tmp) / "pbs.plist"
        subprocess.run(["defaults", "export", "pbs", str(plist)], check=True)
        return plistlib.loads(plist.read_bytes()) if plist.exists() else {}


def write_key_equivalent(equivalent: str | None, service=HOTKEY_SERVICE) -> None:
    """Set (or with None, clear) the clipboard action's shortcut, then re-register.

    Goes through `defaults export`/`import` because the service key contains
    spaces and parentheses that `defaults write -dict-add` cannot parse, and
    because the round trip uses the preferences API rather than fighting
    cfprefsd's cache of the on-disk plist.
    """
    prefs = _load()
    status = prefs.setdefault("NSServicesStatus", {})
    entry = status.setdefault(service.pbs_key, {})
    if equivalent:
        entry["key_equivalent"] = equivalent
    else:
        entry.pop("key_equivalent", None)
    entry.setdefault("presentation_modes", {}).update(
        {"ContextMenu": 1, "ServicesMenu": 1}
    )
    # macOS hides any service that is not explicitly enabled, so every one of
    # them needs presentation_modes -- not just the ones with a shortcut.
    for service in SERVICES:
        entry = status.setdefault(service.pbs_key, {})
        entry.setdefault("presentation_modes", {}).update(
            {"ContextMenu": 1, "ServicesMenu": 1, "FinderPreview": 1}
        )

    live = {s.pbs_key for s in SERVICES}
    for stale in [
        k for k in status
        if "Claude Skills" in k and k not in live
    ]:
        del status[stale]

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
DONE = "Done"


def choose_service():
    """Show every binding and return the service to change, or None to close.

    This dialog doubles as the viewer: reading it is the point, changing
    something is optional.
    """
    bindings = read_all()
    labels = {}
    for service in SERVICES:
        if not service.bindable:
            continue
        labels[f"{service.menu_title}   —   {describe(bindings[service.menu_title])}"] = service
    labels[DONE] = None

    listing = ", ".join(_q(k) for k in labels)
    chosen = _osascript(
        f"set chosen to choose from list {{{listing}}} "
        f'with title "Claude Skills shortcuts" '
        f'with prompt "Current shortcuts:\n\n{summary()}\n\n'
        f'Pick one to change it, or Done to close." '
        f'default items {{{_q(DONE)}}} '
        f'OK button name "Change" cancel button name "Close"\n'
        'if chosen is false then return ""\n'
        "return item 1 of chosen"
    )
    if not chosen or chosen == DONE:
        return None
    if chosen not in labels:
        raise HotkeyError(f"Unexpected selection {chosen!r}.")
    return labels[chosen]


def pick(current: str | None, service) -> str | None:
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
        f'with title "Claude Skills shortcuts" '
        f'with prompt "Shortcut for “{service.menu_title}”.'
        f'\n\nCurrently: {describe(current)}" '
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
        f'\n\nFor example:  ctrl-opt-cmd-K    or    cmd-shift-L" '
        f'with title "Claude Skills shortcuts" '
        f"default answer {_q(describe(current) if current else 'ctrl-opt-cmd-K')} "
        f'buttons {{"Cancel", "Set"}} default button "Set")'
    )
    return parse(typed)


def main(argv: list[str]) -> int:
    try:
        if "--show" in argv:
            print(summary())
            return 0

        if "--set" in argv:
            value = argv[argv.index("--set") + 1]
            chosen = None if value.lower() in ("none", "off", "") else parse(value)
            write_key_equivalent(chosen)
            print(f"{HOTKEY_SERVICE.menu_title}: {describe(chosen)}")
            return 0

        # Interactive: the list of bindings is the view; changing is optional.
        while (service := choose_service()) is not None:
            chosen = pick(read_current(service), service)
            write_key_equivalent(chosen, service)
            notify(
                f"{service.menu_title}: {describe(chosen)}"
                if chosen
                else f"{service.menu_title}: shortcut removed"
            )
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
