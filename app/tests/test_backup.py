from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.backup import (  # noqa: E402
    BackupConfig, BackupError, BackupManager, backup_operation_lock,
    next_due_slot, normalize_schedule,
)


DUMP_SCRIPT = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
if os.environ.get("FAKE_DUMP_FAIL"):
    sys.stderr.write("mysqldump failed: " + os.environ.get("MYSQL_PWD", ""))
    raise SystemExit(9)
args = sys.argv[1:]
Path(os.environ["FAKE_DUMP_ARGS"]).write_text(json.dumps(args), encoding="utf-8")
tables = [t for t in os.environ.get("FAKE_TABLES", "").split(",") if t]
if tables and args[-1] in tables:
    state_path = Path(os.environ["FAKE_TABLE_STATE"])
    states = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    sys.stdout.write("-- table " + args[-1] + "\n" + json.dumps(states.get(args[-1], 0)))
else:
    sys.stdout.write(Path(os.environ["FAKE_DB_STATE"]).read_text(encoding="utf-8"))
'''

MYSQL_SCRIPT = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
Path(os.environ["FAKE_MYSQL_ARGS"]).write_text(json.dumps(args), encoding="utf-8")
if "-e" in args:
    tables = [t for t in os.environ.get("FAKE_TABLES", "").split(",") if t]
    sys.stdout.write("\n".join(sorted(tables)))
else:
    Path(os.environ["FAKE_DB_STATE"]).write_text(sys.stdin.read(), encoding="utf-8")
'''


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ltbooks-backup-test-")
        self.root = Path(self.temp.name)
        self.backup_dir = self.root / "backups"
        self.primary = self.root / "primary"
        self.fallback = self.root / "fallback"
        self.primary.mkdir()
        self.fallback.mkdir()
        self.db_state = self.root / "db-state.txt"
        self.db_state.write_text("db-v1", encoding="utf-8")
        self.table_state = self.root / "table-state.json"
        self.table_state.write_text(json.dumps({"journal": "v1", "users": "v1"}), encoding="utf-8")
        self.dump_args = self.root / "dump-args.json"
        self.mysql_args = self.root / "mysql-args.json"
        self.dump = self._executable("fake-mysqldump", DUMP_SCRIPT)
        self.mysql = self._executable("fake-mysql", MYSQL_SCRIPT)
        self.db = {
            "host": "127.0.0.1", "port": 3306, "user": "unit-test",
            "password": "unit-test-secret", "database": "unit_test_db",
        }
        self.manager = self._manager()
        self.env = mock.patch.dict(os.environ, {
            "FAKE_DB_STATE": str(self.db_state),
            "FAKE_DUMP_ARGS": str(self.dump_args),
            "FAKE_MYSQL_ARGS": str(self.mysql_args),
            "FAKE_TABLES": "",
            "FAKE_TABLE_STATE": str(self.table_state),
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _executable(self, name, content):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
        return path

    def _manager(self, keep=10):
        return BackupManager(BackupConfig(
            backup_dir=self.backup_dir,
            upload_dirs=(self.primary, self.fallback),
            keep=keep,
            mysqldump=str(self.dump),
            mysql=str(self.mysql),
        ), self.db)

    def _enable_tables(self, *names):
        os.environ["FAKE_TABLES"] = ",".join(names)

    def _set_table_state(self, **states):
        self.table_state.write_text(json.dumps(states), encoding="utf-8")

    def test_create_manifest_and_full_restore_with_safety_backup(self):
        receipt = self.primary / "票据.pdf"
        bank = self.fallback / "nested" / "bank.csv"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        bank.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_bytes(b"receipt-v1")
        bank.write_bytes(b"bank-v1")

        created = self.manager.create(prune=False)
        archive = Path(created["path"])
        self.assertTrue(archive.is_file())
        self.assertEqual(archive.parent, self.backup_dir.resolve())
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        self.assertEqual(created["attachment_count"], 2)
        self.assertEqual(
            created["archive_sha256"], hashlib.sha256(archive.read_bytes()).hexdigest()
        )
        with tarfile.open(archive, "r:gz") as tar:
            manifest = json.load(tar.extractfile("manifest.json"))
            self.assertEqual(manifest["version"], 1)
            self.assertTrue(manifest["database"]["single_transaction"])
            self.assertEqual(len(manifest["attachments"]["roots"]), 2)
            self.assertEqual(len(manifest["attachments"]["files"]), 2)
            for item in manifest["attachments"]["files"]:
                data = tar.extractfile(item["member"]).read()
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])

        dump_argv = json.loads(self.dump_args.read_text(encoding="utf-8"))
        self.assertIn("--single-transaction", dump_argv)
        self.assertNotIn(self.db["password"], " ".join(dump_argv))

        self.db_state.write_text("db-v2", encoding="utf-8")
        receipt.write_bytes(b"changed")
        bank.unlink()
        extra = self.primary / "new-after-backup.txt"
        extra.write_text("keep me", encoding="utf-8")
        restored = self.manager.restore(archive)

        self.assertEqual(self.db_state.read_text(encoding="utf-8"), "db-v1")
        self.assertEqual(receipt.read_bytes(), b"receipt-v1")
        self.assertEqual(bank.read_bytes(), b"bank-v1")
        self.assertEqual(extra.read_text(encoding="utf-8"), "keep me")
        self.assertEqual(restored["attachment_count"], 2)
        safety = Path(restored["safety_backup"])
        self.assertTrue(safety.is_file())
        self.assertIn("pre-restore", safety.name)
        self.assertNotEqual(safety, archive)
        mysql_argv = json.loads(self.mysql_args.read_text(encoding="utf-8"))
        self.assertIn("--binary-mode", mysql_argv)
        self.assertNotIn(self.db["password"], " ".join(mysql_argv))
        self.assertEqual(len(self.manager.list()), 2)

    def test_second_backup_same_day_is_rolling_and_restores_single_file(self):
        self._enable_tables("journal", "users")
        receipt = self.primary / "receipt.txt"
        receipt.write_text("receipt-v1", encoding="utf-8")

        first = self.manager.create(prune=False)
        self.assertEqual(first["type"], "full")
        self.assertTrue((self.backup_dir / ".ltbooks-state.json").is_file())

        self._set_table_state(journal="v2", users="v1")
        self.db_state.write_text("db-v2", encoding="utf-8")
        added = self.primary / "added.txt"
        added.write_text("added", encoding="utf-8")
        second = self.manager.create(prune=False)

        # 滚动：更新同一个文件，目录中不产生第二个自动备份。
        self.assertEqual(second["type"], "rolling")
        self.assertEqual(second["name"], first["name"])
        self.assertEqual(second["path"], first["path"])
        self.assertEqual(len(self.manager.list()), 1)
        with tarfile.open(second["path"], "r:gz") as tar:
            manifest = json.load(tar.extractfile("manifest.json"))
            self.assertEqual(manifest["version"], 1)
            self.assertTrue(manifest["rolling"])
            self.assertEqual(manifest["rolling_updates"], 1)
            # 滚动包是完整快照：有 database.sql，附件为全量。
            self.assertIn("database.sql", tar.getnames())
            self.assertEqual(
                {item["path"] for item in manifest["attachments"]["files"]},
                {"receipt.txt", "added.txt"},
            )

        # 单文件直接恢复，无需回溯链条。
        self._set_table_state(journal="v9", users="v9")
        self.db_state.write_text("db-v9", encoding="utf-8")
        added.unlink()
        restored = self.manager.restore(second["path"])
        self.assertEqual(restored["chain_length"], 1)
        self.assertEqual(restored["backup_type"], "full")
        self.assertEqual(receipt.read_text(encoding="utf-8"), "receipt-v1")
        self.assertEqual(added.read_text(encoding="utf-8"), "added")
        self.assertEqual(self.db_state.read_text(encoding="utf-8"), "db-v2")
        # 恢复后状态清除，下一次备份重新建立新的完整包。
        self.assertFalse((self.backup_dir / ".ltbooks-state.json").exists())
        self.assertEqual(self.manager.create(prune=False)["type"], "full")

    def test_rolling_archive_keeps_latest_full_snapshot(self):
        self._enable_tables("journal")
        first = self.manager.create(prune=False)

        self._set_table_state(journal="v2")
        self.db_state.write_text("db-v2", encoding="utf-8")
        first_added = self.primary / "first-added.txt"
        first_added.write_text("first", encoding="utf-8")
        second = self.manager.create(prune=False)

        self._set_table_state(journal="v3")
        self.db_state.write_text("db-v3", encoding="utf-8")
        second_added = self.primary / "second-added.txt"
        second_added.write_text("second", encoding="utf-8")
        third = self.manager.create(prune=False)

        self.assertEqual(third["name"], first["name"])
        self.assertEqual(third["name"], second["name"])
        self.assertEqual(len(self.manager.list()), 1)
        with tarfile.open(third["path"], "r:gz") as tar:
            manifest = json.load(tar.extractfile("manifest.json"))
            self.assertEqual(manifest["rolling_updates"], 2)
            self.assertEqual(
                {item["path"] for item in manifest["attachments"]["files"]},
                {"first-added.txt", "second-added.txt"},
            )

        restored = self.manager.restore(third["path"])
        self.assertEqual(restored["chain_length"], 1)
        self.assertEqual(self.db_state.read_text(encoding="utf-8"), "db-v3")
        self.assertEqual(first_added.read_text(encoding="utf-8"), "first")
        self.assertEqual(second_added.read_text(encoding="utf-8"), "second")

    def test_cross_day_auto_backup_keeps_rolling_single_file(self):
        self._enable_tables("journal")
        first = self.manager.create(prune=False)
        self.assertEqual(first["type"], "full")
        state_path = self.backup_dir / ".ltbooks-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["created_at"] = "2020-01-01T00:00:00Z"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        self._set_table_state(journal="v2")
        again = self.manager.create(prune=False)
        self.assertEqual(again["type"], "rolling")
        self.assertEqual(again["name"], first["name"])

    def test_manual_full_backup_becomes_new_rolling_baseline(self):
        self._enable_tables("journal")
        self.manager.create(prune=False)
        self._set_table_state(journal="v2")
        self.manager.create(prune=False)
        full = self.manager.create(prune=False, incremental=False)
        self.assertEqual(full["type"], "full")
        state = json.loads(
            (self.backup_dir / ".ltbooks-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["tip"], full["name"])
        self.assertEqual(state["base"], full["name"])
        self._set_table_state(journal="v3")
        nxt = self.manager.create(prune=False)
        self.assertEqual(nxt["type"], "rolling")
        self.assertEqual(nxt["name"], full["name"])

    def test_rolling_archive_omits_deleted_attachments(self):
        self._enable_tables("journal")
        doomed = self.primary / "doomed.txt"
        doomed.write_text("remove-me", encoding="utf-8")
        self.manager.create(prune=False)

        doomed.unlink()
        rolled = self.manager.create(prune=False)
        self.assertEqual(rolled["type"], "rolling")
        with tarfile.open(rolled["path"], "r:gz") as tar:
            manifest = json.load(tar.extractfile("manifest.json"))
            self.assertEqual(manifest["attachments"]["files"], [])

        kept = self.primary / "kept.txt"
        kept.write_text("keep", encoding="utf-8")
        last = self.manager.create(prune=False)
        self.manager.restore(last["path"])
        self.assertTrue(kept.exists())
        self.assertFalse(doomed.exists())

    def test_prune_keeps_single_rolling_archive(self):
        self._enable_tables("journal")
        first = self.manager.create(prune=False)
        self._set_table_state(journal="v2")
        second = self.manager.create(prune=False)
        self._set_table_state(journal="v3")
        third = self.manager.create(prune=False)
        manager = self._manager(keep=1)

        self.assertEqual(third["name"], second["name"])
        self.assertEqual(third["name"], first["name"])
        self.assertEqual(manager.prune(), [])
        self.assertEqual({row["name"] for row in manager.list()}, {first["name"]})

    def test_delete_removes_archive_and_clears_tip_state(self):
        self._enable_tables("journal")
        self.manager.create(prune=False)
        self._set_table_state(journal="v2")
        second = self.manager.create(prune=False)
        state_file = self.backup_dir / ".ltbooks-state.json"
        self.assertTrue(state_file.exists())

        self.assertEqual(self.manager.delete(second["name"]), {"deleted": second["name"]})
        self.assertFalse((self.backup_dir / second["name"]).exists())
        self.assertFalse(state_file.exists())
        self.assertEqual(self.manager.create(prune=False)["type"], "full")

    def test_delete_rolling_archive_clears_state(self):
        self._enable_tables("journal")
        self.manager.create(prune=False)
        self._set_table_state(journal="v2")
        rolled = self.manager.create(prune=False)

        self.assertEqual(self.manager.delete(rolled["name"]), {"deleted": rolled["name"]})
        self.assertEqual(self.manager.list(), [])
        self.assertFalse((self.backup_dir / ".ltbooks-state.json").exists())

    def test_restore_rolling_without_state_succeeds(self):
        self._enable_tables("journal")
        self.manager.create(prune=False)
        self._set_table_state(journal="v2")
        self.db_state.write_text("db-v2", encoding="utf-8")
        rolled = self.manager.create(prune=False)
        (self.backup_dir / ".ltbooks-state.json").unlink()
        restored = self.manager.restore(rolled["path"])
        self.assertEqual(restored["chain_length"], 1)
        self.assertEqual(self.db_state.read_text(encoding="utf-8"), "db-v2")

    def test_attachments_only_without_safety_does_not_run_mysql(self):
        source = self.primary / "a.txt"
        source.write_text("old", encoding="utf-8")
        created = self.manager.create(prune=False)
        source.write_text("new", encoding="utf-8")
        self.db_state.write_text("new-db", encoding="utf-8")
        self.mysql_args.unlink(missing_ok=True)

        result = self.manager.restore(
            created["path"], restore_database=False,
            restore_attachments=True, safety_backup=False,
        )
        self.assertEqual(source.read_text(encoding="utf-8"), "old")
        self.assertEqual(self.db_state.read_text(encoding="utf-8"), "new-db")
        self.assertFalse(result["database_restored"])
        self.assertIsNone(result["safety_backup"])
        self.assertFalse(self.mysql_args.exists())

    def test_malicious_tar_members_rejected_before_safety_backup(self):
        cases = ("traversal", "symlink")
        for case in cases:
            with self.subTest(case=case):
                archive = self.root / f"{case}.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    for name, data in (("manifest.json", b"{}"), ("database.sql", b"sql")):
                        info = tarfile.TarInfo(name)
                        info.size = len(data)
                        tar.addfile(info, io.BytesIO(data))
                    if case == "traversal":
                        info = tarfile.TarInfo("attachments/root0/../../escape.txt")
                        info.size = 3
                        tar.addfile(info, io.BytesIO(b"bad"))
                    else:
                        info = tarfile.TarInfo("attachments/root0/link")
                        info.type = tarfile.SYMTYPE
                        info.linkname = "/etc/passwd"
                        tar.addfile(info)
                with self.assertRaises(BackupError):
                    self.manager.restore(archive)
                self.assertFalse((self.root / "escape.txt").exists())
                self.assertFalse(self.backup_dir.exists())

    def test_checksum_mismatch_rejected_before_any_restore(self):
        created = self.manager.create(prune=False)
        original = Path(created["path"])
        corrupt = self.root / "corrupt.tar.gz"
        with tarfile.open(original, "r:gz") as source, tarfile.open(corrupt, "w:gz") as target:
            for member in source.getmembers():
                data = source.extractfile(member).read()
                if member.name == "database.sql":
                    data = b"x" * len(data)
                info = tarfile.TarInfo(member.name)
                info.size = len(data)
                target.addfile(info, io.BytesIO(data))
        self.db_state.write_text("must-not-change", encoding="utf-8")

        with self.assertRaisesRegex(BackupError, "SHA256"):
            self.manager.restore(corrupt)
        self.assertEqual(self.db_state.read_text(encoding="utf-8"), "must-not-change")
        self.assertEqual(len(self.manager.list()), 1)

    def test_retention_only_removes_new_backup_archives(self):
        manager = self._manager(keep=2)
        first = manager.create()
        manager.create()
        third = manager.create()
        self.assertIn(first["name"], third["pruned"])
        old_sql = self.backup_dir / "ltbooks-old.sql.gz"
        unrelated = self.backup_dir / "other.tar.gz"
        old_sql.write_text("keep", encoding="utf-8")
        unrelated.write_text("keep", encoding="utf-8")

        removed = manager.prune(keep=1)
        self.assertEqual(len(removed), 1)
        self.assertEqual(len(manager.list()), 1)
        self.assertTrue(old_sql.exists())
        self.assertTrue(unrelated.exists())
        with self.assertRaises(BackupError):
            manager.prune(keep=0)

    def test_list_reports_malformed_manifest_without_blocking(self):
        self.backup_dir.mkdir()
        archive = self.backup_dir / "ltbooks-20260101T000000Z-deadbeef.tar.gz"
        data = b'{"database": []}'
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        rows = self.manager.list()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], archive.name)
        self.assertIn("error", rows[0])
        self.assertNotIn("_mtime_ns", rows[0])

    def test_database_error_redacts_password_and_leaves_no_archive(self):
        with mock.patch.dict(os.environ, {"FAKE_DUMP_FAIL": "1"}):
            with self.assertRaises(BackupError) as caught:
                self.manager.create()
        message = str(caught.exception)
        self.assertNotIn(self.db["password"], message)
        self.assertIn("[已隐藏]", message)
        self.assertEqual(self.manager.list(), [])

    def test_operation_lock_rejects_overlapping_web_and_cron_jobs(self):
        lock = self.root / "backup.lock"
        with mock.patch.dict(os.environ, {"LEDU_BACKUP_LOCK": str(lock)}):
            with backup_operation_lock():
                with self.assertRaisesRegex(BackupError, "另一项备份或恢复"):
                    with backup_operation_lock():
                        pass
            # 锁释放后下一项任务可以立即取得，不需要等待或重试。
            with backup_operation_lock():
                pass

    def test_cli_create_list_restore_and_prune(self):
        source = self.primary / "cli.txt"
        source.write_text("cli-old", encoding="utf-8")
        cli_backup = self.root / "cli-backups"
        env = os.environ.copy()
        env.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "LEDU_BACKUP_DIR": str(cli_backup),
            "LEDU_UPLOAD_DIRS": os.pathsep.join((str(self.primary), str(self.fallback))),
            "LEDU_BACKUP_KEEP": "5",
            "LEDU_MYSQLDUMP_BIN": str(self.dump),
            "LEDU_MYSQL_BIN": str(self.mysql),
            "LEDU_DB_HOST": "127.0.0.1",
            "LEDU_DB_PORT": "3306",
            "LEDU_DB_NAME": "unit_test_db",
            "LEDU_DB_USER": "unit-test",
            "LEDU_DB_PASSWORD": self.db["password"],
        })
        script = Path(__file__).resolve().parent.parent / "tools" / "auto_backup.py"

        def run(*args):
            proc = subprocess.run(
                [sys.executable, str(script), *args], env=env,
                text=True, capture_output=True, timeout=30, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn(self.db["password"], proc.stdout + proc.stderr)
            return json.loads(proc.stdout)

        created = run("create")
        listed = run("list")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], created["name"])
        source.write_text("cli-new", encoding="utf-8")
        restored = run(
            "restore", created["path"], "--attachments-only", "--no-safety-backup"
        )
        self.assertFalse(restored["database_restored"])
        self.assertEqual(source.read_text(encoding="utf-8"), "cli-old")
        run("create", "--no-prune")
        pruned = run("prune", "--keep", "1")
        self.assertEqual(pruned["keep"], 1)
        self.assertEqual(len(pruned["pruned"]), 1)
        self.assertEqual(len(run("list")), 1)


class ScheduleTest(unittest.TestCase):
    def test_normalize_schedule_sorts_dedupes_and_validates(self):
        self.assertEqual(
            normalize_schedule(["17:00", "9:05", "", "09:05"]),
            ["09:05", "17:00"],
        )
        with self.assertRaisesRegex(BackupError, "格式"):
            normalize_schedule(["25:00"])
        with self.assertRaisesRegex(BackupError, "最多"):
            normalize_schedule(["01:00", "02:00", "03:00", "04:00", "05:00"])

    def test_next_due_slot_returns_latest_unrun_slot(self):
        hk = timezone(timedelta(hours=8))
        now = datetime(2026, 11, 19, 18, 30, tzinfo=hk)
        self.assertIsNone(next_due_slot(
            ["09:00", "17:00"], "2026-11-19T17:05:00+08:00", now))
        due = next_due_slot(
            ["09:00", "17:00"], "2026-11-19T09:05:00+08:00", now)
        self.assertEqual((due.hour, due.minute), (17, 0))
        self.assertIsNone(next_due_slot([], "", now))
        self.assertIsNone(next_due_slot(["23:00"], "", now))


if __name__ == "__main__":
    unittest.main()
