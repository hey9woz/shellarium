"""Hermetic tests: disposable repositories/HOMEs, pseudo terminals, no secrets/network."""
import base64
import fcntl
import json
import os
from pathlib import Path
import pty
import shutil
import select
import subprocess
import sys
import tempfile
import termios
import tomllib
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import validate
import manage

CONFIG = b'model = "example-model"\nmodel_reasoning_effort = "high"\n'
AGENTS = '# 作業方針\n- 日本語で説明する。\n'.encode()


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-apply-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo with spaces"
        self.repo.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()
        self.codex = self.home / ".codex"
        self.codex.mkdir()
        (self.codex / "config.toml").write_bytes(CONFIG)
        (self.codex / "AGENTS.md").write_bytes(AGENTS)
        self.source = self.repo / "scripts/codex-apply"
        self.source.mkdir(parents=True)
        (self.source / "config").mkdir()
        for name in ("manage.py", "validate.py"):
            shutil.copyfile(HERE / name, self.source / name)
        (self.repo / "bin").mkdir()
        shutil.copyfile(HERE.parents[1] / "bin/codex-apply", self.repo / "bin/codex-apply")
        (self.repo / "bin/codex-apply").chmod(0o755)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "LANG": "C.UTF-8",
                    "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1", "TERM": "dumb"}
        self.git("init", "-q")
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.invalid")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.command = self.repo / "bin/codex-apply"

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", str(self.repo), *args], env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)

    def cli(self, *args, answer=None, success=True, before_confirm=None):
        if answer is None:
            result = subprocess.run([str(self.command), *args], env=self.env, cwd="/",
                                    capture_output=True, text=True)
        else:
            master, slave = pty.openpty()
            try:
                with subprocess.Popen([str(self.command), *args], env=self.env, cwd="/", stdin=slave,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
                    os.close(slave)
                    slave = None
                    prefix = b""
                    if before_confirm:
                        while not prefix.endswith(b"[y/N] "):
                            ready, _, _ = select.select([process.stderr], [], [], 10)
                            if not ready:
                                process.kill()
                                process.communicate()
                                self.fail("confirmation prompt timed out: " + repr(prefix))
                            chunk = os.read(process.stderr.fileno(), 1)
                            self.assertTrue(chunk, prefix.decode(errors="replace"))
                            prefix += chunk
                        before_confirm()
                    os.write(master, answer.encode())
                    out, err = process.communicate(timeout=15)
                    err = prefix.decode() + err
                    result = subprocess.CompletedProcess(process.args, process.returncode, out, err)
            finally:
                os.close(master)
                if slave is not None:
                    os.close(slave)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def capture(self):
        return self.cli("--capture", answer="y\n")

    def backups(self):
        return list(self.home.rglob("backup.json"))

    def test_capture_numbering_isolation_and_noop(self):
        (self.repo / "unrelated").write_text("staged unrelated")
        self.git("add", "unrelated")
        result = self.capture()
        self.assertIn("capture v0001", result.stderr)
        changed = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.decode().splitlines()
        self.assertEqual(set(changed), {"scripts/codex-apply/config/config.toml", "scripts/codex-apply/config/AGENTS.md"})
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout.decode().strip(), "unrelated")
        previous = self.git("rev-parse", "HEAD").stdout
        self.assertIn("変更はありません", self.cli("--capture").stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, previous)
        (self.codex / "AGENTS.md").write_bytes(AGENTS + b'\n- Run checks.\n')
        self.assertIn("capture v0002", self.capture().stderr)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout.decode().strip(), "unrelated")

    def test_apply_backup_rotation_and_noop(self):
        self.capture()
        old = b'model = "old-model"\n'
        (self.codex / "config.toml").write_bytes(old)
        self.cli(answer="y\n")
        self.assertEqual((self.codex / "config.toml").read_bytes(), CONFIG)
        backup = self.backups()[0]
        before = backup.read_bytes()
        data = json.loads(before)
        self.assertEqual(base64.b64decode(data["files"]["config.toml"]["content"]), old)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.cli()
        self.assertEqual(backup.read_bytes(), before)
        newer = b'model = "newer-local"\n'
        (self.codex / "config.toml").write_bytes(newer)
        self.cli(answer="yes\n")
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(base64.b64decode(json.loads(backup.read_bytes())["files"]["config.toml"]["content"]), newer)
        self.assertEqual((self.codex / "config.toml").stat().st_mode & 0o777, 0o600)

    def test_first_apply_missing_targets_records_absence(self):
        self.capture()
        self.env["CODEX_HOME"] = str(self.home / "new codex")
        self.cli(answer="y\n")
        self.assertEqual((self.home / "new codex/config.toml").read_bytes(), CONFIG)
        self.assertTrue(all(v is None for v in json.loads(self.backups()[0].read_bytes())["files"].values()))

    def test_confirmation_cancel_noninteractive_and_unknown_option(self):
        for answer in ("\n", "n\n"):
            self.cli("--capture", answer=answer)
            self.assertFalse((self.source / "config/config.toml").exists())
        self.assertIn("requires a terminal", self.cli("--capture", success=False).stderr)
        self.cli("--dry-run", success=False)
        self.cli("--capture", "extra", success=False)
        self.cli("--help")

    def test_only_documented_dependencies_are_needed(self):
        command_dir = self.base / "commands"
        command_dir.mkdir()
        for name in ("bash", "python3", "git", "dirname"):
            (command_dir / name).symlink_to(shutil.which(name))
        self.env["PATH"] = str(command_dir)
        self.capture()
        (command_dir / "git").unlink()
        self.assertIn("missing dependency: git", self.cli(success=False).stderr)

    def test_missing_source_files_and_symlinks(self):
        self.assertIn("missing file", self.cli(success=False).stderr)
        target = self.codex / "config.toml"
        target.unlink()
        target.symlink_to(self.base / "elsewhere")
        self.assertIn("symbolic links", self.cli("--capture", success=False).stderr)

    def test_secret_rejected_before_diff_write_and_commit(self):
        previous = self.git("rev-parse", "HEAD").stdout
        (self.codex / "config.toml").write_text('[mcp_servers.x.env]\nAPI_KEY="NEVER_PRINT_THIS_VALUE"\n')
        result = self.cli("--capture", answer="y\n", success=False)
        self.assertNotIn("NEVER_PRINT_THIS_VALUE", result.stdout + result.stderr)
        self.assertNotIn("---", result.stdout)
        self.assertEqual(previous, self.git("rev-parse", "HEAD").stdout)
        self.assertFalse((self.source / "config/config.toml").exists())

    def test_existing_destination_secret_is_not_shown_in_diff(self):
        self.capture()
        (self.codex / "AGENTS.md").write_text('password = NEVER_PRINT_THIS_VALUE\n')
        result = self.cli(answer="y\n", success=False)
        self.assertNotIn("NEVER_PRINT_THIS_VALUE", result.stdout + result.stderr)
        self.assertFalse(self.backups())

    def test_commit_failure_retry_preserves_index(self):
        (self.repo / "unrelated").write_text("unrelated")
        self.git("add", "unrelated")
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        previous = self.git("rev-parse", "HEAD").stdout
        self.assertIn("commit failed", self.cli("--capture", answer="y\n", success=False).stderr)
        self.assertEqual(previous, self.git("rev-parse", "HEAD").stdout)
        self.assertEqual((self.source / "config/config.toml").read_bytes(), CONFIG)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout.decode().strip(), "unrelated")
        hook.unlink()
        self.assertIn("capture v0001", self.capture().stderr)

    def test_managed_staged_files_and_dirty_worktree_are_preserved(self):
        self.capture()
        file = self.source / "config/AGENTS.md"
        file.write_text("independent edits\n")
        self.assertIn("uncommitted edits", self.cli("--capture", success=False).stderr)
        self.git("add", str(file))
        self.assertIn("staged", self.cli("--capture", success=False).stderr)
        self.assertEqual(file.read_text(), "independent edits\n")

    def test_interrupted_state_and_lock_block_changes(self):
        self.capture()
        state = self.home / ".local/state/codex-apply"
        locks = list(state.glob("*/operation.lock"))
        with locks[0].open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn("another codex-apply", self.cli(success=False).stderr)
        pending = locks[0].parent / "pending.json"
        pending.write_text("recovery state")
        self.assertIn("unfinished operation", self.cli(success=False).stderr)
        self.assertEqual(pending.read_text(), "recovery state")

    def test_changes_during_confirmation_stop_without_capture(self):
        def edit_source():
            (self.codex / "AGENTS.md").write_bytes(AGENTS + b"changed while prompting\n")
        result = self.cli("--capture", answer="y\n", success=False, before_confirm=edit_source)
        self.assertIn("changed during confirmation", result.stderr)
        self.assertFalse((self.source / "config/config.toml").exists())

    def test_apply_symlink_state_and_invalid_paths_are_rejected(self):
        self.capture()
        alternate = self.base / "linked codex"
        alternate.symlink_to(self.codex, target_is_directory=True)
        self.env["CODEX_HOME"] = str(alternate)
        self.assertIn("symbolic links", self.cli(success=False).stderr)
        self.env["CODEX_HOME"] = "relative"
        self.assertIn("absolute", self.cli(success=False).stderr)
        self.env["CODEX_HOME"] = str(self.repo / "local")
        self.assertIn("outside the repository", self.cli(success=False).stderr)

    def test_capture_rejects_git_filters_and_keeps_uncommitted_files(self):
        (self.repo / ".gitattributes").write_text("scripts/codex-apply/config/* filter=alter\n")
        self.git("config", "filter.alter.clean", "sed s/example-model/filtered-model/g")
        result = self.cli("--capture", answer="y\n", success=False)
        self.assertIn("filter changed", result.stderr)
        self.assertEqual((self.source / "config/config.toml").read_bytes(), CONFIG)
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.decode().strip(), "baseline")

    def test_real_merge_in_progress_is_preserved(self):
        branch = self.git("branch", "--show-current").stdout.decode().strip()
        self.git("checkout", "-qb", "topic")
        (self.repo / "merged-file").write_text("topic change")
        self.git("add", "merged-file")
        self.git("commit", "-qm", "topic change")
        self.git("checkout", "-q", branch)
        self.git("merge", "--no-ff", "--no-commit", "topic")
        previous = self.git("rev-parse", "HEAD").stdout
        merge_head = (self.repo / ".git/MERGE_HEAD").read_bytes()
        index = (self.repo / ".git/index").read_bytes()
        result = self.cli("--capture", success=False)
        self.assertIn("in-progress Git operation", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, previous)
        self.assertEqual((self.repo / ".git/MERGE_HEAD").read_bytes(), merge_head)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertFalse((self.source / "config/config.toml").exists())

    def test_other_git_operation_markers_are_rejected(self):
        for marker in ("CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
            with self.subTest(marker=marker):
                path = self.repo / ".git" / marker
                path.write_text("in progress")
                try:
                    self.assertIn("in-progress", self.cli("--capture", success=False).stderr)
                finally:
                    path.unlink()

    def test_hook_cannot_commit_unrelated_staged_files(self):
        (self.repo / "unrelated").write_text("unrelated")
        self.git("add", "unrelated")
        previous = self.git("rev-parse", "HEAD").stdout
        index = (self.repo / ".git/index").read_bytes()
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\ngit add -- unrelated\n")
        hook.chmod(0o755)
        result = self.cli("--capture", answer="y\n", success=False)
        self.assertIn("hook changed the reviewed index", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, previous)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)

    def test_hook_cannot_commit_unvalidated_config_or_change_message(self):
        previous = self.git("rev-parse", "HEAD").stdout
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nprintf 'password = NEVER_PRINT_OR_COMMIT' > scripts/codex-apply/config/AGENTS.md\ngit add -- scripts/codex-apply/config/AGENTS.md\n")
        hook.chmod(0o755)
        result = self.cli("--capture", answer="y\n", success=False)
        self.assertNotIn("NEVER_PRINT_OR_COMMIT", result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, previous)
        hook.unlink()
        (self.source / "config/AGENTS.md").write_bytes(AGENTS)
        message_hook = self.repo / ".git/hooks/commit-msg"
        message_hook.write_text('#!/bin/sh\nprintf "changed subject\n" > "$1"\n')
        message_hook.chmod(0o755)
        result = self.cli("--capture", answer="y\n", success=False)
        self.assertIn("fixed version message", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, previous)

    def test_nonmutating_hooks_and_custom_hooks_path_are_supported(self):
        hooks = self.repo / "custom-hooks"
        hooks.mkdir()
        self.git("config", "core.hooksPath", "custom-hooks")
        for name in ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit"):
            hook = hooks / name
            hook.write_text('#!/bin/sh\ntest -n "$GIT_INDEX_FILE" || exit 1\nprintf "called\n" >> "' + str(self.base / name) + '"\n')
            hook.chmod(0o755)
        self.capture()
        for name in ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit"):
            self.assertEqual((self.base / name).read_text(), "called\n")
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.decode().strip(), "chore(codex-apply): capture v0001")

    def test_external_commit_during_hooks_is_not_overwritten(self):
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text('#!/bin/sh\nunset GIT_INDEX_FILE\ngit -c core.hooksPath=/dev/null commit --allow-empty -qm "external commit"\n')
        hook.chmod(0o755)
        result = self.cli("--capture", answer="y\n", success=False)
        self.assertIn("HEAD/branch changed", result.stderr)
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.decode().strip(), "external commit")
        self.assertNotIn(b"scripts/codex-apply/config/", self.git("ls-tree", "-r", "--name-only", "HEAD").stdout)

    def test_argument_credentials_are_rejected_before_preview(self):
        for arguments in ('["https://user:pass@example.invalid/mcp"]',
                          '["--url=https://example.invalid/mcp?key=demo"]',
                          '["--key", "demo"]', '["--auth=demo"]', '["--credentials", "demo"]',
                          '["HTTPS://user:pass@example.invalid"]', '["postgresql://user:pass@example.invalid/db"]',
                          '["--user", "alice:demo"]', '["--eval=code"]', '["-ecode"]'):
            with self.subTest(arguments=arguments):
                content = '[mcp_servers.x]\ncommand="server"\nargs=' + arguments + '\n'
                (self.codex / "config.toml").write_text(content)
                previous = self.git("rev-parse", "HEAD").stdout
                result = self.cli("--capture", success=False)
                self.assertNotIn("---", result.stdout)
                self.assertEqual(self.git("rev-parse", "HEAD").stdout, previous)
                self.assertFalse((self.source / "config/config.toml").exists())

    def test_compare_and_swap_preserves_external_commit(self):
        desired = {"config.toml": CONFIG, "AGENTS.md": AGENTS}
        for name, content in desired.items():
            (self.source / "config" / name).write_bytes(content)
        revision = self.git("rev-parse", "HEAD").stdout.decode().strip()
        branch = self.git("symbolic-ref", "HEAD").stdout.decode().strip()
        state = self.base / "state"
        state.mkdir()
        original_git = manage.git
        def concurrent_git(*args, **kwargs):
            if args[0] == "update-ref":
                self.git("commit", "--allow-empty", "-qm", "external commit before CAS")
            return original_git(*args, **kwargs)
        with patch.object(manage, "REPO", self.repo), patch.dict(os.environ, self.env, clear=True):
            with patch.object(manage, "git", side_effect=concurrent_git):
                with self.assertRaises(validate.Invalid):
                    manage.commit_capture("chore(codex-apply): capture v0001", revision, desired, state, branch)
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.decode().strip(), "external commit before CAS")
        self.assertNotIn(b"scripts/codex-apply/config/", self.git("ls-tree", "-r", "--name-only", "HEAD").stdout)
        self.assertFalse(list(state.iterdir()))

    def test_invalid_signing_configuration_does_not_create_commit(self):
        previous = self.git("rev-parse", "HEAD").stdout
        self.git("config", "commit.gpgsign", "invalid-boolean")
        result = self.cli("--capture", answer="y\n", success=False)
        self.assertIn("invalid commit.gpgsign", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, previous)

    def test_capture_includes_separate_profiles_and_only_managed_files(self):
        for name in ("careful", "daily", "review"):
            (self.codex / (name + ".config.toml")).write_text('model_reasoning_effort="high"\n[mcp_servers.http]\nurl="https://example.invalid/mcp"\nenv_http_headers={"X-API-Key"="API_KEY"}\n')
        (self.codex / "daily.config.toml").write_text('model="daily-model"\n[projects."/private/local"]\ntrust_level="trusted"\n')
        (self.repo / "unrelated").write_text("unrelated")
        self.git("add", "unrelated")
        self.capture()
        paths = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.decode().splitlines()
        expected = {"scripts/codex-apply/config/" + name for name in (*manage.NAMES, "careful.config.toml", "daily.config.toml", "review.config.toml")}
        self.assertEqual(set(paths), expected)
        daily = tomllib.loads((self.source / "config/daily.config.toml").read_text())
        self.assertNotIn("projects", daily)
        self.assertIn("projects", tomllib.loads((self.codex / "daily.config.toml").read_text()))
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout.decode().strip(), "unrelated")

    def test_apply_adds_updates_deletes_profiles_and_backs_up_all(self):
        (self.codex / "daily.config.toml").write_text('model="daily-model"\n')
        (self.codex / "review.config.toml").write_text('model="review-model"\n')
        self.capture()
        (self.codex / "review.config.toml").unlink()
        (self.codex / "daily.config.toml").write_text('model="old-model"\n[projects."/private/destination"]\ntrust_level="trusted"\n')
        stale = self.codex / "stale.config.toml"
        stale.write_text('model="stale-model"\n')
        result = self.cli(answer="y\n")
        self.assertIn("DELETE", result.stderr)
        self.assertFalse(stale.exists())
        self.assertTrue((self.codex / "review.config.toml").exists())
        daily = tomllib.loads((self.codex / "daily.config.toml").read_text())
        self.assertEqual(daily["model"], "daily-model")
        self.assertEqual(daily["projects"], {"/private/destination": {"trust_level": "trusted"}})
        records = json.loads(self.backups()[0].read_bytes())["files"]
        self.assertEqual(base64.b64decode(records["stale.config.toml"]["content"]), b'model="stale-model"\n')
        self.assertIsNone(records["review.config.toml"])
        backup = self.backups()[0].read_bytes()
        self.assertIn("変更はありません", self.cli().stderr)
        self.assertEqual(self.backups()[0].read_bytes(), backup)

    def test_capture_profile_deletion_retries_failed_commit(self):
        profile = self.codex / "daily.config.toml"
        profile.write_text('model="daily-model"\n')
        self.capture()
        profile.unlink()
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        result = self.cli("--capture", answer="y\n", success=False)
        self.assertIn("commit failed", result.stderr)
        self.assertFalse((self.source / "config/daily.config.toml").exists())
        hook.unlink()
        result = self.capture()
        self.assertIn("capture v0002", result.stderr)
        paths = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.decode().splitlines()
        self.assertEqual(paths, ["scripts/codex-apply/config/daily.config.toml"])
        self.assertFalse(self.git("status", "--porcelain").stdout)
        self.assertIn("変更はありません", self.cli("--capture").stderr)

    def test_profile_deletion_is_cancelled_without_writes(self):
        self.capture()
        stale = self.codex / "stale.config.toml"
        stale.write_text('model="stale-model"\n')
        result = self.cli(answer="n\n")
        self.assertIn("DELETE", result.stderr)
        self.assertEqual(stale.read_text(), 'model="stale-model"\n')
        self.assertFalse(self.backups())

    def test_profile_list_change_during_confirmation_stops_capture(self):
        def new_profile():
            (self.codex / "new.config.toml").write_text('model="new-model"\n')
        result = self.cli("--capture", answer="y\n", success=False, before_confirm=new_profile)
        self.assertIn("changed during confirmation", result.stderr)
        self.assertFalse((self.source / "config/config.toml").exists())

    def test_invalid_secret_and_symlink_profiles_are_rejected(self):
        profile = self.codex / "daily.config.toml"
        for content in ('invalid = [', '[mcp_servers.x.env]\nAPI_KEY="NEVER_PRINT_THIS_VALUE"\n'):
            profile.write_text(content)
            result = self.cli("--capture", success=False)
            self.assertNotIn("NEVER_PRINT_THIS_VALUE", result.stdout + result.stderr)
            self.assertNotIn("---", result.stdout)
            self.assertFalse((self.source / "config/config.toml").exists())
        profile.unlink()
        profile.symlink_to(self.base / "missing-profile")
        self.assertIn("symbolic links", self.cli("--capture", success=False).stderr)

    def test_capture_excludes_projects_and_accepts_generated_tui_settings(self):
        content = CONFIG + b'\n[tui]\nscreen_reader_detection_done=true\n[tui.model_availability_nux]\nexample=123\n[projects."/private/machine-one"]\ntrust_level="trusted"\n'
        (self.codex / "config.toml").write_bytes(content)
        result = self.capture()
        shared = tomllib.loads((self.source / "config/config.toml").read_text())
        self.assertNotIn("projects", shared)
        self.assertTrue(shared["tui"]["screen_reader_detection_done"])
        self.assertEqual(shared["tui"]["model_availability_nux"]["example"], 123)
        self.assertEqual((self.codex / "config.toml").read_bytes(), content)
        self.assertNotIn("/private/machine-one", result.stdout + result.stderr)

    def test_capture_migrates_committed_projects_in_base_and_profile(self):
        names = ("config.toml", "daily.config.toml")
        legacy = CONFIG + b'\n[projects."/legacy/shared"]\ntrust_level="trusted"\n'
        local = CONFIG + b'\n[projects."/local/current"]\ntrust_level="untrusted"\n'
        for name in names:
            (self.source / "config" / name).write_bytes(legacy)
            (self.codex / name).write_bytes(local)
        (self.source / "config/AGENTS.md").write_bytes(AGENTS)
        self.git("add", "scripts/codex-apply/config")
        self.git("commit", "-qm", "legacy shared projects")
        previous = self.git("rev-parse", "HEAD").stdout
        self.assertIn("projects", self.cli(success=False).stderr)
        self.cli("--capture", answer="n\n")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, previous)
        for name in names:
            self.assertEqual((self.source / "config" / name).read_bytes(), legacy)
        result = self.capture()
        self.assertIn("capture v0001", result.stderr)
        self.assertIn("/legacy/shared", result.stdout)
        for name in names:
            shared = (self.source / "config" / name).read_bytes()
            self.assertNotIn("projects", tomllib.loads(shared.decode()))
            self.assertEqual(self.git("show", "HEAD:scripts/codex-apply/config/" + name).stdout, shared)
            self.assertEqual((self.codex / name).read_bytes(), local)
        self.assertEqual(self.git("show", "HEAD^:scripts/codex-apply/config/config.toml").stdout, legacy)
        self.assertIn("変更はありません", self.cli("--capture").stderr)
        self.cli(answer="y\n")
        for name in names:
            self.assertEqual(tomllib.loads((self.codex / name).read_text())["projects"],
                             {"/local/current": {"trust_level": "untrusted"}})

    def test_capture_migrates_legacy_head_after_working_copy_is_sanitized(self):
        legacy = CONFIG + b'\n[projects."/legacy/shared"]\ntrust_level="trusted"\n'
        shared = self.source / "config/config.toml"
        shared.write_bytes(legacy)
        (self.source / "config/AGENTS.md").write_bytes(AGENTS)
        self.git("add", "scripts/codex-apply/config")
        self.git("commit", "-qm", "legacy shared projects")
        shared.write_bytes(CONFIG)
        self.assertIn("capture v0001", self.capture().stderr)
        self.assertEqual(self.git("show", "HEAD:scripts/codex-apply/config/config.toml").stdout, CONFIG)
        self.assertFalse(self.git("status", "--porcelain").stdout)

    def test_projects_migration_still_rejects_secrets_in_existing_settings(self):
        shared = self.source / "config/config.toml"
        secret = CONFIG + b'\n[projects."/legacy/shared"]\ntrust_level="trusted"\n# API_KEY=NEVER_PRINT_THIS_VALUE\n'
        (self.source / "config/AGENTS.md").write_bytes(AGENTS)
        for location in ("working copy", "committed baseline"):
            with self.subTest(location=location):
                shared.write_bytes(secret)
                if location == "committed baseline":
                    self.git("add", "scripts/codex-apply/config")
                    self.git("commit", "-qm", "invalid legacy fixture")
                    shared.write_bytes(CONFIG)
                previous = self.git("rev-parse", "HEAD").stdout
                before = shared.read_bytes()
                result = self.cli("--capture", success=False)
                self.assertNotIn("NEVER_PRINT_THIS_VALUE", result.stdout + result.stderr)
                self.assertNotIn("---", result.stdout)
                self.assertEqual(shared.read_bytes(), before)
                self.assertEqual(self.git("rev-parse", "HEAD").stdout, previous)

    def test_apply_preserves_destination_projects_and_roundtrip_is_noop(self):
        first = CONFIG + b'\n[projects."/private/machine-one"]\ntrust_level="trusted"\n'
        (self.codex / "config.toml").write_bytes(first)
        self.capture()
        revision = self.git("rev-parse", "HEAD").stdout
        second = b'model="old-model"\nprojects={"/private/machine-two"={trust_level="untrusted"}}\n'
        (self.codex / "config.toml").write_bytes(second)
        self.cli(answer="y\n")
        applied = tomllib.loads((self.codex / "config.toml").read_text())
        self.assertEqual(applied["model"], "example-model")
        self.assertEqual(applied["projects"], {"/private/machine-two": {"trust_level": "untrusted"}})
        self.assertNotIn("/private/machine-one", (self.codex / "config.toml").read_text())
        backup = self.backups()[0].read_bytes()
        self.assertIn("変更はありません", self.cli().stderr)
        self.assertEqual(self.backups()[0].read_bytes(), backup)
        self.assertIn("変更はありません", self.cli("--capture").stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, revision)

    def test_project_exclusion_does_not_hide_credentials(self):
        (self.codex / "config.toml").write_bytes(CONFIG + b'\n[projects."/private/machine"]\ntrust_level="trusted"\n# API_KEY=NEVER_PRINT_THIS_VALUE\n')
        result = self.cli("--capture", success=False)
        self.assertNotIn("NEVER_PRINT_THIS_VALUE", result.stdout + result.stderr)
        self.assertFalse((self.source / "config/config.toml").exists())

    def test_valid_mcp_references_and_profiles_are_captured(self):
        config = CONFIG + b'''\n[profiles.work]
model = "work-model"
[mcp_servers.stdio]
command = "example-mcp-server"
env_vars = ["API_KEY", {name="REMOTE_TOKEN", source="remote"}]
[mcp_servers.http]
url = "https://example.invalid/mcp"
bearer_token_env_var = "HTTP_TOKEN"
env_http_headers = {"X-API-Key"="OTHER_TOKEN"}
[mcp_servers.public]
url = "https://example.invalid/public"
'''
        (self.codex / "config.toml").write_bytes(config)
        self.capture()
        self.assertEqual((self.source / "config/config.toml").read_bytes(), config)
        self.assertNotIn("OP_SESSION", self.env)


