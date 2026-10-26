#!/usr/bin/env python3
"""Install a Claude Code skill from selected text.

Invoked by the "Add Selected Text to Claude Skills" Quick Action, with the
selection on stdin. There is deliberately no human-facing command line: all
feedback goes through native dialogs and notifications, and all diagnostics go
to ~/Library/Logs/claude-skill-installer/install.log.

The text is the skill, verbatim. It must open with frontmatter naming it --
nothing is fetched and nothing is generated.

    install.py text            skill markdown on stdin
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

SKILLS_DIR = Path(
    os.environ.get("CLAUDE_SKILLS_DIR", Path.home() / ".claude" / "skills")
).expanduser()
# Set to a button label to auto-answer every dialog; used by the test harness and
# by any non-GUI invocation, where a modal dialog would simply hang.
AUTO_ANSWER = os.environ.get("SKILL_INSTALLER_AUTO_ANSWER")
# run.sh exports this; the default covers running install.py directly.
LOG_PATH = Path(
    os.environ.get(
        "SKILL_INSTALLER_LOG",
        Path.home() / "Library" / "Logs" / "claude-skill-installer" / "install.log",
    )
)
# Triggers that v0.1 bundles still call until claude-skills-setup is re-run.
RETIRED_TRIGGERS = {"files", "clipboard", "hotkey"}

log = logging.getLogger("skill-installer")


class SkillError(Exception):
    """A failure with a message fit to show the user in a dialog."""


@dataclass(frozen=True)
class Candidate:
    """One skill from the selection: its SKILL.md text and the name it installs as."""

    name: str
    description: str
    text: str


# --------------------------------------------------------------------------- #
# macOS front end
# --------------------------------------------------------------------------- #


def _osascript(script: str) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=False
    )
    log.debug(
        "osascript rc=%s stdout=%r stderr=%r", proc.returncode, proc.stdout, proc.stderr
    )
    if proc.returncode != 0:
        # User cancelled a dialog, or the dialog could not be shown at all.
        raise SkillError("cancelled")
    return proc.stdout.strip()


def _q(text: str) -> str:
    """Quote a Python string for embedding in AppleScript source."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, message: str) -> None:
    log.info("notify title=%r message=%r", title, message)
    if AUTO_ANSWER:
        print(f"[notify] {title}: {message}", file=sys.stderr)
        return
    subprocess.run(
        ["osascript", "-e", f"display notification {_q(message)} with title {_q(title)}"],
        capture_output=True,
        check=False,
    )


def alert(message: str) -> None:
    log.warning("alert message=%r", message)
    if AUTO_ANSWER:
        print(f"[alert] {message}", file=sys.stderr)
        return
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display alert "Add to Claude Skills" message {_q(message)} as warning',
        ],
        capture_output=True,
        check=False,
    )


def ask(message: str, buttons: Sequence[str], default: str) -> str:
    """Show a choice dialog. Raises SkillError('cancelled') if dismissed."""
    if AUTO_ANSWER:
        log.info("auto-answering dialog with %r", AUTO_ANSWER)
        print(f"[ask] {message}\n[auto] {AUTO_ANSWER}", file=sys.stderr)
        return AUTO_ANSWER
    button_list = ", ".join(_q(b) for b in buttons)
    script = (
        f"button returned of (display dialog {_q(message)} "
        f'with title "Add to Claude Skills" '
        f"buttons {{{button_list}}} default button {_q(default)})"
    )
    choice = _osascript(script)
    log.info("ask message=%r choice=%r", message.splitlines()[0], choice)
    return choice


def choose(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Let the user pick which skills to take when a source holds several.
    A single skill installs without asking; there is nothing to choose."""
    if len(candidates) == 1:
        return list(candidates)
    if AUTO_ANSWER:
        log.info("auto-selecting all %d candidates", len(candidates))
        return list(candidates)
    labels = {f"{c.name} — {c.description[:70]}": c for c in candidates}
    listing = ", ".join(_q(label) for label in labels)
    script = (
        f"set chosen to choose from list {{{listing}}} "
        f'with title "Add to Claude Skills" '
        f'with prompt "The selection has {len(candidates)} skills. '
        f'Which do you want to install?" '
        f"with multiple selections allowed\n"
        'if chosen is false then return ""\n'
        'set out to ""\n'
        'repeat with item_ in chosen\n'
        '    set out to out & item_ & linefeed\n'
        "end repeat\n"
        "return out"
    )
    selected = [line for line in _osascript(script).splitlines() if line.strip()]
    log.info("user selected %d of %d candidates", len(selected), len(candidates))
    if not selected:
        raise SkillError("cancelled")
    return [labels[line] for line in selected if line in labels]


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #

FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.S)
FENCE = re.compile(r"\A\s*```[a-zA-Z0-9_-]*\r?\n(.*?)\r?\n```\s*\Z", re.S)


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Parse the leading YAML frontmatter block. Flat scalars only, which is all
    a skill header uses; returns None when there is no well-formed block."""
    match = FRONTMATTER.match(text)
    if not match:
        return None
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] in " \t":  # continuation or nested value: ignore, not needed
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields[key.strip()] = value.strip().strip("'\"")
    return fields


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:48] or "unnamed-skill"


