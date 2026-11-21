# LtBooks — core/backup.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""LtBooks 数据库与上传附件的一致性备份、校验和恢复。

备份包为受控目录中的 .tar.gz：
- 完整备份（版本 1）：manifest.json、database.sql 与 attachments/rootN/...；
- 滚动备份（版本 1 + rolling 标记）：自动备份在首次完整包的基础上，每次把最新
  全量原子重写进同一个文件，目录中始终只有一个自动备份文件，恢复无需回溯链条；
- 旧版增量备份（版本 2）仍可读取和恢复，首次滚动时会被合并并删除。

恢复不会信任包内的绝对路径，而是按 rootN 映射到当前配置的上传目录；附件采用
逐文件原子覆盖。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from config import DB, STORAGE_DIR, env as app_env


FORMAT_NAME = "ltbooks-backup"
FORMAT_VERSION = 1                 # 完整备份：单个 database.sql
FORMAT_VERSION_DELTA = 2           # 增量备份：仅变更表与变更附件，链接到父备份
STATE_FILENAME = ".ltbooks-state.json"
STATE_VERSION = 1
INCREMENTAL_FILENAME = "ltbooks-auto-incremental.tar.gz"
DEFAULT_KEEP = 180                 # 每日两次，约 90 天
MAX_MANIFEST_SIZE = 16 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
BACKUP_NAME_RE = re.compile(
    r"(?:ltbooks-auto-incremental|ltbooks-(?:[A-Za-z0-9][A-Za-z0-9_-]{0,31}-)?"
    r"\d{8}T\d{6}Z-[0-9a-f]{8})\.tar\.gz"
)
ROOT_ID_RE = re.compile(r"root(0|[1-9][0-9]*)")
TABLE_NAME_RE = re.compile(r"[A-Za-z0-9_$]{1,64}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SCHEDULE_KEY = "backup.schedule"
DEFAULT_SCHEDULE = ("09:00", "17:00")
MAX_SCHEDULE_TIMES = 4
TIME_RE = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


def normalize_schedule(values) -> list[str]:
    """把若干 HH:MM 去重排序；空白项忽略，格式非法直接报错。"""
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        match = TIME_RE.fullmatch(text)
        if not match:
            raise BackupError(f"自动备份时间格式不正确：{text}（应为 HH:MM）")
        item = f"{int(match.group(1)):02d}:{match.group(2)}"
        if item not in out:
            out.append(item)
    if len(out) > MAX_SCHEDULE_TIMES:
        raise BackupError(f"自动备份时间最多设置 {MAX_SCHEDULE_TIMES} 个")
    return sorted(out)


def load_schedule() -> list[str]:
    """读取界面设置的自动备份时间；从未设置过时返回默认 09:00、17:00。"""
    from .settings import get

    raw = get(SCHEDULE_KEY, "__unset__")
    if raw == "__unset__":
        return list(DEFAULT_SCHEDULE)
    return normalize_schedule(str(raw).split(","))


def next_due_slot(schedule: list[str], last_auto: str | None,
                  now: datetime) -> datetime | None:
    """返回今天最晚一个已到点、且尚未执行的备份时间；没有则 None。"""
    due: datetime | None = None
    for item in schedule:
        match = TIME_RE.fullmatch(item)
        if not match:
            continue
        slot = now.replace(hour=int(match.group(1)), minute=int(match.group(2)),
                           second=0, microsecond=0)
        if slot <= now and (due is None or slot > due):
            due = slot
    if due is None:
        return None
    if last_auto:
        try:
            last = datetime.fromisoformat(last_auto)
        except ValueError:
            last = None
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=now.tzinfo)
            if last >= due:
                return None
    return due


class BackupError(RuntimeError):
    """可向运维人员直接展示的备份/恢复错误。"""


@contextmanager
def backup_operation_lock():
    """与定时任务的 flock 共用一把锁，阻止界面操作与自动备份重叠。"""
    path = Path(app_env("LEDU_BACKUP_LOCK", "/var/run/ltbooks-auto-backup.lock"))
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as ex:
        raise BackupError(f"无法打开备份锁 {path}：{ex.strerror or ex}") from ex
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as ex:
            raise BackupError("另一项备份或恢复操作正在进行，请稍后重试") from ex
        yield
    finally:
        os.close(fd)


@dataclass(frozen=True)
class BackupConfig:
    backup_dir: Path
    upload_dirs: tuple[Path, ...]
    keep: int = DEFAULT_KEEP
    mysqldump: str = "mysqldump"
    mysql: str = "mysql"

    def __post_init__(self):
        backup_dir = Path(self.backup_dir).expanduser().resolve()
        upload_dirs = tuple(Path(p).expanduser().resolve() for p in self.upload_dirs)
        if len(set(upload_dirs)) != len(upload_dirs):
            raise BackupError("上传目录配置存在重复项")
        for root in upload_dirs:
            if backup_dir == root or root in backup_dir.parents:
                raise BackupError("备份目录不能位于上传目录内，避免递归打包")
        object.__setattr__(self, "backup_dir", backup_dir)
        object.__setattr__(self, "upload_dirs", upload_dirs)
        object.__setattr__(self, "keep", _validate_keep(self.keep))

    @classmethod
    def from_env(cls) -> "BackupConfig":
        raw_dirs = app_env("LEDU_UPLOAD_DIRS")
        if raw_dirs:
            dirs = tuple(Path(p) for p in raw_dirs.split(os.pathsep) if p.strip())
        else:
            dirs = (Path("/opt/ltbooks/uploads"), STORAGE_DIR / "uploads")
        try:
            keep = int(app_env("LEDU_BACKUP_KEEP", str(DEFAULT_KEEP)))
        except (TypeError, ValueError) as ex:
            raise BackupError("LEDU_BACKUP_KEEP 必须是正整数") from ex
        return cls(
            backup_dir=Path(app_env("LEDU_BACKUP_DIR", "/opt/ltbooks/backups")),
            upload_dirs=dirs,
            keep=keep,
            mysqldump=str(app_env("LEDU_MYSQLDUMP_BIN", "mysqldump")),
            mysql=str(app_env("LEDU_MYSQL_BIN", "mysql")),
        )


def _validate_keep(value) -> int:
    if isinstance(value, bool):
        raise BackupError("保留份数必须是正整数")
    try:
        keep = int(value)
    except (TypeError, ValueError) as ex:
        raise BackupError("保留份数必须是正整数") from ex
    if keep < 1:
        raise BackupError("保留份数必须至少为 1")
    return keep


