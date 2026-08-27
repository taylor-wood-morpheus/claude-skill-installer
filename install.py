#!/usr/bin/env python3
"""Install Claude Code skills from files, pasted text, GitHub URLs or the clipboard.

Invoked by the macOS Quick Actions in ~/Library/Services. There is deliberately no
human-facing command line: all feedback goes through native dialogs and
notifications, and all diagnostics go to install.log next to this file.

Entry points:
    install.py files PATH...   a zip, a directory, or a loose SKILL.md
    install.py text            skill markdown on stdin (selected text)
    install.py clipboard       dispatch on whatever is on the pasteboard
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

SKILLS_DIR = Path(
    os.environ.get("CLAUDE_SKILLS_DIR", Path.home() / ".claude" / "skills")
).expanduser()
# Set to a button label to auto-answer every dialog; used by the test harness and
# by any non-GUI invocation, where a modal dialog would simply hang.
AUTO_ANSWER = os.environ.get("SKILL_INSTALLER_AUTO_ANSWER")
LOG_PATH = Path(__file__).resolve().parent / "install.log"
USER_AGENT = "claude-skill-installer/1.0"
HTTP_TIMEOUT = 30
MAX_LLM_CHARS = 8000
# Suffixes that are inert documentation. Anything else in a skill is treated as
# code for the purposes of the review prompt.
DOC_SUFFIXES = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".toml"}
JUNK_NAMES = {"__MACOSX", ".DS_Store", "__pycache__"}

log = logging.getLogger("skill-installer")


class SkillError(Exception):
    """A failure with a message fit to show the user in a dialog."""


# --------------------------------------------------------------------------- #
# Sources: what a trigger resolved to, before we know how many skills it holds
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Tree:
    """A directory tree on disk, to be scanned for SKILL.md files."""

    root: Path
    origin: str


@dataclass(frozen=True)
class LooseMarkdown:
    """Skill markdown that is not yet laid out as a directory."""

    text: str
    origin: str


Source = Tree | LooseMarkdown


@dataclass(frozen=True)
class Candidate:
    """A single skill, laid out on disk and ready to copy into SKILLS_DIR."""

    name: str
    description: str
    root: Path
    origin: str

    @property
    def code_files(self) -> list[Path]:
        """Files that are not inert documentation, i.e. things that can run."""
        return sorted(
            p.relative_to(self.root)
            for p in self.root.rglob("*")
            if p.is_file()
            and (p.suffix.lower() not in DOC_SUFFIXES or os.access(p, os.X_OK))
        )

    @property
    def file_count(self) -> int:
        return sum(1 for p in self.root.rglob("*") if p.is_file())


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
        f'with prompt "This source has {len(candidates)} skills. '
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


def clipboard_text() -> str:
    proc = subprocess.run(["pbpaste"], capture_output=True, text=True, check=False)
    text = proc.stdout
    log.debug("clipboard length=%d head=%r", len(text), text[:120])
    return text


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


def synthesise_frontmatter(text: str) -> dict[str, str]:
    """Ask headless Claude to author the name/description a paste is missing."""
    prompt = (
        "The text below is a Claude Code skill whose YAML frontmatter is missing "
        "or invalid. Reply with ONLY a JSON object, no prose and no code fence, "
        'with exactly two keys: "name" (kebab-case, at most 48 characters, no '
        'spaces) and "description" (one line, starting with a verb, saying what '
        "the skill does and when it should be used).\n\n"
        "----- BEGIN SKILL -----\n"
        f"{text[:MAX_LLM_CHARS]}\n"
        "----- END SKILL -----"
    )
    log.info("invoking headless claude to synthesise frontmatter chars=%d", len(text))
    proc = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    log.debug("claude rc=%s stdout=%r stderr=%r", proc.returncode, proc.stdout[:500], proc.stderr[:500])
    if proc.returncode != 0:
        raise SkillError(
            "This text has no name/description frontmatter, and asking Claude to "
            f"write one failed:\n\n{proc.stderr.strip()[:300]}"
        )
    raw = proc.stdout.strip()
    if fenced := FENCE.match(raw):
        raw = fenced.group(1).strip()
    try:
        fields = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError) as exc:
        log.error("unparseable claude reply: %r", raw[:300])
        raise SkillError(
            "Claude did not return a usable name for this skill. See install.log."
        ) from exc
    name, description = slugify(str(fields.get("name", ""))), str(
        fields.get("description", "")
    ).strip()
    if not description:
        raise SkillError("Claude returned no description for this skill.")
    log.info("synthesised name=%r description=%r", name, description)
    return {"name": name, "description": description}


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

RE_GH_TREE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+?)/?$")
RE_GH_BLOB = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+?)$")
RE_GH_REPO = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")
RE_GIST = re.compile(r"^https?://gist\.github\.com/(?:[^/]+/)?([0-9a-fA-F]+)/?$")
RE_SLACK = re.compile(r"^https?://[^/]*\.slack\.com/")
RE_URL = re.compile(r"^https?://\S+$")


def _gh_token() -> str | None:
    for env in ("GITHUB_TOKEN", "GH_TOKEN"):
        if token := os.environ.get(env):
            log.debug("using github token from %s", env)
            return token
    proc = subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=False
    )
    if proc.returncode == 0 and proc.stdout.strip():
        log.debug("using github token from gh auth token")
        return proc.stdout.strip()
    log.debug("no github token available; requests will be unauthenticated")
    return None


def fetch(url: str, *, token: str | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if token and "github" in url:
        headers["Authorization"] = f"Bearer {token}"
    log.info("fetching url=%s authenticated=%s", url, "Authorization" in headers)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        log.error("http error url=%s status=%s", url, exc.code)
        raise SkillError(f"GitHub returned {exc.code} for\n{url}") from exc
    except urllib.error.URLError as exc:
        log.error("network error url=%s reason=%s", url, exc.reason)
        raise SkillError(f"Could not reach\n{url}\n\n{exc.reason}") from exc
    log.info("fetched url=%s bytes=%d", url, len(body))
    return body


def default_branch(owner: str, repo: str, token: str | None) -> str:
    payload = json.loads(
        fetch(f"https://api.github.com/repos/{owner}/{repo}", token=token)
    )
    branch = payload.get("default_branch", "main")
    log.info("default branch owner=%s repo=%s branch=%s", owner, repo, branch)
    return branch


def _extract_tarball(blob: bytes, dest: Path, subpath: str | None) -> Path:
    archive = dest / "archive.tar.gz"
    archive.write_bytes(blob)
    unpacked = dest / "unpacked"
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(unpacked, filter="data")
    archive.unlink()
    roots = [p for p in unpacked.iterdir() if p.is_dir()]
    if len(roots) != 1:
        raise SkillError(f"Unexpected archive layout: {len(roots)} top-level entries.")
    root = roots[0]
    if subpath:
        root = root / subpath
        if not root.is_dir():
            raise SkillError(f"The archive has no directory at\n{subpath}")
    log.info("extracted tarball root=%s subpath=%r", root, subpath)
    return root


def resolve_url(url: str, workdir: Path) -> Source:
    """Turn a URL into a Tree or LooseMarkdown, downloading as needed."""
    token = _gh_token()

    if RE_SLACK.match(url):
        raise SkillError(
            "That is a Slack link, which carries no content that can be read "
            "without a Slack app token.\n\n"
            "Select the skill text in the message and copy that instead, or "
            "download the attachment and right-click it in Finder."
        )

    if match := RE_GH_TREE.match(url):
        owner, repo, ref, subpath = match.groups()
        log.info("github tree owner=%s repo=%s ref=%s path=%s", owner, repo, ref, subpath)
        blob = fetch(
            f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}", token=token
        )
        return Tree(_extract_tarball(blob, workdir, subpath), origin=url)

    if match := RE_GH_BLOB.match(url):
        owner, repo, ref, path = match.groups()
        log.info("github blob owner=%s repo=%s ref=%s path=%s", owner, repo, ref, path)
        raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
        return LooseMarkdown(fetch(raw, token=token).decode("utf-8"), origin=url)

    if match := RE_GIST.match(url):
        gist_id = match.group(1)
        payload = json.loads(
            fetch(f"https://api.github.com/gists/{gist_id}", token=token)
        )
        files = payload.get("files", {})
        log.info("gist id=%s files=%s", gist_id, list(files))
        body = "\n\n".join(
            f["content"] for f in files.values() if (f.get("filename") or "").endswith(".md")
        )
        if not body:
            raise SkillError("That gist contains no markdown files.")
        return LooseMarkdown(body, origin=url)

    if match := RE_GH_REPO.match(url):
        owner, repo = match.groups()
        ref = default_branch(owner, repo, token)
        blob = fetch(
            f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}", token=token
        )
        return Tree(_extract_tarball(blob, workdir, None), origin=url)

    # Any other URL: a zip is an archive, everything else is treated as markdown.
    blob = fetch(url, token=token)
    if blob[:2] == b"PK":
        log.info("generic url is a zip archive url=%s", url)
        archive = workdir / "download.zip"
        archive.write_bytes(blob)
        return Tree(unzip(archive, workdir / "unzipped"), origin=url)
    return LooseMarkdown(blob.decode("utf-8", errors="replace"), origin=url)


def unzip(archive: Path, dest: Path) -> Path:
    """Extract a zip, refusing any member that would escape `dest` (zip slip)."""
    dest.mkdir(parents=True, exist_ok=True)
    resolved_dest = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        members = zf.namelist()
        log.info("unzipping archive=%s members=%d", archive.name, len(members))
        for member in members:
            target = (resolved_dest / member).resolve()
            if target != resolved_dest and resolved_dest not in target.parents:
                log.error("rejecting escaping zip member=%r", member)
                raise SkillError(
                    f"This zip tries to write outside the install directory "
                    f"({member!r}) and was not installed."
                )
        zf.extractall(resolved_dest)
    prune_junk(dest)
    # A zip of one directory is conventional; unwrap it so the skill root is found.
    entries = [p for p in dest.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        log.debug("unwrapping single top-level directory %s", entries[0].name)
        return entries[0]
    return dest


def prune_junk(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
        if path.name in JUNK_NAMES or path.name.startswith("._"):
            log.debug("pruning junk path=%s", path)
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(
                missing_ok=True
            )


# --------------------------------------------------------------------------- #
# Discovery: source -> candidates
# --------------------------------------------------------------------------- #


def _skill_roots(tree: Path) -> list[Path]:
    found = sorted(
        {p.parent for p in tree.rglob("*") if p.is_file() and p.name.lower() == "skill.md"}
    )
    log.info("found %d SKILL.md files under %s", len(found), tree)
    return found


def _candidate_from_dir(root: Path, origin: str) -> Candidate:
    skill_md = next(p for p in root.iterdir() if p.name.lower() == "skill.md")
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fields = parse_frontmatter(text) or {}
    if not fields.get("name") or not fields.get("description"):
        log.info("skill at %s has incomplete frontmatter=%s", root, fields)
        fields = {**fields, **synthesise_frontmatter(text)}
        skill_md.write_text(
            f"---\nname: {fields['name']}\ndescription: {fields['description']}\n---\n\n"
            + FRONTMATTER.sub("", text).lstrip(),
            encoding="utf-8",
        )
    return Candidate(
        name=slugify(fields["name"]),
        description=fields["description"],
        root=root,
        origin=origin,
    )


def _candidate_from_markdown(text: str, origin: str, workdir: Path) -> Candidate:
    if fenced := FENCE.match(text):
        log.debug("stripping surrounding code fence")
        text = fenced.group(1)
    fields = parse_frontmatter(text) or {}
    if not fields.get("name") or not fields.get("description"):
        fields = {**fields, **synthesise_frontmatter(text)}
        text = (
            f"---\nname: {fields['name']}\ndescription: {fields['description']}\n---\n\n"
            + FRONTMATTER.sub("", text).lstrip()
        )
    name = slugify(fields["name"])
    root = workdir / "laid-out" / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(text.rstrip() + "\n", encoding="utf-8")
    log.info("laid out pasted skill name=%s root=%s", name, root)
    return Candidate(name=name, description=fields["description"], root=root, origin=origin)


def discover(source: Source, workdir: Path) -> list[Candidate]:
    match source:
        case LooseMarkdown(text=text, origin=origin):
            docs = split_documents(text)
            return [
                _candidate_from_markdown(doc, origin, workdir / f"doc{i}")
                for i, doc in enumerate(docs)
            ]
        case Tree(root=root, origin=origin):
            roots = _skill_roots(root)
            if not roots:
                loose = [p for p in root.rglob("*.md") if p.is_file()]
                log.info("no SKILL.md in tree; %d loose markdown files", len(loose))
                if len(loose) == 1:
                    return [
                        _candidate_from_markdown(
                            loose[0].read_text(encoding="utf-8", errors="replace"),
                            origin,
                            workdir / "loose",
                        )
                    ]
                raise SkillError(
                    "No SKILL.md found in there, so there is nothing to install."
                )
            return [_candidate_from_dir(r, origin) for r in roots]


# --------------------------------------------------------------------------- #
# Install
# --------------------------------------------------------------------------- #


def review(candidates: Sequence[Candidate]) -> None:
    """Confirm before installing anything that can execute. Pure documentation
    installs silently: the friction is reserved for the case that earns it."""
    risky = [c for c in candidates if c.code_files]
    if not risky:
        log.info("no executable content in %d candidate(s); installing silently", len(candidates))
        return
    lines = [
        "These skills contain files that can run, not just instructions:",
        "",
    ]
    for c in risky:
        shown = c.code_files[:8]
        lines.append(f"{c.name}")
        lines += [f"    {p}" for p in shown]
        if len(c.code_files) > len(shown):
            lines.append(f"    … and {len(c.code_files) - len(shown)} more")
    lines += ["", f"Source: {risky[0].origin}", "", "Install anyway?"]
    if ask("\n".join(lines), ["Cancel", "Install"], "Install") != "Install":
        raise SkillError("cancelled")


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
            f"Incoming: {candidate.file_count} file(s) from {candidate.origin}",
            ["Cancel", "Keep Both", "Overwrite"],
            "Keep Both",
        )
        if choice == "Overwrite":
            shutil.rmtree(dest)
        elif choice == "Keep Both":
            dest = SKILLS_DIR / _unique_name(candidate.name)
        else:
            raise SkillError("cancelled")
    shutil.copytree(candidate.root, dest)
    prune_junk(dest)
    subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(dest)],
        capture_output=True,
        check=False,
    )
    log.info("installed name=%s dest=%s files=%d origin=%s",
             candidate.name, dest, candidate.file_count, candidate.origin)
    return dest


# --------------------------------------------------------------------------- #
# Triggers
# --------------------------------------------------------------------------- #


def sources_from_paths(paths: Iterable[str], workdir: Path) -> list[Source]:
    sources: list[Source] = []
    for index, raw in enumerate(paths):
        path = Path(raw).expanduser()
        log.info("path input index=%d path=%s", index, path)
        if not path.exists():
            raise SkillError(f"No such file:\n{path}")
        if path.is_dir():
            sources.append(Tree(path, origin=str(path)))
        elif path.suffix.lower() == ".zip":
            sources.append(
                Tree(unzip(path, workdir / f"zip{index}"), origin=str(path))
            )
        else:
            sources.append(
                LooseMarkdown(
                    path.read_text(encoding="utf-8", errors="replace"), origin=str(path)
                )
            )
    return sources


def sources_from_text(text: str, workdir: Path) -> list[Source]:
    stripped = text.strip()
    if not stripped:
        raise SkillError("There is nothing to install — the text was empty.")
    if RE_URL.match(stripped) and "\n" not in stripped:
        log.info("text input is a single url")
        return [resolve_url(stripped, workdir)]
    if (path := Path(stripped).expanduser()).exists() and "\n" not in stripped:
        log.info("text input is a path")
        return sources_from_paths([stripped], workdir)
    return [LooseMarkdown(text, origin="pasted text")]


def run(argv: Sequence[str], workdir: Path) -> None:
    trigger, *rest = argv
    log.info("trigger=%s args=%s", trigger, rest)
    match trigger:
        case "files":
            sources = sources_from_paths(rest, workdir)
        case "text":
            sources = sources_from_text(sys.stdin.read(), workdir)
        case "clipboard":
            sources = sources_from_text(clipboard_text(), workdir)
        case other:
            raise SkillError(f"Unknown trigger {other!r}.")

    candidates = [c for source in sources for c in discover(source, workdir)]
    if not candidates:
        raise SkillError("Found nothing that looks like a skill.")
    log.info("discovered candidates=%s", [c.name for c in candidates])
    candidates = choose(candidates)
    review(candidates)
    installed = [install(c) for c in candidates]

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
        with tempfile.TemporaryDirectory(prefix="skill-install-") as tmp:
            run(sys.argv[1:], Path(tmp))
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
