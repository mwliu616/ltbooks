"""Backup HTTP boundary tests: admin authorization, safe payloads and uploads."""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api as webapi  # noqa: E402


NAME = "ltbooks-20261118T191206Z-db35a10a.tar.gz"


class BackupApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ltbooks-backup-api-test-")
        self.root = Path(self.temp.name)
        self.client = webapi.app.test_client()
        self.admin = {
            "X-Ledu-Token": webapi.API_TOKEN,
            "X-Ledu-Role": "admin",
            "X-Ledu-User": "backup-test",
        }
        self.lock_env = mock.patch.dict(
            os.environ, {"LEDU_BACKUP_LOCK": str(self.root / "backup.lock")}
        )
        self.lock_env.start()

    def tearDown(self):
        self.lock_env.stop()
        self.temp.cleanup()

    def test_list_is_admin_only_and_hides_server_paths(self):
        with mock.patch("core.backup.BackupManager") as cls:
            manager = cls.return_value
            manager.config.keep = 180
            manager.list.return_value = [{
                "name": NAME, "path": "/private/server/path.tar.gz", "size": 123,
                "created_at": "2026-11-18T19:12:06Z", "database": "books",
                "attachment_count": 2,
            }]
            denied = self.client.get("/backups", headers={**self.admin, "X-Ledu-Role": "auditor"})
            self.assertEqual(denied.status_code, 403)
            response = self.client.get("/backups", headers=self.admin)
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["settings"]["keep"], 180)
            self.assertNotIn("path", data["backups"][0])
            self.assertEqual(data["backups"][0]["name"], NAME)

    def test_create_uses_lock_audits_and_hides_server_path(self):
        result = {
            "name": NAME, "path": "/private/server/path.tar.gz",
            "created_at": "2026-11-18T19:12:06Z", "database": "books",
            "attachment_count": 2, "archive_sha256": "a" * 64, "pruned": [],
        }
        with mock.patch("core.backup.BackupManager") as cls, \
                mock.patch.object(webapi, "append_audit_via_api") as audit:
            cls.return_value.create.return_value = result
            response = self.client.post("/backups/create", json={}, headers=self.admin)
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertNotIn("path", data)
            cls.return_value.create.assert_called_once_with(label="manual", incremental=False)
            audit.assert_called_once()

    def test_restore_requires_explicit_confirmation(self):
        response = self.client.post("/backups/restore", json={
            "name": NAME, "restoreDatabase": True, "restoreAttachments": True,
        }, headers=self.admin)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "confirmation_required")

    def test_restore_upload_is_validated_and_never_returns_paths(self):
        result = {
            "archive": "/tmp/upload.tar.gz", "created_at": "2026-11-18T19:12:06Z",
            "database_restored": True, "attachment_count": 2,
            "safety_backup": "/private/pre-restore.tar.gz",
        }
        with mock.patch("core.backup.BackupManager") as cls, \
                mock.patch.object(webapi, "append_audit_via_api") as audit:
            cls.return_value.restore.return_value = result
            response = self.client.post("/backups/restore-upload", data={
                "restoreDatabase": "1", "restoreAttachments": "1", "confirmRestore": "1",
                "archive": (io.BytesIO(b"not-a-real-archive"), NAME),
            }, headers=self.admin, content_type="multipart/form-data")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertNotIn("archive", data)
            self.assertNotIn("safety_backup", data)
            self.assertEqual(data["safetyBackupName"], "pre-restore.tar.gz")
            cls.return_value.restore.assert_called_once()
            audit.assert_called_once()

    def test_delete_is_admin_only_and_audited(self):
        with mock.patch("core.backup.BackupManager") as cls, \
                mock.patch.object(webapi, "append_audit_via_api") as audit:
            cls.return_value.delete.return_value = {"deleted": NAME}
            denied = self.client.post(
                "/backups/delete", json={"name": NAME},
                headers={**self.admin, "X-Ledu-Role": "accountant"},
            )
            self.assertEqual(denied.status_code, 403)
            response = self.client.post(
                "/backups/delete", json={"name": NAME}, headers=self.admin
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["deleted"], NAME)
            cls.return_value.delete.assert_called_once_with(NAME)
            audit.assert_called_once()
            invalid = self.client.post(
                "/backups/delete", json={"name": "../secret"}, headers=self.admin
            )
            self.assertEqual(invalid.status_code, 400)

    def test_schedule_save_validates_and_audits(self):
        with mock.patch("core.settings.set") as settings_set, \
                mock.patch.object(webapi, "append_audit_via_api") as audit:
            denied = self.client.post(
                "/backups/schedule", json={"times": ["08:00"]},
                headers={**self.admin, "X-Ledu-Role": "accountant"},
            )
            self.assertEqual(denied.status_code, 403)
            response = self.client.post(
                "/backups/schedule", json={"times": ["17:00", "9:30", ""]},
                headers=self.admin,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["schedule"], ["09:30", "17:00"])
            saved = settings_set.call_args_list[0].args
            self.assertEqual(saved[0], "backup.schedule")
            self.assertEqual(saved[1], "09:30,17:00")
            audit.assert_called_once()
            invalid = self.client.post(
                "/backups/schedule", json={"times": ["bad"]}, headers=self.admin
            )
            self.assertEqual(invalid.status_code, 400)

    def test_download_streams_only_whitelisted_admin_backup(self):
        archive = self.root / NAME
        archive.write_bytes(b"backup-bytes")
        with mock.patch("core.backup.BackupManager") as cls, \
                mock.patch.object(webapi, "append_audit_via_api"):
            cls.return_value.config.backup_dir = self.root
            denied = self.client.get(
                "/backups/download/" + NAME,
                headers={**self.admin, "X-Ledu-Role": "accountant"},
            )
            self.assertEqual(denied.status_code, 403)
            response = self.client.get("/backups/download/" + NAME, headers=self.admin)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"backup-bytes")
            response.close()
            invalid = self.client.get("/backups/download/..%2Fsecret", headers=self.admin)
            self.assertEqual(invalid.status_code, 404)


if __name__ == "__main__":
    unittest.main()
