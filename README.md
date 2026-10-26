# Add Selected Text to Claude Skills

Select a Claude Code skill's text anywhere — a Slack message, a doc, a web page —
right-click, and install it into `~/.claude/skills`. macOS only.

## Install

With Homebrew (MorpheusWealth tap):

```sh
brew tap morpheuswealth/tools git@github.com:MorpheusWealth/homebrew-tools.git
brew install morpheuswealth/tools/claude-skill-installer
claude-skills-setup
```

`claude-skills-setup` writes the Quick Action into `~/Library/Services` — a
formula may not touch your home directory itself. To uninstall, remove it first,
because `brew uninstall` cannot:

```sh
claude-skills-setup --remove
brew uninstall claude-skill-installer
```

Or from a checkout:

```sh
git clone https://github.com/taylor-wood-morpheus/claude-skill-installer.git
cd claude-skill-installer && ./install.sh
```

`./uninstall.sh` removes it. Skills already installed are never touched.

Requires macOS and Python 3.12+ (the formula brings its own).

## Use

Select the skill's text → right-click → **Services → Add Selected Text to Claude
Skills**.

The selection is the skill, verbatim. It must start with frontmatter:

```markdown
---
name: my-skill
description: What it does and when Claude should use it
---

…the skill's instructions…
```

Text without a `name` and `description` is refused with a dialog saying what is
missing — nothing is generated for it and nothing is fetched. A selection that
is just a link to a skill is refused the same way: select the skill itself.

- **A surrounding code fence** (` ```markdown … ``` `) is stripped.
- **Several skills in one selection** — each starting with its own frontmatter —
  raise a checklist so you choose. A single skill installs without asking.
- **An invalid name** is made valid: skill names are lowercase letters, digits
  and hyphens, at most 64 characters, and must match the skill's folder
  ([Agent Skills spec](https://agentskills.io/specification)). So `name: Alpha
  Skill` installs as `alpha-skill/` with its `name:` line rewritten to match —
  the only change ever made to the text. The notification says so.
- **Name collisions** offer Overwrite / Cancel.

To bind a keyboard shortcut to it: System Settings → Keyboard → Keyboard
Shortcuts → Services → Text → *Add Selected Text to Claude Skills*.

## Upgrading from v0.1

v0.1 also had a Finder action, a clipboard hotkey (⌃⌥⌘S) that fetched GitHub
URLs, `Claude Skills.app`, and wrote missing frontmatter with `claude -p`. All
of that is gone. After `brew upgrade`, run `claude-skills-setup` once: it
removes the old menu items, the app and the old hotkey. Until then, the old
items show a dialog saying so.

## How it works

One Automator `.workflow` bundle in `~/Library/Services` whose Run Shell Script
action pipes the selection to the `run.sh` beside the `setup.py` that generated
it — `~/.claude/tools/skill-installer/` for a checkout install, the formula's
`opt/…/libexec/` under Homebrew.

`services.py` describes the bundle once; the generator writes it and enables it
in `pbs`. Enabling is not optional: macOS hides any service without an explicit
`presentation_modes` entry. Services run with a minimal environment via
launchd, so `run.sh` resolves an interpreter and fixes `PATH` before handing off.

`make_quick_actions.py` generates the bundle locally from an action plist
embedded as `action_template.b64`. Both details matter: the plist carries a
dozen undocumented `AM*` keys that should not be hand-authored, and a
`.workflow` that arrives inside a download is Gatekeeper-quarantined and refuses
to run — one written by a script is not.

## Diagnostics

`~/Library/Logs/claude-skill-installer/install.log` (rotating, 1 MB × 3) records
every run, the frontmatter found or missing, dialog answers and install paths.
Services swallow stdout and stderr, so this is the only place failures are
visible.

## Testing

```sh
CLAUDE_SKILLS_DIR=/tmp/x SKILL_INSTALLER_AUTO_ANSWER=Overwrite ./run.sh text < SKILL.md
```

`CLAUDE_SKILLS_DIR` redirects the install; `SKILL_INSTALLER_AUTO_ANSWER`
auto-answers dialogs with the given button label and prints them to stderr.
Note that `automator` launches services through launchd and does **not** inherit
an exported `CLAUDE_SKILLS_DIR` — invoke `run.sh` directly when testing, or your
real skills directory is the target.