class PolicyAndRecoveryTests(unittest.TestCase):
    def test_literal_credentials_urls_shells_and_unknowns_rejected(self):
        cases = [b'[mcp_servers.x.env]\nTOKEN="value"', b'[mcp_servers.x.http_headers]\nX="value"',
                 b'[mcp_servers.x.oauth]\nclient_secret="value"',
                 b'[mcp_servers.x]\nurl="https://user:pass@example.invalid"',
                 b'[mcp_servers.x]\nurl="https://example.invalid?token=value"',
                 b'[mcp_servers.x]\ncommand="bash"\nargs=["-c", "something"]',
                 b'[mcp_servers.x]\ncommand="test"\nargs=["--api-key", "value"]',
                 b'[mcp_servers.x]\nenv_vars=["${TOKEN}"]', b'unknown="value"',
                 b'[projects."/home/name/project"]\ntrust_level="trusted"',
                 b'[mcp_servers.x]\ncwd="/home/name"', b'invalid = [',
                 b'[mcp_servers.x]\nenv_vars=[{name="TOKEN",source=[]}]']
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(validate.Invalid):
                    validate.validate("config.toml", text)

    def test_markdown_secrets_and_terminal_controls_rejected(self):
        for text in (b'-----BEGIN PRIVATE KEY-----', b'password: value',
                     b'sk-' + b'a' * 20, b'hello\x1b[2J', b'\xff', b'TOKEN=opaque', b'{"password":"opaque"}', b'hello\rspoof'):
            with self.subTest(text=text):
                with self.assertRaises(validate.Invalid):
                    validate.validate("AGENTS.md", text)

    def test_tui_settings_and_keymap_are_validated(self):
        content = b'[tui]\nnotifications=["event"]\nanimations=false\nstatus_line_use_colors=true\ntheme="example"\n[tui.keymap.composer]\nsubmit=["ctrl-enter"]\n'
        validate.validate("config.toml", content)
        for bad in (b'[tui]\nanimations="invalid"', b'[tui]\nstatus_line_use_colors="invalid"', b'[tui]\nunknown=true',
                    b'[tui.keymap.composer]\nsubmit=123', b'[tui.model_availability_nux]\nexample="invalid"'):
            with self.subTest(bad=bad):
                with self.assertRaises(validate.Invalid):
                    validate.validate("config.toml", bad)

    def test_project_projection_uses_parsed_toml_and_preserves_values(self):
        original = b'# local comment\nmodel="example"\nprojects={"/private/project"={trust_level="trusted"}}\n[mcp_servers.x]\ncommand="server"\nenv_vars=[{name="API_KEY",source="local"}]\n'
        validate.validate("config.toml", original, allow_projects=True)
        portable = manage.portable_config(original)
        validate.validate("config.toml", portable)
        shared = tomllib.loads(portable.decode())
        self.assertNotIn("projects", shared)
        self.assertEqual(shared["mcp_servers"]["x"]["env_vars"], [{"name":"API_KEY", "source":"local"}])
        result = manage.preserve_projects(portable, original)
        self.assertEqual(tomllib.loads(result.decode()), tomllib.loads(original.decode()))
        self.assertEqual(manage.portable_config(result), portable)
        with self.assertRaises(validate.Invalid):
            validate.validate("config.toml", original)

    def test_readme_restore_example_works_with_a_controlling_tty(self):
        document = (HERE / "README.md").read_text()
        script = document.split("python3 - /exact/path/to/backup.json <<'PY'\n", 1)[1].split("\nPY", 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            directory = base / "target"
            directory.mkdir()
            before = {"config.toml": (b"original", 0o640), "AGENTS.md": None,
                      "daily.config.toml": (b"old-profile", 0o600), "careful.config.toml": None}
            record = base / "backup.json"
            record.write_bytes(manage.payload(directory, before))
            (directory / "config.toml").write_bytes(b"replacement")
            (directory / "AGENTS.md").write_bytes(b"new file")
            (directory / "daily.config.toml").write_bytes(b"new-profile")
            (directory / "careful.config.toml").write_bytes(b"new-file")
            master, slave = pty.openpty()
            def terminal():
                os.setsid()
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            try:
                with subprocess.Popen([sys.executable, "-", str(record)], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                      preexec_fn=terminal, pass_fds=(slave,)) as process:
                    os.write(master, b"y\n")
                    try:
                        out, err = process.communicate(script, timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                        raise
                    self.assertEqual(process.returncode, 0, out + err)
            finally:
                os.close(master)
                os.close(slave)
            self.assertEqual((directory / "config.toml").read_bytes(), b"original")
            self.assertEqual((directory / "config.toml").stat().st_mode & 0o777, 0o640)
            self.assertFalse((directory / "AGENTS.md").exists())
            self.assertEqual((directory / "daily.config.toml").read_bytes(), b"old-profile")
            self.assertFalse((directory / "careful.config.toml").exists())

    def test_profile_deletion_is_rolled_back_if_later_write_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            directory = base / "target"
            directory.mkdir()
            (directory / "daily.config.toml").write_bytes(b'model="original"')
            before = {name: manage.snapshot(directory / name) for name in ("daily.config.toml", "review.config.toml")}
            pending, backup = base / "pending.json", base / "backup.json"
            backup.write_bytes(b"previous-generation")
            original = manage.atomic
            def fail_review(path, data, mode=0o600):
                if path == directory / "review.config.toml":
                    raise OSError(28, "disk full")
                return original(path, data, mode)
            with patch.object(manage, "atomic", side_effect=fail_review):
                with self.assertRaises(OSError):
                    manage.replace_files(directory, {"daily.config.toml": None, "review.config.toml": CONFIG}, before, pending, backup)
            self.assertEqual((directory / "daily.config.toml").read_bytes(), b'model="original"')
            self.assertFalse((directory / "review.config.toml").exists())
            self.assertFalse(pending.exists())
            self.assertEqual(backup.read_bytes(), b"previous-generation")

    def test_failed_rollback_keeps_recovery_data(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            directory = base / "target"
            directory.mkdir()
            (directory / "config.toml").write_bytes(b"original")
            before = {name: manage.snapshot(directory / name) for name in manage.NAMES}
            pending, backup = base / "pending.json", base / "backup.json"
            backup.write_bytes(b"previous-generation")
            original_atomic = manage.atomic

            def fail_apply_and_rollback(path, data, mode=0o600):
                if path == directory / "AGENTS.md" or data == b"original":
                    raise OSError(28, "disk full")
                return original_atomic(path, data, mode)

            with patch.object(manage, "atomic", side_effect=fail_apply_and_rollback):
                with self.assertRaises(OSError):
                    manage.replace_files(directory, {"config.toml": CONFIG, "AGENTS.md": AGENTS}, before, pending, backup)
            self.assertTrue(pending.exists())
            self.assertEqual(base64.b64decode(json.loads(pending.read_bytes())["files"]["config.toml"]["content"]), b"original")
            self.assertEqual(backup.read_bytes(), b"previous-generation")

    def test_failed_apply_rolls_back_both_files_and_preserves_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            directory = base / "target"
            directory.mkdir()
            (directory / "config.toml").write_bytes(b'old')
            (directory / "config.toml").chmod(0o640)
            before = {name: manage.snapshot(directory / name) for name in manage.NAMES}
            pending, backup = base / "pending.json", base / "backup.json"
            backup.write_bytes(b'previous-generation')
            original = manage.atomic
            failed = False

            def fail_second(path, data, mode=0o600):
                nonlocal failed
                if path == directory / "AGENTS.md" and not failed:
                    failed = True
                    raise OSError(28, "disk full")
                return original(path, data, mode)

            with patch.object(manage, "atomic", side_effect=fail_second):
                with self.assertRaises(OSError):
                    manage.replace_files(directory, {"config.toml": CONFIG, "AGENTS.md": AGENTS}, before, pending, backup)
            self.assertEqual(manage.snapshot(directory / "config.toml"), before["config.toml"])
            self.assertFalse((directory / "AGENTS.md").exists())
            self.assertEqual(backup.read_bytes(), b'previous-generation')
            self.assertFalse(pending.exists())
            self.assertFalse(list(directory.glob(".codex-apply-*")))


if __name__ == "__main__":
    unittest.main()