def _safe_label(label: str | None) -> str:
    if not label:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", label):
        raise BackupError("备份标签只能含字母、数字、横线和下划线，最长 32 字符")
    return label + "-"


def _safe_parts(name: str, description: str) -> tuple[str, ...]:
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise BackupError(f"{description}不是安全的相对路径")
    raw = name.rstrip("/") if name.endswith("/") else name
    parts = raw.split("/")
    if not raw or any(p in ("", ".", "..") for p in parts):
        raise BackupError(f"{description}包含路径穿越或空路径段")
    return tuple(parts)


def _file_info(path: Path) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return {"size": size, "sha256": digest.hexdigest()}


def _copy_with_hash(source: Path, destination: Path) -> dict:
    """复制时算哈希；O_NOFOLLOW 防止上传目录中的链接指向包外。"""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
    except OSError as ex:
        raise BackupError(f"无法读取附件 {source}：{ex.strerror or ex}") from ex
    digest = hashlib.sha256()
    size = 0
    with os.fdopen(fd, "rb") as src:
        info = os.fstat(src.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise BackupError(f"附件不是普通文件：{source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as dst:
            while True:
                chunk = src.read(CHUNK_SIZE)
                if not chunk:
                    break
                dst.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    return {"size": size, "sha256": digest.hexdigest()}


def _sha256_text(value: str) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


class BackupManager:
    def __init__(self, config: BackupConfig | None = None, db_config: dict | None = None):
        self.config = config or BackupConfig.from_env()
        self.db = dict(db_config or DB)

    def _redact(self, text: str) -> str:
        result = text or ""
        password = str(self.db.get("password") or "")
        if password:
            result = result.replace(password, "[已隐藏]")
        return result.strip()

    def _db_args(self) -> list[str]:
        database = str(self.db.get("database") or "")
        user = str(self.db.get("user") or "")
        if not database or not user:
            raise BackupError("数据库配置缺少 LEDU_DB_NAME 或 LEDU_DB_USER")
        if database.startswith("-"):
            raise BackupError("数据库名不能以横线开头")
        try:
            port = int(self.db.get("port") or 3306)
        except (TypeError, ValueError) as ex:
            raise BackupError("数据库端口配置不合法") from ex
        return [
            f"--host={self.db.get('host') or '127.0.0.1'}",
            f"--port={port}",
            f"--user={user}",
            "--default-character-set=utf8mb4",
        ]

    def _run_db_tool(self, argv: list[str], **kwargs) -> None:
        env = os.environ.copy()
        # 密码不出现在命令行、日志或异常中。
        env["MYSQL_PWD"] = str(self.db.get("password") or "")
        try:
            proc = subprocess.run(
                argv,
                stdin=kwargs.get("stdin"),
                stdout=kwargs.get("stdout", subprocess.DEVNULL),
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
        except FileNotFoundError as ex:
            raise BackupError(f"找不到数据库工具：{Path(argv[0]).name}") from ex
        except OSError as ex:
            raise BackupError(
                f"无法执行数据库工具 {Path(argv[0]).name}：{self._redact(str(ex))}"
            ) from ex
        if proc.returncode:
            detail = self._redact(proc.stderr.decode("utf-8", errors="replace"))
            if len(detail) > 1600:
                detail = detail[:1600] + "…"
            raise BackupError(
                f"数据库工具 {Path(argv[0]).name} 执行失败（退出码 {proc.returncode}）："
                f"{detail or '无错误输出'}"
            )

    def _dump_database(self, destination: Path) -> None:
        argv = [
            self.config.mysqldump,
            "--single-transaction",
            "--quick",
            "--skip-lock-tables",
            # 应用 schema 不创建 EVENT；不传 --events，避免仅为备份给应用账号
            # 额外授予 EVENT 管理权限。存储过程与触发器仍按实际对象纳入 dump。
            "--routines",
            "--triggers",
            "--hex-blob",
            *self._db_args(),
            str(self.db["database"]),
        ]
        with destination.open("xb") as out:
            try:
                self._run_db_tool(argv, stdout=out)
            except Exception:
                destination.unlink(missing_ok=True)
                raise

    def _restore_database(self, source: Path) -> None:
        argv = [
            self.config.mysql,
            "--binary-mode",
            *self._db_args(),
            str(self.db["database"]),
        ]
        with source.open("rb") as sql:
            self._run_db_tool(argv, stdin=sql, stdout=subprocess.DEVNULL)

    def _query(self, sql: str) -> str:
        """执行只读查询并返回文本结果；用于读取表清单和校验基线。"""
        argv = [
            self.config.mysql,
            "--batch",
            "--skip-column-names",
            *self._db_args(),
            str(self.db["database"]),
            "-e",
            sql,
        ]
        env = os.environ.copy()
        env["MYSQL_PWD"] = str(self.db.get("password") or "")
        try:
            proc = subprocess.run(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, check=False, text=True,
            )
        except (FileNotFoundError, OSError) as ex:
            raise BackupError(f"无法执行数据库查询：{self._redact(str(ex))}") from ex
        if proc.returncode:
            raise BackupError(
                f"数据库查询失败（退出码 {proc.returncode}）："
                f"{self._redact(proc.stderr)[:800]}"
            )
        return proc.stdout

    def _list_tables(self) -> list[str]:
        """返回当前库的基础表名；名称必须可直接作为 SQL 标识符或 tar 成员。"""
        output = self._query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        tables = []
        for line in output.splitlines():
            name = line.strip()
            if not name:
                continue
            if not TABLE_NAME_RE.fullmatch(name):
                raise BackupError(f"表名包含不安全字符，无法增量备份：{name[:64]}")
            tables.append(name)
        return tables

    def _dump_table(self, table: str, destination: Path) -> dict:
        """单表 dump：结构 + 数据 + 触发器；输出去掉时间戳以保证哈希可比较。"""
        if not TABLE_NAME_RE.fullmatch(table):
            raise BackupError("表名不合法")
        argv = [
            self.config.mysqldump,
            "--single-transaction",
            "--quick",
            "--skip-lock-tables",
            "--skip-comments",
            "--skip-dump-date",
            "--triggers",
            "--hex-blob",
            "--default-character-set=utf8mb4",
            *self._db_args(),
            str(self.db["database"]),
            table,
        ]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as out:
            try:
                self._run_db_tool(argv, stdout=out)
            except Exception:
                destination.unlink(missing_ok=True)
                raise
        return _file_info(destination)

    def _snapshot_tables(self, stage: Path, keep_changed: set[str] | None = None,
                         baseline: dict[str, str] | None = None) -> tuple[dict, list]:
        """逐表 dump 并计算哈希。

        keep_changed 为 None 时丢弃全部文件（完整备份只需哈希）；
        否则只保留哈希与基线不同的表，返回可直接写入增量包的记录。
        """
        tables = self._list_tables()
        hashes: dict[str, str] = {}
        changed: list[dict] = []
        for table in tables:
            destination = stage / "tables" / f"{table}.sql"
            info = self._dump_table(table, destination)
            hashes[table] = info["sha256"]
            differs = baseline is None or baseline.get(table) != info["sha256"]
            if keep_changed is not None and table in keep_changed and differs:
                changed.append({
                    "name": table,
                    "member": f"tables/{table}.sql",
                    **info,
                })
            else:
                destination.unlink(missing_ok=True)
        return hashes, changed

    def _collect_attachments(self, stage: Path, baseline: dict[str, str] | None = None):
        """遍历上传目录；baseline 不为空时只复制新增或变化的文件。"""
        roots: list[dict] = []
        files: list[dict] = []
        state: dict[str, str] = {}
        seen: set[str] = set()
        for index, root in enumerate(self.config.upload_dirs):
            root_id = f"root{index}"
            roots.append({"id": root_id, "source": str(root)})
            if not root.exists():
                continue
            if not root.is_dir():
                raise BackupError(f"上传路径不是目录：{root}")
            for current, dirnames, filenames in os.walk(root, followlinks=False):
                current_path = Path(current)
                for dirname in sorted(dirnames):
                    if (current_path / dirname).is_symlink():
                        raise BackupError(f"附件目录包含符号链接：{current_path / dirname}")
                dirnames[:] = sorted(dirnames)
                for filename in sorted(filenames):
                    source = current_path / filename
                    if source.is_symlink():
                        raise BackupError(f"附件包含符号链接：{source}")
                    relative = source.relative_to(root).as_posix()
                    key = f"{root_id}/{relative}"
                    seen.add(key)
                    if baseline is None:
                        member = f"attachments/{key}"
                        info = _copy_with_hash(source, stage / member)
                    else:
                        info = _file_info(source)
                        if baseline.get(key) == info["sha256"]:
                            state[key] = info["sha256"]
                            continue
                        member = f"attachments/{key}"
                        _copy_with_hash(source, stage / member)
                    state[key] = info["sha256"]
                    files.append({
                        "root": root_id,
                        "path": relative,
                        "member": member,
                        **info,
                    })
        deleted = sorted(set(baseline or {}) - seen)
        return roots, files, state, deleted

    def _state_path(self) -> Path:
        return self.config.backup_dir / STATE_FILENAME

    def _read_state(self) -> dict | None:
        path = self._state_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if (
            not isinstance(raw, dict)
            or raw.get("version") != STATE_VERSION
            or not isinstance(raw.get("tip"), str)
            or not isinstance(raw.get("tables"), dict)
            or not isinstance(raw.get("attachments"), dict)
        ):
            return None
        # 旧状态没有 base 时，以当时的链尾作为新固定增量包的累计基线。
        base = raw.get("base", raw["tip"])
        if (
            not BACKUP_NAME_RE.fullmatch(raw["tip"])
            or not isinstance(base, str)
            or not BACKUP_NAME_RE.fullmatch(base)
        ):
            return None
        raw["base"] = base
        return raw

    def _write_state(self, tip: str, created_at: str, tables: dict, attachments: dict,
                     base: str | None = None) -> None:
        """记录链尾、累计基线与基线哈希；写入失败只影响下次是否退化为完整备份。"""
        payload = {
            "version": STATE_VERSION,
            "tip": tip,
            "base": base or tip,
            "created_at": created_at,
            "tables": tables,
            "attachments": attachments,
        }
        path = self._state_path()
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)

    def _clear_state(self) -> None:
        try:
            self._state_path().unlink(missing_ok=True)
        except OSError:
            pass

    def _should_incremental(self, state: dict | None) -> bool:
        """链尾和累计基线都存在时走增量；否则先生成完整备份。"""
        if not state or not state["tables"]:
            return False
        backup_dir = self.config.backup_dir
        return ((backup_dir / state["tip"]).is_file()
                and (backup_dir / state["base"]).is_file())

    def _ensure_backup_dir(self) -> Path:
        path = self.config.backup_dir
        try:
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
        except OSError as ex:
            raise BackupError(f"无法创建备份目录 {path}：{ex.strerror or ex}") from ex
        if not path.is_dir():
            raise BackupError(f"备份路径不是目录：{path}")
        return path

    def create(self, label: str | None = None, prune: bool = True,
               incremental: bool | None = None) -> dict:
        """创建备份。

        incremental=None 为自动备份：有有效基线则滚动更新同一个文件，否则先完整；
        incremental=False 为手动备份：始终生成新的完整备份，并作为新的滚动基线。
        """
        backup_dir = self._ensure_backup_dir()
        state = self._read_state()
        if incremental is None:
            incremental = self._should_incremental(state)
        if incremental:
            return self._update_rolling(backup_dir, state, label, prune)
        return self._create_full(backup_dir, label, prune)

    def _new_archive(self, backup_dir: Path, label: str | None) -> tuple[str, Path]:
        label = _safe_label(label)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        final = backup_dir / f"ltbooks-{label}{stamp}-{secrets.token_hex(4)}.tar.gz"
        while final.exists():
            final = backup_dir / f"ltbooks-{label}{stamp}-{secrets.token_hex(4)}.tar.gz"
        return created_at, final

    def _create_full(self, backup_dir: Path, label: str | None, prune: bool) -> dict:
        """完整备份：单文件 database.sql + 全部附件，并记录表哈希供滚动更新比对。"""
        created_at, final = self._new_archive(backup_dir, label)

        table_hashes: dict[str, str] = {}
        attachment_state: dict[str, str] = {}
        incremental_ready = True
        with tempfile.TemporaryDirectory(prefix="ltbooks-backup-") as work:
            stage = Path(work)
            database = stage / "database.sql"
            self._dump_database(database)
            # 逐表哈希供后续增量比对使用；失败时退化为每次完整备份，不影响本次结果。
            try:
                table_hashes, _ = self._snapshot_tables(stage / "table-state")
            except BackupError:
                table_hashes, incremental_ready = {}, False
            roots, files, attachment_state, _ = self._collect_attachments(stage)
            manifest = {
                "format": FORMAT_NAME,
                "version": FORMAT_VERSION,
                "type": "full",
                "label": label or "auto",
                "created_at": created_at,
                "database": {
                    "name": str(self.db["database"]),
                    "member": "database.sql",
                    "single_transaction": True,
                    **_file_info(database),
                },
                "attachments": {"roots": roots, "files": files},
            }

            manifest_path = stage / "manifest.json"
            with manifest_path.open("x", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            manifest_path.chmod(0o600)

            tmp_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w+b", dir=backup_dir, prefix=".ltbooks-",
                    suffix=".tar.gz.tmp", delete=False,
                ) as raw:
                    tmp_name = raw.name
                    with tarfile.open(fileobj=raw, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
                        tar.add(manifest_path, arcname="manifest.json", recursive=False)
                        tar.add(database, arcname="database.sql", recursive=False)
                        for item in files:
                            tar.add(
                                stage / item["member"], arcname=item["member"], recursive=False
                            )
                    raw.flush()
                    os.fsync(raw.fileno())
                os.chmod(tmp_name, 0o600)
                os.replace(tmp_name, final)
                tmp_name = None
            except (OSError, tarfile.TarError) as ex:
                raise BackupError(f"写入备份包失败：{self._redact(str(ex))}") from ex
            finally:
                if tmp_name:
                    Path(tmp_name).unlink(missing_ok=True)

        if incremental_ready:
            self._write_state(final.name, created_at, table_hashes, attachment_state)
        result = {
            "name": final.name,
            "path": str(final),
            "created_at": created_at,
            "database": manifest["database"]["name"],
            "attachment_count": len(files),
            "archive_sha256": _file_info(final)["sha256"],
            "pruned": [],
            "type": "full",
            "changed_tables": len(table_hashes),
        }
        if prune:
            try:
                result["pruned"] = self.prune()
            except BackupError as ex:
                raise BackupError(f"备份已生成 {final}，但清理旧备份失败：{ex}") from ex
        return result

    def _update_rolling(self, backup_dir: Path, state: dict | None,
                        label: str | None, prune: bool) -> dict:
        """单文件滚动备份：把最新全量合并进首个完整包，原子替换同一文件。

        目录中自动备份始终只有一个文件，恢复时无需回溯增量链。
        """
        if not state:
            raise BackupError("缺少可用的完整备份基线，请先创建完整备份")
        target_name = state["base"]
        if target_name == INCREMENTAL_FILENAME:
            raise BackupError("滚动基线不能指向旧增量包，请先创建完整备份")
        target = backup_dir / target_name
        if not target.is_file():
            raise BackupError("滚动备份基线不存在，请先创建完整备份")
        # 基线必须是完整包（v1），不能把旧的差异包当作滚动目标。
        try:
            previous = self._read_manifest_unverified(target)
        except BackupError as ex:
            raise BackupError(f"滚动基准备份不可读：{ex}") from ex
        if previous.get("version") != FORMAT_VERSION:
            raise BackupError("滚动基线不是完整备份，请先创建完整备份")

        created_at = previous.get("created_at")
        if not isinstance(created_at, str):
            created_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z")
        updated_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")
        try:
            updates = int(previous.get("rolling_updates") or 0) + 1
        except (TypeError, ValueError):
            updates = 1

        table_hashes: dict[str, str] = {}
        attachment_state: dict[str, str] = {}
        with tempfile.TemporaryDirectory(prefix="ltbooks-backup-") as work:
            stage = Path(work)
            database = stage / "database.sql"
            self._dump_database(database)
            try:
                table_hashes, _ = self._snapshot_tables(stage / "table-state")
            except BackupError:
                # 逐表哈希失败不影响本次备份，沿用上次状态以维持单文件滚动。
                table_hashes = dict(state.get("tables") or {})
            roots, files, attachment_state, _ = self._collect_attachments(stage)
            if not attachment_state:
                attachment_state = dict(state.get("attachments") or {})
            manifest = {
                "format": FORMAT_NAME,
                "version": FORMAT_VERSION,
                "type": "full",
                "rolling": True,
                "rolling_updates": updates,
                "label": label or "auto",
                "created_at": created_at,
                "updated_at": updated_at,
                "database": {
                    "name": str(self.db["database"]),
                    "member": "database.sql",
                    "single_transaction": True,
                    **_file_info(database),
                },
                "attachments": {"roots": roots, "files": files},
            }

            manifest_path = stage / "manifest.json"
            with manifest_path.open("x", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            manifest_path.chmod(0o600)

            tmp_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w+b", dir=backup_dir, prefix=".ltbooks-",
                    suffix=".tar.gz.tmp", delete=False,
                ) as raw:
                    tmp_name = raw.name
                    with tarfile.open(fileobj=raw, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
                        tar.add(manifest_path, arcname="manifest.json", recursive=False)
                        tar.add(database, arcname="database.sql", recursive=False)
                        for item in files:
                            tar.add(
                                stage / item["member"], arcname=item["member"], recursive=False
                            )
                    raw.flush()
                    os.fsync(raw.fileno())
                os.chmod(tmp_name, 0o600)
                os.replace(tmp_name, target)
                tmp_name = None
            except (OSError, tarfile.TarError) as ex:
                raise BackupError(f"写入滚动备份包失败：{self._redact(str(ex))}") from ex
            finally:
                if tmp_name:
                    Path(tmp_name).unlink(missing_ok=True)

        if table_hashes:
            self._write_state(target_name, updated_at, table_hashes, attachment_state,
                              base=target_name)
        # 迁移：旧版独立增量包不再需要，删除以免目录里出现第二个自动备份文件。
        legacy = backup_dir / INCREMENTAL_FILENAME
        if legacy.is_file() and legacy.name != target_name:
            try:
                legacy.unlink()
            except OSError:
                pass

        result = {
            "name": target_name,
            "path": str(target),
            "created_at": created_at,
            "updated_at": updated_at,
            "database": manifest["database"]["name"],
            "attachment_count": len(files),
            "archive_sha256": _file_info(target)["sha256"],
            "pruned": [],
            "type": "rolling",
            "rolling_updates": updates,
            "changed_tables": len(table_hashes),
        }
        if prune:
            try:
                result["pruned"] = self.prune()
            except BackupError as ex:
                raise BackupError(f"备份已更新 {target}，但清理旧备份失败：{ex}") from ex
        return result

    def _backup_files(self) -> list[Path]:
        directory = self.config.backup_dir
        if not directory.exists():
            return []
        if not directory.is_dir():
            raise BackupError(f"备份路径不是目录：{directory}")
        files = []
        for path in directory.iterdir():
            if path.is_symlink() or not BACKUP_NAME_RE.fullmatch(path.name):
                continue
            if path.is_file():
                files.append(path)
        return files

    @staticmethod
    def _label_of(name: str) -> str:
        """旧包清单没有 label，按文件名前缀推断，保证手动/自动列表都能归类。"""
        if name.startswith("ltbooks-manual-"):
            return "manual"
        if name.startswith("ltbooks-pre-restore-"):
            return "pre-restore"
        return "auto"

    def list(self) -> list[dict]:
        """按修改时间倒序列出本模块的备份，不读取或输出数据库凭据。"""
        rows = []
        for path in self._backup_files():
            try:
                info = path.stat()
            except FileNotFoundError:
                continue
            row = {
                "name": path.name,
                "path": str(path),
                "size": info.st_size,
                "created_at": datetime.fromtimestamp(
                    info.st_mtime, timezone.utc
                ).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "database": None,
                "attachment_count": None,
                "type": None,
                "label": self._label_of(path.name),
                "chain_parent": None,
                "_mtime_ns": info.st_mtime_ns,
            }
            try:
                manifest = self._read_manifest_unverified(path)
                database = manifest.get("database")
                attachments = manifest.get("attachments")
                files = attachments.get("files") if isinstance(attachments, dict) else None
                if not isinstance(database, dict) or not isinstance(files, list):
                    raise BackupError("备份清单结构不完整")
                created_at = manifest.get("created_at")
                if created_at is not None and not isinstance(created_at, str):
                    raise BackupError("备份清单创建时间不合法")
                row.update({
                    "created_at": created_at or row["created_at"],
                    "database": database.get("name"),
                    "attachment_count": len(files),
                    "type": "incremental" if manifest.get("version") == FORMAT_VERSION_DELTA else "full",
                    "label": str(manifest.get("label") or row["label"]),
                    "chain_parent": manifest.get("parent") if manifest.get("version") == FORMAT_VERSION_DELTA else None,
                    "rolling": bool(manifest.get("rolling")),
                    "rolling_updates": manifest.get("rolling_updates"),
                    "updated_at": manifest.get("updated_at"),
                })
            except BackupError as ex:
                row["error"] = str(ex)
            rows.append(row)
        rows.sort(key=lambda row: row["_mtime_ns"], reverse=True)
        for row in rows:
            del row["_mtime_ns"]
        return rows

    def _read_manifest_unverified(self, archive: Path) -> dict:
        try:
            with tarfile.open(archive, "r:gz") as tar:
                member = tar.getmember("manifest.json")
                if not member.isreg() or member.size > MAX_MANIFEST_SIZE:
                    raise BackupError("manifest.json 缺失或过大")
                return self._read_manifest_member(tar, member)
        except BackupError:
            raise
        except (OSError, tarfile.TarError, KeyError) as ex:
            raise BackupError(f"无法读取备份清单：{self._redact(str(ex))}") from ex

    def prune(self, keep: int | None = None) -> list[str]:
        """仅删除本模块命名的旧包，不碰既有 SQL 或其他文件。

        增量包依赖父备份，因此保留最新若干份时，会一并保留它们回溯到的完整备份。
        """
        keep = self.config.keep if keep is None else _validate_keep(keep)
        files = self._backup_files()
        files.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
        keep_names = {path.name for path in files[:keep]}
        queue = list(files[:keep])
        while queue:
            path = queue.pop()
            try:
                kind, manifest = self._read_type(path)
            except BackupError:
                continue
            if kind != "incremental":
                continue
            parent = manifest.get("parent")
            if not isinstance(parent, str) or not BACKUP_NAME_RE.fullmatch(parent):
                continue
            if parent in keep_names:
                continue
            parent_path = self.config.backup_dir / parent
            if parent_path.is_file():
                keep_names.add(parent)
                queue.append(parent_path)
        removed = []
        for path in files:
            if path.name in keep_names:
                continue
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as ex:
                raise BackupError(f"无法删除旧备份 {path.name}：{ex.strerror or ex}") from ex
        return removed

    def delete(self, name: str) -> dict:
        """删除单个备份包。

        增量包依赖父包，因此仍被其他增量备份引用的父包必须先删除其后续增量；
        删除链尾时同步清除状态文件，下一次备份自动回到完整备份。
        """
        if not isinstance(name, str) or not BACKUP_NAME_RE.fullmatch(name):
            raise BackupError("请选择有效的备份包")
        path = self.config.backup_dir / name
        if path.is_symlink() or not path.is_file():
            raise BackupError("备份包不存在或已删除")
        for other in self._backup_files():
            if other.name == name:
                continue
            try:
                kind, manifest = self._read_type(other)
            except BackupError:
                continue
            if kind == "incremental" and manifest.get("parent") == name:
                raise BackupError("该备份是其他增量备份的父包，请先删除后续增量备份")
        try:
            path.unlink()
        except OSError as ex:
            raise BackupError(f"无法删除备份 {name}：{ex.strerror or ex}") from ex
        state = self._read_state()
        if state and state["tip"] == name:
            self._clear_state()
        return {"deleted": name}

    def _resolve_archive(self, archive) -> Path:
        supplied = Path(archive).expanduser()
        path = self.config.backup_dir / supplied if not supplied.is_absolute() and len(supplied.parts) == 1 else supplied
        path = path.resolve()
        if not path.exists():
            raise BackupError(f"备份包不存在：{path}")
        if not path.is_file():
            raise BackupError(f"备份包不是普通文件：{path}")
        if not path.name.endswith(".tar.gz"):
            raise BackupError("备份包必须是 .tar.gz 文件")
        return path

    def _read_manifest_member(self, tar: tarfile.TarFile, member: tarfile.TarInfo) -> dict:
        source = tar.extractfile(member)
        if source is None:
            raise BackupError("无法读取 manifest.json")
        data = source.read(MAX_MANIFEST_SIZE + 1)
        if len(data) > MAX_MANIFEST_SIZE:
            raise BackupError("manifest.json 过大")
        try:
            manifest = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as ex:
            raise BackupError("manifest.json 不是有效的 UTF-8 JSON") from ex
        if not isinstance(manifest, dict):
            raise BackupError("manifest.json 顶层必须是对象")
        return manifest

    def _validate_members(self, members: list[tarfile.TarInfo]) -> dict[str, tarfile.TarInfo]:
        by_name = {}
        for member in members:
            name = member.name
            _safe_parts(name, "tar 成员")
            if name in by_name:
                raise BackupError(f"tar 包含重复成员：{name}")
            if not (member.isfile() or member.isdir()):
                raise BackupError(f"tar 包含链接或特殊成员，已拒绝：{name}")
            if member.size < 0:
                raise BackupError(f"tar 成员大小不合法：{name}")
            if member.isfile():
                if name not in ("manifest.json", "database.sql") and not name.startswith(
                    ("attachments/", "tables/")
                ):
                    raise BackupError(f"tar 包含未授权成员：{name}")
            elif name != "attachments" and not name.startswith(("attachments/", "tables/")):
                raise BackupError(f"tar 包含未授权目录：{name}")
            by_name[name] = member
        return by_name

    def _validate_manifest(self, manifest: dict, by_name: dict[str, tarfile.TarInfo]) -> list[dict]:
        if manifest.get("format") != FORMAT_NAME:
            raise BackupError("备份格式或版本不受支持")
        version = manifest.get("version")
        if version == FORMAT_VERSION:
            return self._validate_full_manifest(manifest, by_name)
        if version == FORMAT_VERSION_DELTA:
            return self._validate_delta_manifest(manifest, by_name)
        raise BackupError("备份格式或版本不受支持")

    def _validate_full_manifest(self, manifest: dict, by_name: dict[str, tarfile.TarInfo]) -> list[dict]:
        if not isinstance(manifest.get("created_at"), str):
            raise BackupError("清单缺少创建时间")
        database = manifest.get("database")
        if not isinstance(database, dict) or database.get("member") != "database.sql":
            raise BackupError("清单中的数据库记录不合法")
        if not isinstance(database.get("name"), str) or not database["name"]:
            raise BackupError("清单缺少数据库名")
        self._validate_file_record(database, "数据库")
        attachments = manifest.get("attachments")
        if not isinstance(attachments, dict):
            raise BackupError("清单缺少附件记录")
        roots = attachments.get("roots")
        files = attachments.get("files")
        if not isinstance(roots, list) or not isinstance(files, list):
            raise BackupError("附件根目录或文件清单不合法")
        root_ids = set()
        for position, root in enumerate(roots):
            if not isinstance(root, dict) or root.get("id") != f"root{position}":
                raise BackupError("附件根目录编号不连续或不合法")
            if not ROOT_ID_RE.fullmatch(root["id"]):
                raise BackupError("附件根目录编号不合法")
            root_ids.add(root["id"])

        expected = {"manifest.json", "database.sql"}
        seen_paths = set()
        for item in files:
            if not isinstance(item, dict):
                raise BackupError("附件文件记录不合法")
            root_id = item.get("root")
            if root_id not in root_ids:
                raise BackupError("附件引用了未声明的根目录")
            relative = item.get("path")
            parts = _safe_parts(relative, "附件路径")
            normalized = "/".join(parts)
            if normalized != relative or (root_id, normalized) in seen_paths:
                raise BackupError("附件路径重复或未规范化")
            seen_paths.add((root_id, normalized))
            expected_member = f"attachments/{root_id}/{normalized}"
            if item.get("member") != expected_member:
                raise BackupError("附件 tar 成员名与相对路径不一致")
            self._validate_file_record(item, f"附件 {normalized}")
            expected.add(expected_member)

        manifest_member = by_name.get("manifest.json")
        database_member = by_name.get("database.sql")
        if manifest_member is None or not manifest_member.isfile():
            raise BackupError("备份缺少 manifest.json")
        if database_member is None or not database_member.isfile():
            raise BackupError("备份缺少 database.sql")
        actual = {name for name, member in by_name.items() if member.isfile()}
        if actual != expected:
            missing = sorted(expected - actual)[:3]
            extra = sorted(actual - expected)[:3]
            detail = []
            if missing:
                detail.append("缺少 " + ", ".join(missing))
            if extra:
                detail.append("未登记 " + ", ".join(extra))
            raise BackupError("tar 文件与清单不一致：" + "；".join(detail))
        return files

    def _validate_roots(self, attachments: dict) -> set[str]:
        roots = attachments.get("roots")
        if not isinstance(roots, list):
            raise BackupError("附件根目录清单不合法")
        root_ids = set()
        for position, root in enumerate(roots):
            if not isinstance(root, dict) or root.get("id") != f"root{position}":
                raise BackupError("附件根目录编号不连续或不合法")
            root_ids.add(root["id"])
        return root_ids

    def _validate_delta_manifest(self, manifest: dict, by_name: dict[str, tarfile.TarInfo]) -> list[dict]:
        """增量包：只允许 manifest、变更表与变更附件，且必须指向合法父备份。"""
        if manifest.get("type") != "incremental":
            raise BackupError("增量备份清单类型不合法")
        if not isinstance(manifest.get("created_at"), str):
            raise BackupError("清单缺少创建时间")
        parent = manifest.get("parent")
        if not isinstance(parent, str) or not BACKUP_NAME_RE.fullmatch(parent):
            raise BackupError("清单中的父备份名不合法")
        database = manifest.get("database")
        if (
            not isinstance(database, dict)
            or database.get("kind") != "delta"
            or not isinstance(database.get("name"), str)
        ):
            raise BackupError("清单中的数据库记录不合法")

        records = manifest.get("tables")
        if not isinstance(records, list):
            raise BackupError("增量表清单不合法")
        expected = {"manifest.json"}
        table_names = set()
        for item in records:
            if not isinstance(item, dict):
                raise BackupError("增量表记录不合法")
            name = item.get("name")
            if not isinstance(name, str) or not TABLE_NAME_RE.fullmatch(name) or name in table_names:
                raise BackupError("增量表名不合法或重复")
            table_names.add(name)
            member = f"tables/{name}.sql"
            if item.get("member") != member:
                raise BackupError("增量表 tar 成员名不合法")
            self._validate_file_record(item, f"数据表 {name}")
            expected.add(member)

        dropped = manifest.get("dropped_tables", [])
        if not isinstance(dropped, list) or any(
            not isinstance(name, str) or not TABLE_NAME_RE.fullmatch(name) for name in dropped
        ):
            raise BackupError("删除表清单不合法")

        attachments = manifest.get("attachments")
        if not isinstance(attachments, dict):
            raise BackupError("清单缺少附件记录")
        root_ids = self._validate_roots(attachments)
        files = attachments.get("files")
        deleted = attachments.get("deleted", [])
        if not isinstance(files, list) or not isinstance(deleted, list):
            raise BackupError("增量附件清单不合法")

        seen_paths = set()
        for item in files:
            if not isinstance(item, dict):
                raise BackupError("附件文件记录不合法")
            root_id = item.get("root")
            if root_id not in root_ids:
                raise BackupError("附件引用了未声明的根目录")
            relative = item.get("path")
            parts = _safe_parts(relative, "附件路径")
            normalized = "/".join(parts)
            if normalized != relative or (root_id, normalized) in seen_paths:
                raise BackupError("附件路径重复或未规范化")
            seen_paths.add((root_id, normalized))
            member = f"attachments/{root_id}/{normalized}"
            if item.get("member") != member:
                raise BackupError("附件 tar 成员名与相对路径不一致")
            self._validate_file_record(item, f"附件 {normalized}")
            expected.add(member)

        for entry in deleted:
            if not isinstance(entry, str) or entry.count("/") < 1:
                raise BackupError("删除附件记录不合法")
            root_id, relative = entry.split("/", 1)
            if root_id not in root_ids:
                raise BackupError("删除附件引用了未声明的根目录")
            parts = _safe_parts(relative, "附件路径")
            if "/".join(parts) != relative:
                raise BackupError("删除附件路径未规范化")

        manifest_member = by_name.get("manifest.json")
        if manifest_member is None or not manifest_member.isfile():
            raise BackupError("备份缺少 manifest.json")
        actual = {name for name, member in by_name.items() if member.isfile()}
        if actual != expected:
            missing = sorted(expected - actual)[:3]
            extra = sorted(actual - expected)[:3]
            detail = []
            if missing:
                detail.append("缺少 " + ", ".join(missing))
            if extra:
                detail.append("未登记 " + ", ".join(extra))
            raise BackupError("tar 文件与清单不一致：" + "；".join(detail))
        return files

    @staticmethod
    def _validate_file_record(item: dict, description: str) -> None:
        if type(item.get("size")) is not int or item["size"] < 0:
            raise BackupError(f"{description}大小记录不合法")
        if not _sha256_text(item.get("sha256")):
            raise BackupError(f"{description} SHA256 记录不合法")

    def _extract_checked(
        self, tar: tarfile.TarFile, member: tarfile.TarInfo,
        destination: Path, expected: dict,
    ) -> None:
        source = tar.extractfile(member)
        if source is None:
            raise BackupError(f"无法读取 tar 成员：{member.name}")
        if member.size != expected["size"]:
            raise BackupError(f"文件大小与清单不符：{member.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with destination.open("xb") as out:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if size != expected["size"] or digest.hexdigest() != expected["sha256"]:
            raise BackupError(f"SHA256 校验失败：{member.name}")

    def _stage_validated_archive(self, archive: Path, stage: Path) -> dict:
        """在任何安全备份或恢复写入之前完成成员、清单、大小和 SHA256 校验。"""
        try:
            with tarfile.open(archive, "r:gz") as tar:
                by_name = self._validate_members(tar.getmembers())
                manifest_member = by_name.get("manifest.json")
                if manifest_member is None or not manifest_member.isfile():
                    raise BackupError("备份缺少 manifest.json")
                if manifest_member.size > MAX_MANIFEST_SIZE:
                    raise BackupError("manifest.json 过大")
                manifest = self._read_manifest_member(tar, manifest_member)
                files = self._validate_manifest(manifest, by_name)
                if manifest.get("version") == FORMAT_VERSION:
                    self._extract_checked(
                        tar, by_name["database.sql"], stage / "database.sql",
                        manifest["database"],
                    )
                else:
                    for item in manifest.get("tables", []):
                        self._extract_checked(
                            tar, by_name[item["member"]], stage / item["member"], item
                        )
                for item in files:
                    self._extract_checked(
                        tar, by_name[item["member"]], stage / item["member"], item
                    )
                return manifest
        except BackupError:
            raise
        except (OSError, tarfile.TarError) as ex:
            raise BackupError(f"备份包读取或校验失败：{self._redact(str(ex))}") from ex

    def _read_type(self, archive: Path) -> tuple[str, dict]:
        manifest = self._read_manifest_unverified(archive)
        if manifest.get("format") != FORMAT_NAME:
            raise BackupError("备份格式或版本不受支持")
        version = manifest.get("version")
        if version == FORMAT_VERSION:
            return "full", manifest
        if version == FORMAT_VERSION_DELTA and manifest.get("type") == "incremental":
            return "incremental", manifest
        raise BackupError("备份格式或版本不受支持")

    def _resolve_chain(self, archive: Path) -> list[Path]:
        """从目标备份回溯到完整备份；父备份必须位于同一备份目录。"""
        chain = []
        seen = set()
        current = archive
        while True:
            kind, manifest = self._read_type(current)
            chain.append(current)
            if kind == "full":
                break
            parent = manifest.get("parent")
            if not isinstance(parent, str) or not BACKUP_NAME_RE.fullmatch(parent):
                raise BackupError("增量备份缺少合法的父备份")
            if parent in seen:
                raise BackupError("增量备份链存在循环引用")
            seen.add(parent)
            current = self.config.backup_dir / parent
            if not current.is_file():
                raise BackupError(f"增量链缺少父备份：{parent}")
            if len(chain) > 200:
                raise BackupError("增量备份链过长，已拒绝恢复")
        chain.reverse()
        return chain

    def _validate_delta_roots_against(self, base: dict, delta: dict) -> None:
        base_ids = [root["id"] for root in base["attachments"]["roots"]]
        delta_ids = [root["id"] for root in delta["attachments"]["roots"]]
        if delta_ids != base_ids:
            raise BackupError("增量备份的附件目录映射与完整备份不一致")

    def _attachment_path(self, targets: dict[str, Path], root_id: str, relative: str) -> Path:
        root = targets[root_id]
        parts = PurePosixPath(relative).parts
        cursor = root
        for index, part in enumerate(parts):
            cursor = cursor / part
            if cursor.is_symlink():
                raise BackupError(f"附件路径包含符号链接：{cursor}")
            if index < len(parts) - 1 and cursor.exists() and not cursor.is_dir():
                raise BackupError(f"附件父路径不是目录：{cursor}")
        return cursor

    def _delete_attachments(self, manifest: dict, targets: dict[str, Path]) -> int:
        count = 0
        for entry in manifest["attachments"].get("deleted", []):
            root_id, relative = entry.split("/", 1)
            target = self._attachment_path(targets, root_id, relative)
            if target.exists() and target.is_file():
                target.unlink()
                count += 1
        return count

    def _apply_delta_database(self, stage: Path, manifest: dict) -> None:
        """按清单重放变更表；删除表一并处理，整个过程关闭外键检查。"""
        records = manifest.get("tables") or []
        dropped = manifest.get("dropped_tables") or []
        if not records and not dropped:
            return
        script = stage / "_delta.sql"
        with script.open("xb") as out:
            out.write(b"SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;\n")
            for table in dropped:
                out.write(f"DROP TABLE IF EXISTS `{table}`;\n".encode("utf-8"))
            for item in records:
                data = (stage / item["member"]).read_bytes()
                out.write(data)
                if data and not data.endswith(b"\n"):
                    out.write(b"\n")
            out.write(b"SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;\n")
        self._restore_database(script)

    def _attachment_targets(self, manifest: dict) -> dict[str, Path]:
        targets = {}
        for position, root in enumerate(manifest["attachments"]["roots"]):
            if position < len(self.config.upload_dirs):
                targets[root["id"]] = self.config.upload_dirs[position]
        used = {item["root"] for item in manifest["attachments"]["files"]}
        used |= {
            entry.split("/", 1)[0]
            for entry in manifest["attachments"].get("deleted", [])
            if isinstance(entry, str) and "/" in entry
        }
        missing = sorted(used - set(targets))
        if missing:
            raise BackupError(
                "当前 LEDU_UPLOAD_DIRS 缺少备份所需的附件目录映射：" + ", ".join(missing)
            )
        return targets

    def _preflight_targets(self, manifest: dict, targets: dict[str, Path]) -> None:
        for item in manifest["attachments"]["files"]:
            root = targets[item["root"]]
            if root.exists() and not root.is_dir():
                raise BackupError(f"附件恢复目标不是目录：{root}")
            cursor = root
            parts = PurePosixPath(item["path"]).parts
            for index, part in enumerate(parts):
                cursor = cursor / part
                if cursor.is_symlink():
                    raise BackupError(f"附件恢复路径包含符号链接：{cursor}")
                if index < len(parts) - 1 and cursor.exists() and not cursor.is_dir():
                    raise BackupError(f"附件恢复父路径不是目录：{cursor}")
            if cursor.exists() and not cursor.is_file():
                raise BackupError(f"附件恢复目标不是普通文件：{cursor}")

    @staticmethod
    def _restore_file(source: Path, target: Path, root_stat: os.stat_result) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.stat() if target.exists() else None
        fd, tmp_name = tempfile.mkstemp(prefix=".ltbooks-restore-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as out, source.open("rb") as src:
                shutil.copyfileobj(src, out, CHUNK_SIZE)
                out.flush()
                os.fsync(out.fileno())
            mode = stat.S_IMODE(existing.st_mode) & 0o777 if existing else 0o640
            os.chmod(tmp_name, mode)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                owner = existing or root_stat
                os.chown(tmp_name, owner.st_uid, owner.st_gid)
            os.replace(tmp_name, target)
            tmp_name = None
        finally:
            if tmp_name:
                Path(tmp_name).unlink(missing_ok=True)

    def _restore_attachments(self, stage: Path, manifest: dict, targets: dict[str, Path]) -> int:
        count = 0
        for item in manifest["attachments"]["files"]:
            root = targets[item["root"]]
            root.mkdir(parents=True, mode=0o750, exist_ok=True)
            root_stat = root.stat()
            relative = PurePosixPath(item["path"])
            target = root.joinpath(*relative.parts)
            self._restore_file(stage / item["member"], target, root_stat)
            count += 1
        return count

    def restore(
        self, archive, restore_database: bool = True,
        restore_attachments: bool = True, safety_backup: bool = True,
    ) -> dict:
        """校验并恢复；增量包会自动回溯整条链，默认先做完整安全备份。"""
        if not restore_database and not restore_attachments:
            raise BackupError("至少需要选择数据库或附件其中一项进行恢复")
        archive = self._resolve_archive(archive)
        chain = self._resolve_chain(archive)
        with tempfile.TemporaryDirectory(prefix="ltbooks-restore-") as work:
            stage = Path(work)
            parts: list[tuple[dict, Path]] = []
            for index, member in enumerate(chain):
                part_stage = stage / f"part{index}"
                parts.append((self._stage_validated_archive(member, part_stage), part_stage))
            base_manifest, base_stage = parts[0]
            targets = self._attachment_targets(base_manifest) if restore_attachments else {}
            if restore_attachments:
                self._preflight_targets(base_manifest, targets)
                for manifest, _ in parts[1:]:
                    self._validate_delta_roots_against(base_manifest, manifest)
                    self._preflight_targets(manifest, targets)

            # 安全备份必须是完整备份，避免恢复后状态文件指向不存在的增量链。
            safety = None
            if safety_backup:
                safety = self.create(label="pre-restore", prune=False, incremental=False)
            try:
                if restore_database:
                    self._restore_database(base_stage / "database.sql")
                    for manifest, part_stage in parts[1:]:
                        self._apply_delta_database(part_stage, manifest)
                count = 0
                if restore_attachments:
                    count += self._restore_attachments(base_stage, base_manifest, targets)
                    for manifest, part_stage in parts[1:]:
                        count += self._restore_attachments(part_stage, manifest, targets)
                        self._delete_attachments(manifest, targets)
            except (BackupError, OSError) as ex:
                detail = self._redact(str(ex))
                if safety:
                    raise BackupError(
                        f"恢复失败：{detail}；恢复前安全备份保留在 {safety['path']}"
                    ) from ex
                raise BackupError(f"恢复失败：{detail}") from ex
            # 恢复后的数据库不再等于链尾状态，清除基线，下次备份重新生成完整包。
            self._clear_state()
            return {
                "archive": str(archive),
                "created_at": base_manifest["created_at"],
                "database_restored": restore_database,
                "attachment_count": count,
                "safety_backup": safety["path"] if safety else None,
                "chain_length": len(chain),
                "backup_type": "incremental" if len(chain) > 1 else "full",
            }


def create_backup(**kwargs) -> dict:
    return BackupManager().create(**kwargs)


def list_backups() -> list[dict]:
    return BackupManager().list()


def restore_backup(archive, **kwargs) -> dict:
    return BackupManager().restore(archive, **kwargs)


def prune_backups(keep: int | None = None) -> list[str]:
    return BackupManager().prune(keep)
