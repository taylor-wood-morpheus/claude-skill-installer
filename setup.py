#!/usr/bin/env python3
"""Create the Quick Actions and Claude Skills.app, or with --remove, delete them.

The one entry point for both the git install (install.sh / uninstall.sh) and
the Homebrew formula's `claude-skills-setup`.

    setup.py                     bundles call the run.sh beside this file
    setup.py --runner PATH       bundles call PATH (Homebrew: its opt/ path)
    setup.py --remove

Removal leaves installed skills, and any shortcut stored in pbs, alone.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_app  # noqa: E402
import make_quick_actions  # noqa: E402
from services import DEFAULT_RUNNER, SERVICES  # noqa: E402


def flush() -> None:
    subprocess.run(["/System/Library/CoreServices/pbs", "-flush"], check=False)


def install(runner: str) -> int:
    print(f"Generating Quick Actions (runner: {runner})…")
    if make_quick_actions.main(runner) != 0:
        return 1
    print("\nBuilding Claude Skills.app…")
    print(f"  created {make_app.build(runner)}")
    flush()
    print("\nRegistered with the Services system.")
    return 0


def remove() -> int:
    targets = [
        *(make_quick_actions.SERVICES_DIR / f"{s.bundle}.workflow" for s in SERVICES),
        make_app.APPS / f"{make_app.APP_NAME}.app",
    ]
    for path in targets:
        if path.exists():
            shutil.rmtree(path)
            print(f"  removed {path}")
        else:
            print(f"  absent  {path}")
    flush()
    print("Skills already in ~/.claude/skills were not touched.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remove", action="store_true", help="delete them instead")
    parser.add_argument("--runner", default=DEFAULT_RUNNER, help="run.sh the bundles call")
    args = parser.parse_args(argv)
    return remove() if args.remove else install(args.runner)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
