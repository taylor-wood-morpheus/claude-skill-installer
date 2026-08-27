# Add to Claude Skills

Install a Claude Code skill into `~/.claude/skills` from a Finder selection, a
text selection, or the clipboard. macOS only. There is no command to type.

## Install

```sh
git clone <this-repo> && cd claude-skill-installer && ./install.sh
```

`./uninstall.sh` removes it. Skills already installed are never touched.

Requires macOS and Python 3.12+ (`brew install python`). The `claude` CLI is
used to name skills that arrive without frontmatter, and an authenticated `gh`
unlocks private repos and better GitHub rate limits — the installer reports
which of these it found.

## Use

| | Trigger | Handles |
|---|---|---|
| 1 | Finder right-click → Quick Actions | a `.zip`, a folder, a loose `SKILL.md` |
| 2 | select text → right-click → Services | skill markdown in a message or doc |
| 3 | **⌃⌥⌘S** anywhere | GitHub URLs, copied skill text, a file path |
| 4 | right-click → Services → **Claude Skills Shortcuts** | shows and changes the shortcuts above |

### Viewing and changing the shortcuts

Right-click anywhere → Services → **Claude Skills Shortcuts** opens with every
binding listed:

```
Add to Claude Skills                 (none)
Add Selected Text to Claude Skills   (none)
Add Clipboard to Claude Skills       ⌃⌥⌘S
Claude Skills Shortcuts              (none)   (this dialog)
```

Reading it is the point — press Close and nothing changes. Picking a row offers
presets, a free-text field and "remove the shortcut", then returns to the list.
Any of the three actions can take a shortcut, not just the clipboard one: a
shortcut on the text action fires on the current selection, which is quicker
than the context menu. The dialog itself is deliberately not bindable — losing
the shortcut you use to fix shortcuts is a bad afternoon.

Typed shortcuts are accepted as `ctrl-opt-cmd-K`, `cmd+shift+L`, `⌃⌥⌘K` or the
raw `^~@k`; one with no modifier is refused, since it would fire while you type.

Reinstalling never clobbers a shortcut you have chosen — `install.sh` only
writes the ⌃⌥⌘S default when no binding exists yet. There is also
`run.sh hotkey --show` to print the table, plus `--set cmd-shift-L` / `--set none`
for scripted use,
and System Settings → Keyboard → Keyboard Shortcuts → Services still works.

### What the hotkey accepts

- `github.com/o/r` — whole repo; every `SKILL.md` in it, with a picker
- `github.com/o/r/tree/ref/path` — one skill directory
- `github.com/o/r/blob/ref/path/SKILL.md` — one file
- `gist.github.com/…` — markdown files in a gist
- any other URL — a zip is unpacked, anything else read as markdown
- raw skill markdown, with or without frontmatter
- a filesystem path

URLs pasted without a scheme (`github.com/o/r/...`, as copied from a browser bar
or a chat message) are recognised and fetched over https. A paste whose entire
body is a link is refused rather than named — otherwise headless Claude writes
convincing frontmatter for a skill that contains nothing but a URL.

Slack message permalinks are **rejected with an explanation**: they carry no
readable content without a Slack app token. Copy the message *text* instead, or
download the attachment and use the Finder action.

## Behaviour

- **Missing frontmatter** is authored by headless `claude -p`, supplying a
  kebab-case `name` and a `description`.
- **Several skills in one source** raise a checklist so you choose. A single
  skill installs without asking.
- **Executable content** — anything not `.md`/`.txt`/`.json`/`.yaml`, or marked
  `+x` — raises a confirmation listing the files. Documentation-only skills
  install silently, so the friction lands only where it earns its place. A skill
  from a chat message is a stranger's code running with your agent's
  permissions; read that dialog.
- **Name collisions** offer Overwrite / Keep Both (`name-2`) / Cancel.
- **Zip slip** — an archive member resolving outside the destination aborts the
  whole install.
- Quarantine xattrs are stripped after copy; `__MACOSX`, `._*` and `.DS_Store`
  are pruned.

## How it works

Four Automator `.workflow` bundles in `~/Library/Services`, all invoking
`~/.claude/tools/skill-installer/run.sh`.

`services.py` is the single description of all four bundles. Both the generator
and the hotkey editor read it, because every service needs an explicit
`presentation_modes` entry in `pbs` — macOS hides any service that is not
enabled, and a service added to one list while missing from the other never
appears. Menu titles must also be unique: `pbs` keys services by menu title, so
two bundles sharing a title collapse into one entry and only one can be enabled.

Two further constraints shaped this. Services are matched by **UTI conformance,
never by filename**, so the Finder item cannot be scoped to files called `SKILL.md`; it
declares `public.folder`, `public.archive` and `public.plain-text`, which covers
folders, every archive flavour and anything text-like. And services run with a
minimal environment via launchd, so `run.sh` resolves an interpreter and fixes
`PATH` before handing off.

`set_hotkey.py` owns the `pbs` encoding, so both the installer and the
hotkey editor write a shortcut through the same code path rather than keeping
two copies of it.

`make_quick_actions.py` generates the bundles locally from an action plist
embedded as `action_template.b64`. Both details matter: the plist carries a
dozen undocumented `AM*` keys that should not be hand-authored, and a
`.workflow` that arrives inside a download is Gatekeeper-quarantined and refuses
to run — one written by a script is not.

## Diagnostics

`~/.claude/tools/skill-installer/install.log` (rotating, 1 MB × 3) records every
trigger, fetch, discovery decision, dialog answer and install path. Services
swallow stdout and stderr, so this is the only place failures are visible.

## Testing

```sh
CLAUDE_SKILLS_DIR=/tmp/x SKILL_INSTALLER_AUTO_ANSWER=Install ./run.sh files skill.zip
```

`CLAUDE_SKILLS_DIR` redirects the install; `SKILL_INSTALLER_AUTO_ANSWER`
auto-answers dialogs with the given button label and prints them to stderr.
Note that `automator` launches services through launchd and does **not** inherit
an exported `CLAUDE_SKILLS_DIR` — invoke `run.sh` directly when testing, or your
real skills directory is the target.
