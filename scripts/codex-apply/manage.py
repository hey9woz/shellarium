"""Preview and atomically deploy two files; capture uses an isolated Git index."""
import base64
from contextlib import contextmanager
import difflib
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from validate import Invalid, validate

REPO = Path(__file__).resolve().parents[2]
NAMES = ("config.toml", "AGENTS.md")
REL = tuple("scripts/codex-apply/config/" + name for name in NAMES)
VERSION_PREFIX = "chore(codex-apply): capture v"


def say(message):
    print(message, file=sys.stderr)


def quoted(path):
    return json.dumps(str(path), ensure_ascii=False)


def safe_path(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise Invalid("symbolic links are not supported: " + quoted(part))
    if path.exists() and not path.is_file():
        raise Invalid("expected a regular file: " + quoted(path))


def snapshot(path):
    safe_path(path)
    if not path.exists():
        return None
    return (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))


def contents(snap):
    return None if snap is None else snap[0]


def checked_files(directory, required):
    result = {}
    for name in NAMES:
        result[name] = snapshot(directory / name)
        if result[name] is None:
            if required:
                raise Invalid("missing file: " + quoted(directory / name))
        else:
            validate(name, contents(result[name]))
    return result


def git(*args, env=None, check=True):
    result = subprocess.run(["git", "-C", str(REPO), *args], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise Invalid("Git operation failed: " + args[0] + " (output suppressed); check Git identity, hooks, permissions and repository state locally")
    return result


def head():
    result = git("rev-parse", "--verify", "HEAD", check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def git_files(revision):
    files = {}
    for name, path in zip(NAMES, REL):
        result = git("show", f"{revision}:{path}", check=False) if revision else None
        files[name] = result.stdout if result and result.returncode == 0 else None
        if files[name] is not None:
            validate(name, files[name])
    return files


def version():
    current = 0
    if head():
        import re
        for subject in git("log", "--format=%s").stdout.decode().splitlines():
            match = re.fullmatch(re.escape(VERSION_PREFIX) + r"(\d+)", subject)
            if match:
                current = max(current, int(match[1]))
    return current


def atomic(path, data, mode=0o600):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".codex-apply-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def payload(directory, before):
    return json.dumps({"target": str(directory), "files": {
        name: None if snap is None else {"content": base64.b64encode(snap[0]).decode(), "mode": snap[1]}
        for name, snap in before.items()}}, ensure_ascii=False).encode()


@contextmanager
def lock(path):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a") as stream:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Invalid("another codex-apply is running; retry after it finishes") from None
        yield


def replace_files(directory, desired, before, pending, backup=None):
    """Publish a backup only after success. Preserve the previous generation on failure."""
    if pending.exists():
        raise Invalid("unfinished operation; inspect recovery file: " + quoted(pending))
    atomic(pending, payload(directory, before))
    try:
        for name in NAMES:
            if desired[name] != contents(before[name]):
                atomic(directory / name, desired[name])
        if backup:
            safe_path(backup)
            os.replace(pending, backup)
        else:
            pending.unlink()
    except BaseException:
        try:
            for name, original in before.items():
                path = directory / name
                if snapshot(path) == original:
                    continue
                if original is None:
                    safe_path(path)
                    path.unlink(missing_ok=True)
                else:
                    atomic(path, original[0], original[1])
            pending.unlink(missing_ok=True)
        except BaseException:
            say("codex-apply: rollback incomplete; recovery data: " + quoted(pending))
        raise


def preview(source, target, old, desired, label, number, capture):
    say("codex-apply" + (" --capture" if capture else ""))
    say("─" * 60)
    say(f"  From     {quoted(source)}\n  To       {quoted(target)}\n  Version  {label}")
    if capture:
        say(f"  Commit   {VERSION_PREFIX}{number:04d}")
    say("")
    for name in NAMES:
        state = "SAME" if old[name] == desired[name] else "NEW" if old[name] is None else "UPDATE"
        say(f"  {state:<8} {name}")
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
    for name in NAMES:
        if old[name] == desired[name]:
            continue
        print(f"\n── {name} " + "─" * 40)
        lines = difflib.unified_diff((old[name] or b"").decode().splitlines(keepends=True),
                                     desired[name].decode().splitlines(keepends=True),
                                     fromfile="current/" + name if old[name] is not None else "/dev/null",
                                     tofile="capture/" + name if capture else "repository/" + name)
        for line in lines:
            prefix = "\033[32m" if line.startswith("+") else "\033[31m" if line.startswith("-") else ""
            print((prefix if color else "") + line.rstrip("\n") + ("\033[0m" if color and prefix else ""))
            if not line.endswith("\n"):
                print("\\ No newline at end of file")
    sys.stdout.flush()


def confirm(capture):
    if not sys.stdin.isatty():
        raise Invalid("confirmation requires a terminal; no files were changed")
    say("")
    if capture:
        say("対象の2ファイルだけを取り込み、コミットします。")
        prompt = "取り込み・コミットを実行しますか？ [y/N] "
    else:
        say("変更前の2ファイルの状態をバックアップします（保持は1世代）。")
        prompt = "適用しますか？ [y/N] "
    print(prompt, end="", file=sys.stderr, flush=True)
    if sys.stdin.readline().strip().lower() not in {"y", "yes"}:
        say("キャンセルしました。変更していません。")
        return False
    return True


def capture_branch():
    result = git("symbolic-ref", "--quiet", "HEAD", check=False)
    if result.returncode:
        raise Invalid("capture requires a branch; detached HEAD is not supported")
    return result.stdout.decode().strip()


def check_git_operation():
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "BISECT_START"):
        path = Path(git("rev-parse", "--git-path", marker).stdout.decode().strip())
        if not path.is_absolute():
            path = REPO / path
        if path.exists():
            raise Invalid("finish or abort the in-progress Git operation before capture")
    if git("ls-files", "--unmerged").stdout:
        raise Invalid("resolve unmerged index entries before capture")


def check_capture(revision, source, local):
    check_git_operation()
    # Avoid overwriting pre-existing staged versions of our own files.
    if git("diff", "--cached", "--quiet", "--", *REL, check=False).returncode:
        raise Invalid("managed config files are staged; unstage them before capture")
    committed = git_files(revision)
    for name in NAMES:
        current = contents(local[name])
        if current not in (committed[name], source[name]):
            raise Invalid("uncommitted edits in repository config; reconcile locally before capture: " + name)
    return committed


def run_hook(name, env, *args):
    hooks = Path(git("rev-parse", "--git-path", "hooks").stdout.decode().strip())
    if not hooks.is_absolute():
        hooks = REPO / hooks
    hook = hooks / name
    if hook.is_file() and os.access(hook, os.X_OK):
        result = subprocess.run([str(hook), *args], cwd=REPO, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise Invalid("capture saved but commit failed in " + name + "; fix the hook and rerun --capture (output suppressed)")


def commit_capture(message, revision, desired, state, branch):
    # Run normal validation/message hooks against a separate index, then freeze
    # the reviewed tree. commit-tree cannot let hooks change the final snapshot.
    fd, index = tempfile.mkstemp(prefix=".capture-index-", dir=state)
    os.close(fd)
    os.unlink(index)
    fd, message_path = tempfile.mkstemp(prefix=".capture-message-", dir=state)
    message_bytes = (message + "\n").encode()
    with os.fdopen(fd, "wb") as stream:
        stream.write(message_bytes)
    env = os.environ.copy()
    env.update(GIT_INDEX_FILE=index, GIT_EDITOR=":")
    try:
        check_git_operation()
        if revision:
            git("read-tree", revision, env=env)
        else:
            git("read-tree", "--empty", env=env)
        git("add", "--", *REL, env=env)
        expected_tree = git("write-tree", env=env).stdout.strip()
        for hook, args in (("pre-commit", ()), ("prepare-commit-msg", (message_path, "message")),
                           ("commit-msg", (message_path,))):
            run_hook(hook, env, *args)
        if git("write-tree", env=env).stdout.strip() != expected_tree:
            raise Invalid("commit hook changed the reviewed index; no commit was created")
        if Path(message_path).read_bytes() != message_bytes:
            raise Invalid("commit hook changed the fixed version message; no commit was created")
        for name, path in zip(NAMES, REL):
            staged = git("show", ":" + path, env=env).stdout
            if staged != desired[name]:
                raise Invalid("Git filter changed validated settings; capture not committed")
            validate(name, staged)
        if any(contents(snapshot(REPO / path)) != desired[name] for name, path in zip(NAMES, REL)):
            raise Invalid("repository settings changed during hooks; review them before retrying capture")
        if head() != revision or capture_branch() != branch:
            raise Invalid("Git HEAD/branch changed during capture; retry")
        check_git_operation()
        options = ["-p", revision] if revision else []
        signing = git("config", "--bool", "--get", "commit.gpgsign", check=False)
        if signing.returncode not in {0, 1}:
            raise Invalid("invalid commit.gpgsign configuration; capture saved but not committed")
        if signing.returncode == 0 and signing.stdout.strip() == b"true":
            options.append("-S")
        result = git("commit-tree", expected_tree.decode(), *options, "-F", message_path, env=env, check=False)
        if result.returncode:
            raise Invalid("capture saved but commit failed; check Git identity/signing and rerun --capture (output suppressed)")
        commit_id = result.stdout.decode().strip()
        if head() != revision or capture_branch() != branch:
            raise Invalid("Git HEAD/branch changed while creating the commit; no branch was updated")
        check_git_operation()
        # Compare-and-swap: an external commit must not be overwritten.
        git("update-ref", "-m", message, branch, commit_id, revision or "")
        say("  OK  " + commit_id[:12] + "  " + message)
        try:
            git("reset", "--quiet", commit_id, "--", *REL)
        except Invalid:
            raise Invalid("capture was committed, but the real index could not be synchronized; inspect git status locally") from None
        try:
            run_hook("post-commit", env)
        except Invalid:
            say("codex-apply: commit succeeded, but post-commit failed (output suppressed)")
    finally:
        for path in (Path(index), Path(index + ".lock"), Path(message_path)):
            path.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    capture = "--capture" in sys.argv[1:]
    if any(os.environ.get(key) for key in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")):
        raise Invalid("unset Git repository/index override variables before running codex-apply")
    if Path(git("rev-parse", "--show-toplevel").stdout.decode().strip()) != REPO:
        raise Invalid("codex-apply must live at the root of its own Git repository")
    home = Path(os.environ.get("CODEX_HOME") or str(Path.home() / ".codex"))
    state_base = Path(os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")) / "codex-apply"
    if not home.is_absolute() or not state_base.is_absolute():
        raise Invalid("CODEX_HOME and XDG_STATE_HOME must be absolute paths")
    home = Path(os.path.abspath(home))
    repo_config = REPO / "scripts/codex-apply/config"
    for directory in (home, state_base):
        if directory.resolve().is_relative_to(REPO):
            raise Invalid("generated config/state must be outside the repository")
        # Check ancestors without rejecting a directory itself.
        safe_path(directory / ".path-check")
    if state_base.resolve().is_relative_to(home.resolve()) or home.resolve().is_relative_to(state_base.resolve()):
        raise Invalid("configuration and backup directories must not overlap")
    target_id = hashlib.sha256(str(home).encode()).hexdigest()[:16]
    repo_id = hashlib.sha256(str(REPO).encode()).hexdigest()[:16]
    state = state_base / target_id
    with lock(state_base / ("repo-" + repo_id + ".lock")), lock(state / "operation.lock"):
        pending = state / "pending.json"
        if pending.exists():
            raise Invalid("unfinished operation; inspect recovery file: " + quoted(pending))
        revision = head()
        number = version()
        source_dir, target_dir = (home, repo_config) if capture else (repo_config, home)
        source = checked_files(source_dir, required=True)
        before = checked_files(target_dir, required=False)
        desired = {name: contents(source[name]) for name in NAMES}
        old = {name: contents(before[name]) for name in NAMES}
        branch = capture_branch() if capture else None
        if capture:
            old = check_capture(revision, desired, before)
        changed = any(old[name] != desired[name] for name in NAMES)
        if not changed and all(contents(before[name]) == desired[name] for name in NAMES):
            say("変更はありません。")
            return
        next_number = number + 1 if capture else number
        previous_label = f"v{number:04d}" if number else "unversioned"
        label = f"{previous_label} → v{next_number:04d}" if capture else previous_label
        if not capture and (git("ls-files", "--error-unmatch", "--", *REL, check=False).returncode
                            or git("diff", "--quiet", "HEAD", "--", *REL, check=False).returncode):
            label = "working tree (base: " + label + ")"
        preview(source_dir, target_dir, old, desired, label, next_number, capture)
        if not confirm(capture):
            return
        if checked_files(source_dir, required=True) != source or checked_files(target_dir, required=False) != before or head() != revision:
            raise Invalid("files or Git HEAD changed during confirmation; retry")
        if capture:
            if capture_branch() != branch:
                raise Invalid("Git branch changed during confirmation; retry")
            check_capture(revision, desired, before)
            replace_files(target_dir, desired, before, pending)
            if changed:
                commit_capture(f"{VERSION_PREFIX}{next_number:04d}", revision, desired, state, branch)
            say("取り込みが完了しました。")
        else:
            backup = state / "backup.json"
            replace_files(target_dir, desired, before, pending, backup)
            say("適用が完了しました。\n  Backup  " + quoted(backup))


if __name__ == "__main__":
    try:
        main()
    except (Invalid, OSError, UnicodeError) as error:
        if isinstance(error, Invalid):
            message = str(error)
        elif isinstance(error, OSError):
            message = "file operation failed (" + errno.errorcode.get(error.errno, "unknown") + "); check paths, permissions and disk space"
        else:
            message = "invalid UTF-8 (contents suppressed)"
        say("codex-apply: " + message)
        sys.exit(1)
    except KeyboardInterrupt:
        say("codex-apply: interrupted; inspect any recovery message above")
        sys.exit(130)
