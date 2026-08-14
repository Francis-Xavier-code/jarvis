"""agent-tools: bash + filesystem tools for the assistant (pi-agent style).

Gives the LLM the ability to actually *do* things on this machine:
  * bash.execute(command, cwd?, timeout?)  - run a shell command
  * fs.read / fs.write / fs.edit / fs.append - text file operations
  * fs.list / fs.glob                       - discover files
  * fs.undo(path)                           - restore the last auto-backup

Security model:
  * **Every bash command requires explicit user confirmation** (y/N prompt;
    replaceable via kernel.confirm_action).
  * Files inside the project root are editable directly - including JARVIS
    plugins - because the kernel hot-reloads changes and failed reloads
    roll back automatically. Paths outside the project root require user
    confirmation. config.toml (secrets) and writes into .git/.venv/data/
    are refused outright.
  * **Automatic backups**: every write/edit/append snapshots the previous
    file into <data_dir>/backups/ (last 5 kept). If the assistant edits
    something into a broken state, tell it to call fs.undo(path) - or fix
    the file - and hot-reload will pick up the repair.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

from jarvis.types import KernelApi

MAX_BASH_OUTPUT = 6000
MAX_READ_CHARS = 8000
BACKUP_KEEP = 5


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated {len(text) - limit} chars)"


DEFAULT_IDENTITY = {"name": "JARVIS", "email": "jarvis@jarvis.local", "sign_edits": True}


# Comment style per file type; None means "do not sign" (would corrupt the file).
_COMMENT_STYLES = {
    ".py": "#", ".sh": "#", ".toml": "#", ".ini": "#", ".cfg": "#",
    ".yaml": "#", ".yml": "#", ".rb": "#", ".pl": "#", ".bash": "#",
    ".zsh": "#", ".fish": "#", ".mk": "#",
    ".js": "//", ".ts": "//", ".jsx": "//", ".tsx": "//",
    ".c": "//", ".cpp": "//", ".h": "//", ".hpp": "//", ".go": "//",
    ".rs": "//", ".java": "//", ".swift": "//", ".kt": "//", ".php": "//",
    ".css": "/* */",
    ".html": "<!-- -->", ".xml": "<!-- -->", ".svg": "<!-- -->",
    ".md": "<!-- -->", ".markdown": "<!-- -->",
    ".sql": "--", ".lua": "--",
    ".txt": "plain",
}


# ---- JARVIS identity (isolated from the host git config) ----
def _identity(kernel: KernelApi) -> "tuple[str, str, bool]":
    """JARVIS's own identity used to sign edits.

    Reads ONLY the JARVIS config ([agent-identity] section) and falls back to a
    local-only default. It deliberately never consults ~/.gitconfig / `git
    config`, so the host user's real email is never leaked into files.
    """
    cfg = kernel.config.get("agent-identity", {}) or {}
    name = str(cfg.get("name") or DEFAULT_IDENTITY["name"]).strip()
    email = str(cfg.get("email") or DEFAULT_IDENTITY["email"]).strip()
    sign = cfg.get("sign_edits", DEFAULT_IDENTITY["sign_edits"])
    if isinstance(sign, str):
        sign = sign.strip().lower() in ("1", "true", "yes", "on")
    return name, email, bool(sign)


def _comment_style(path: Path) -> "str | None":
    return _COMMENT_STYLES.get(path.suffix.lower())


def _bump(version: str, kind: str) -> str:
    """Semver bump: Added -> minor, otherwise patch."""
    parts = version.split(".")
    try:
        major, minor, patch = (int(p) for p in parts[:3])
    except ValueError:
        return f"{version}.1"
    if kind == "Added":
        minor += 1
        patch = 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def _sign_file(kernel: KernelApi, p: Path) -> None:
    """Append a traceable "last modified by JARVIS <email>" signature.

    Idempotent per identity (a file already signed by this email is not
    re-signed), format-aware (comment syntax per file type; JSON/binary and
    unknown formats are skipped to avoid corruption), and runs AFTER the
    auto-backup so backups stay pristine.
    """
    name, email, enabled = _identity(kernel)
    if not enabled:
        return
    style = _comment_style(p)
    if style is None:
        return
    try:
        content = p.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return
    if re.search(rf"modified by .*<{re.escape(email)}>", content):
        return  # already signed by this identity
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if style == "#":
        block = f"\n# --- last modified by {name} <{email}> on {ts} ---\n"
    elif style == "//":
        block = f"\n// --- last modified by {name} <{email}> on {ts} ---\n"
    elif style == "/* */":
        block = f"\n/* --- last modified by {name} <{email}> on {ts} --- */\n"
    elif style == "<!-- -->":
        block = f"\n<!-- --- last modified by {name} <{email}> on {ts} --- -->\n"
    elif style == "--":
        block = f"\n-- --- last modified by {name} <{email}> on {ts} ---\n"
    else:  # plain text
        block = f"\n--- last modified by {name} <{email}> on {ts} ---\n"
    try:
        with p.open("a", encoding="utf-8") as fh:
            fh.write(block)
    except OSError:
        pass


def _root() -> Path:
    return Path.cwd().resolve()


def _protected(path: Path) -> bool:
    parts = path.parts
    return (
        ".git" in parts
        or ".venv" in parts
        or "sessions" in parts
        or "data" in parts
        or "backups" in parts
    )


def _resolve(kernel: KernelApi, raw: str, write: bool) -> Path:
    """Resolve + guard a path. Raises PermissionError when access is refused."""
    p = Path(raw).expanduser().resolve()
    root = _root()
    try:
        in_root = p.is_relative_to(root)
    except AttributeError:  # Python < 3.9
        in_root = p == root or str(p).startswith(str(root) + os.sep)
    if p.name == "config.toml":
        raise PermissionError("config.toml holds secrets and is off-limits")
    if write:
        maint = _maintenance_note()
        if maint:
            raise PermissionError(
                f"maintenance mode ({maint}) - refuse concurrent writes: {p}"
            )
    if write and _is_frozen(p):
        # frozen writes must NEVER be auto-approved (auto_approve=true would
        # otherwise bypass the gate) - confirm_hard always asks the human.
        if not kernel.confirm_hard(
            f"[frozen] {p} is protected (.jarvis-frozen) - confirm modification?"
        ):
            raise PermissionError(f"frozen path not confirmed: {p}")
    if not in_root:
        if not kernel.confirm(f"[fs] access outside project root: {p}?"):
            raise PermissionError(f"path outside project root not confirmed: {p}")
    if write and _protected(p):
        raise PermissionError(f"write refused for protected path: {p}")
    return p


def _backup(kernel: KernelApi, p: Path) -> None:
    """Snapshot the current file before it is modified (keep last N)."""
    if not p.exists() or not p.is_file():
        return
    backups_dir = Path(kernel.data_dir) / "backups"
    key = hashlib.sha256(str(p.resolve()).encode()).hexdigest()[:12]
    target_dir = backups_dir / key
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"{ts}_{p.name}"
    try:
        shutil.copy2(p, target)
    except OSError:
        return
    for old in sorted(target_dir.glob(f"*_{p.name}"))[:-BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def _latest_backup(kernel: KernelApi, p: Path) -> "Path | None":
    key = hashlib.sha256(str(p.resolve()).encode()).hexdigest()[:12]
    candidates = sorted((Path(kernel.data_dir) / "backups" / key).glob(f"*_{p.name}"))
    return candidates[-1] if candidates else None


# ---- self-modification guardrails (JARVIS editing JARVIS) ----
# JARVIS can edit its own files - that is the point - but a bad edit must
# never be able to brick startup or corrupt the kernel contract. Three
# mechanisms: syntax pre-validation, atomic writes, and a frozen-path list.

# Files whose NEW content is validated before it is allowed on disk.
_SYNTAX_CHECK_SUFFIXES = {".py", ".toml"}

# Paths (relative to the project root) that require user confirmation before
# fs.write/edit/append touches them: a bare name matches exactly, a trailing
# "/" or a directory prefix protects everything under it.
_FROZEN_FILE = ".jarvis-frozen"

# When this file exists at the project root, fs.* writes are refused: the
# human (or another process) is working, and concurrent edits are the #1
# cause of chain reactions. Content is shown in the refusal message.
_MAINTENANCE_FILE = ".jarvis-maintenance"


def _maintenance_note() -> "str | None":
    f = _root() / _MAINTENANCE_FILE
    if f.exists():
        return (f.read_text(encoding="utf-8").strip() or "maintenance in progress")
    return None


def _check_syntax(p: Path, content: str) -> "str | None":
    """Validate the NEW content of a source/manifest file BEFORE writing.

    Returns an error message, or None when valid. Guards against JARVIS
    writing itself into a state that cannot parse (startup crashes)."""
    if p.suffix not in _SYNTAX_CHECK_SUFFIXES:
        return None
    try:
        if p.suffix == ".py":
            compile(content, str(p), "exec")
        else:
            tomllib.loads(content)
    except Exception as exc:  # noqa: BLE001 - SyntaxError / TOMLDecodeError
        return f"{p.suffix} syntax error in new content: {exc}"
    return None


def _atomic_write(p: Path, content: str) -> None:
    """Write atomically (same-dir temp file + rename) so hot-reload watchers
    never observe a half-written file."""
    tmp = p.with_name(f".{p.name}.jarvis-tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, p)


def _frozen_entries() -> list[str]:
    """Protected paths from .jarvis-frozen (one per line; # comments)."""
    f = _root() / _FROZEN_FILE
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _is_frozen(p: Path) -> bool:
    """True when a write to p must pass the user-confirmation gate."""
    root = _root()
    try:
        rel = p.relative_to(root)
    except ValueError:
        return False
    rel_str = rel.as_posix()
    for entry in _frozen_entries():
        entry = entry.strip("/")
        if rel_str == entry or rel_str.startswith(entry + "/"):
            return True
    return False


def setup(kernel: KernelApi) -> None:
    @kernel.tool(
        "bash.execute",
        "Execute a shell command on this machine and return its output. "
        "Requires user confirmation every time. Prefer fs.* tools for file changes.",
        {"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout": {"type": "integer"}},
    )
    def bash_execute(command: str, cwd: str = "", timeout: int = 30) -> str:
        if not command.strip():
            return "[bash] empty command"
        if not kernel.confirm(f"[bash] run: {command!r}"):
            return "[bash] command not confirmed by the user"
        try:
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=cwd or str(_root()),
                capture_output=True,
                text=True,
                timeout=min(max(int(timeout), 1), 300),
            )
        except subprocess.TimeoutExpired:
            return f"[bash] timed out after {timeout}s"
        except FileNotFoundError:
            return "[bash] shell not found"
        except Exception as exc:  # noqa: BLE001
            return f"[bash] failed: {exc}"
        combined = ((result.stdout or "") + (result.stderr or "")).strip()
        return f"exit {result.returncode}\n" + _truncate(combined or "(no output)", MAX_BASH_OUTPUT)

    @kernel.tool(
        "fs.read",
        "Read a UTF-8 text file inside the project root (or elsewhere with user confirmation)",
        {"path": {"type": "string"}},
    )
    def fs_read(path: str) -> str:
        try:
            p = _resolve(kernel, path, write=False)
        except PermissionError as exc:
            return f"[fs] {exc}"
        if not p.exists():
            return f"[fs] not found: {p}"
        if p.is_dir():
            return "[fs] is a directory (use fs.list)"
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"[fs] binary or non-UTF8 file ({p.stat().st_size} bytes)"
        except Exception as exc:  # noqa: BLE001
            return f"[fs] read failed: {exc}"
        return _truncate(content, MAX_READ_CHARS)

    @kernel.tool(
        "fs.write",
        "Overwrite a file with new content (auto-backup first; refuses protected paths)",
        {"path": {"type": "string"}, "content": {"type": "string"}},
    )
    def fs_write(path: str, content: str) -> str:
        try:
            p = _resolve(kernel, path, write=True)
        except PermissionError as exc:
            return f"[fs] {exc}"
        err = _check_syntax(p, content)
        if err:
            return f"[fs] refused: {err}"
        try:
            _backup(kernel, p)
            p.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(p, content)
        except Exception as exc:  # noqa: BLE001
            return f"[fs] write failed: {exc}"
        _sign_file(kernel, p)
        return f"[fs] wrote {len(content)} chars to {p}"

    @kernel.tool(
        "fs.edit",
        "Replace text in a file. old must match exactly once (auto-backup first)",
        {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
    )
    def fs_edit(path: str, old: str, new: str) -> str:
        if not old:
            return "[fs] old must not be empty"
        try:
            p = _resolve(kernel, path, write=True)
        except PermissionError as exc:
            return f"[fs] {exc}"
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return f"[fs] read failed: {exc}"
        count = content.count(old)
        if count != 1:
            return f"[fs] old matched {count} times (must match exactly once)"
        new_content = content.replace(old, new, 1)
        err = _check_syntax(p, new_content)
        if err:
            return f"[fs] refused: {err}"
        _backup(kernel, p)
        _atomic_write(p, new_content)
        _sign_file(kernel, p)
        return f"[fs] replaced in {p}"

    @kernel.tool(
        "fs.append",
        "Append text to a file (auto-backup first)",
        {"path": {"type": "string"}, "content": {"type": "string"}},
    )
    def fs_append(path: str, content: str) -> str:
        try:
            p = _resolve(kernel, path, write=True)
        except PermissionError as exc:
            return f"[fs] {exc}"
        try:
            existing = p.read_text(encoding="utf-8") if p.exists() else ""
        except Exception as exc:  # noqa: BLE001
            return f"[fs] read failed: {exc}"
        new_content = existing + content
        err = _check_syntax(p, new_content)
        if err:
            return f"[fs] refused: {err}"
        try:
            _backup(kernel, p)
            p.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(p, new_content)
        except Exception as exc:  # noqa: BLE001
            return f"[fs] append failed: {exc}"
        _sign_file(kernel, p)
        return f"[fs] appended {len(content)} chars to {p}"

    @kernel.tool(
        "fs.list",
        "List entries in a directory (relative to the project root by default)",
        {"path": {"type": "string"}},
    )
    def fs_list(path: str = "") -> str:
        try:
            p = _resolve(kernel, path or ".", write=False)
        except PermissionError as exc:
            return f"[fs] {exc}"
        if not p.exists() or not p.is_dir():
            return "[fs] not a directory"
        try:
            entries = sorted(p.iterdir())
        except OSError as exc:
            return f"[fs] list failed: {exc}"
        lines = [f"{('dir ' if e.is_dir() else 'file')}  {e.name}" for e in entries]
        return "\n".join(lines) if lines else "(empty directory)"

    @kernel.tool(
        "fs.glob",
        "Find files by glob pattern relative to the project root (e.g. **/*.py)",
        {"pattern": {"type": "string"}},
    )
    def fs_glob(pattern: str) -> str:
        root = _root()
        try:
            matches = sorted(str(p.relative_to(root)) for p in root.glob(pattern) if p.is_file())
        except Exception as exc:  # noqa: BLE001
            return f"[fs] glob failed: {exc}"
        return "\n".join(matches[:200]) if matches else "(no matches)"

    @kernel.tool(
        "fs.undo",
        "Restore a file from its most recent auto-backup (after a bad edit)",
        {"path": {"type": "string"}},
    )
    def fs_undo(path: str) -> str:
        try:
            p = _resolve(kernel, path, write=True)
        except PermissionError as exc:
            return f"[fs] {exc}"
        backup = _latest_backup(kernel, p)
        if backup is None:
            return f"[fs] no backup found for {p}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return f"[fs] restore failed: {exc}"
        return f"[fs] restored {p} from backup {backup.name}"

    @kernel.tool(
        "agent.identity",
        "Show JARVIS's own identity (name/email) used to sign edits - isolated from the host git config",
    )
    def agent_identity() -> str:
        name, email, sign = _identity(kernel)
        return (
            f"name: {name}\nemail: {email}\nsign_edits: {sign}\n"
            "This identity comes from JARVIS config [agent-identity] (or a local-only default) "
            "and NEVER reads the host ~/.gitconfig. For git commits, stay isolated with:\n"
            f"    git -c user.name={name} -c user.email={email} commit ..."
        )

    @kernel.tool(
        "plugin.log_change",
        "Record a change to a plugin: add a CHANGELOG entry and bump its version in plugin.toml. Call this after modifying any plugin file (the plugin CHANGELOG/versioning standard requires it).",
        {"plugin": {"type": "string"}, "note": {"type": "string"}, "kind": {"type": "string"}},
    )
    def plugin_log_change(plugin: str, note: str, kind: str = "Changed") -> str:
        if not note.strip():
            return "[plugin] note must not be empty"
        kind = kind.strip().capitalize()
        if kind not in ("Added", "Changed", "Fixed", "Removed"):
            kind = "Changed"
        pdir = _root() / "plugins" / plugin
        toml_path = pdir / "plugin.toml"
        if not toml_path.exists():
            return f"[plugin] no plugin.toml at {pdir}"
        try:
            with toml_path.open("rb") as fh:
                data = tomllib.load(fh)
            version = str(data["plugin"].get("version", "0.0.0"))
        except Exception as exc:  # noqa: BLE001
            return f"[plugin] cannot read plugin.toml: {exc}"
        new_version = _bump(version, kind)
        toml_text = toml_path.read_text(encoding="utf-8")
        toml_text = re.sub(
            r"(?m)^version\s*=\s*\"[^\"]+\"",
            f'version = "{new_version}"',
            toml_text,
            count=1,
        )
        name, email, _ = _identity(kernel)
        ts = time.strftime("%Y-%m-%d")
        entry = f"## [{new_version}] - {ts}\n\n### {kind}\n- {note} (by {name} <{email}>)\n\n"
        changelog_path = pdir / "CHANGELOG.md"
        if changelog_path.exists():
            content = changelog_path.read_text(encoding="utf-8")
            m = re.search(r"(?m)^## \[", content)
            content = content[: m.start()] + entry + content[m.start():] if m else content.rstrip() + "\n\n" + entry
        else:
            content = f"# Changelog — {plugin}\n\n{entry}"
        try:
            toml_path.write_text(toml_text, encoding="utf-8")
            changelog_path.write_text(content, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return f"[plugin] write failed: {exc}"
        return f"[plugin] logged change to {plugin} v{new_version} ({kind}) - remember to also bump plugin.toml deps if any"


def teardown(kernel: KernelApi) -> None:
    pass