def _looks_like_frontmatter(text: str, start: int) -> bool:
    """True if a `---` line at `start` opens a skill frontmatter block."""
    window = text[start : start + 600]
    body = window.split("\n", 1)[-1]
    closing = re.search(r"(?m)^---[ \t]*$", body)
    return closing is not None and "name:" in body[: closing.start()]


def split_documents(text: str) -> list[str]:
    """Split a paste that contains several SKILL.md files into one string each."""
    starts = [
        m.start()
        for m in re.finditer(r"(?m)^---[ \t]*$", text)
        if _looks_like_frontmatter(text, m.start())
    ]
    if len(starts) <= 1:
        return [text]
    bounds = starts + [len(text)]
    docs = [text[a:b].strip() for a, b in zip(bounds, bounds[1:])]
    log.info("split paste into %d documents", len(docs))
    return docs


MISSING_FRONTMATTER = """\
A skill must start with frontmatter giving its name and description:

---
name: my-skill
description: What it does and when Claude should use it
---

Select the whole skill, including that header."""


def candidate(text: str) -> Candidate:
    """Read a skill's name and description from its own frontmatter, or refuse."""
    fields = parse_frontmatter(text) or {}
    missing = [key for key in ("name", "description") if not fields.get(key)]
    if missing:
        log.warning("refusing: missing=%s fields=%s head=%r", missing, fields, text[:120])
        what = "no frontmatter" if not fields else f"no {' or '.join(missing)}"
        raise SkillError(f"This text has {what}.\n\n{MISSING_FRONTMATTER}")
    return Candidate(
        name=slugify(fields["name"]),
        description=fields["description"],
        text=text.rstrip() + "\n",
    )


def candidates_from_text(text: str) -> list[Candidate]:
    stripped = text.strip()
    if not stripped:
        raise SkillError("There is nothing to install — the selection was empty.")
    if fenced := FENCE.match(stripped):
        log.debug("stripping surrounding code fence")
        stripped = fenced.group(1)
    return [candidate(doc) for doc in split_documents(stripped)]


# --------------------------------------------------------------------------- #
# Install
# --------------------------------------------------------------------------- #


def _unique_name(name: str) -> str:
    for suffix in range(2, 100):
        candidate = f"{name}-{suffix}"
        if not (SKILLS_DIR / candidate).exists():
            return candidate
    raise SkillError(f"Could not find a free name based on {name!r}.")


def install(candidate: Candidate) -> Path:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    dest = SKILLS_DIR / candidate.name
    if dest.exists():
        log.info("collision name=%s existing=%s", candidate.name, dest)
        choice = ask(
            f"A skill called “{candidate.name}” is already installed.\n\n"
            f"Existing: {sum(1 for _ in dest.rglob('*') if _.is_file())} file(s)\n"
            "Incoming: its SKILL.md, from the selected text",
            ["Cancel", "Keep Both", "Overwrite"],
            "Keep Both",
        )
        if choice == "Overwrite":
            shutil.rmtree(dest)
        elif choice == "Keep Both":
            dest = SKILLS_DIR / _unique_name(candidate.name)
        else:
            raise SkillError("cancelled")
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text(candidate.text, encoding="utf-8")
    log.info("installed name=%s dest=%s chars=%d", candidate.name, dest, len(candidate.text))
    return dest


def run(argv: Sequence[str]) -> None:
    trigger, *rest = argv
    log.info("trigger=%s args=%s", trigger, rest)
    match trigger:
        case "text":
            candidates = candidates_from_text(sys.stdin.read())
        case retired if retired in RETIRED_TRIGGERS:
            raise SkillError(
                "This Quick Action was removed in v0.2: only selected text is "
                "supported now.\n\nRun claude-skills-setup in a terminal to tidy "
                "up the old menu items."
            )
        case other:
            raise SkillError(f"Unknown trigger {other!r}.")

    log.info("discovered candidates=%s", [c.name for c in candidates])
    installed = [install(c) for c in choose(candidates)]

    if len(installed) == 1:
        notify("Skill installed", f"{installed[0].name} → ~/.claude/skills")
    else:
        notify(
            f"{len(installed)} skills installed",
            ", ".join(p.name for p in installed),
        )


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(funcName)s: %(message)s")
    )
    logging.basicConfig(level=logging.DEBUG, handlers=[handler])
    log.info("=== start argv=%s ===", sys.argv[1:])

    if len(sys.argv) < 2:
        alert("No input given.")
        return 2
    try:
        run(sys.argv[1:])
    except SkillError as exc:
        if str(exc) == "cancelled":
            log.info("cancelled by user")
            return 1
        alert(str(exc))
        return 1
    except Exception:
        log.exception("unhandled failure")
        alert(f"Something went wrong. See:\n{LOG_PATH}")
        return 1
    log.info("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
