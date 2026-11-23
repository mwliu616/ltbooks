#!/usr/bin/env python3
# LtBooks — tools/auto_backup.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""LtBooks 备份恢复 CLI：tick / create / list / restore / prune。

示例：
  ./venv/bin/python tools/auto_backup.py tick        # 计划任务每分钟调用，到点才备份
  ./venv/bin/python tools/auto_backup.py create
  ./venv/bin/python tools/auto_backup.py list
  ./venv/bin/python tools/auto_backup.py restore /var/backups/ltbooks/<包名>
  ./venv/bin/python tools/auto_backup.py prune --keep 180
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.backup import (  # noqa: E402
    BackupConfig, BackupError, BackupManager, backup_operation_lock,
    load_schedule, next_due_slot,
)


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as ex:
        raise argparse.ArgumentTypeError("必须是正整数") from ex
    if number < 1:
        raise argparse.ArgumentTypeError("必须至少为 1")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lt-AI-Books 数据库与附件备份恢复")
    parser.add_argument("--backup-dir", help="覆盖 LEDU_BACKUP_DIR")
    parser.add_argument(
        "--upload-dir", action="append", dest="upload_dirs",
        help="覆盖上传目录；可重复传入，顺序对应备份包 root0/root1",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "tick",
        help="按界面设置的香港时间到点执行自动备份（供计划任务每分钟调用）",
    )

    create = commands.add_parser("create", help="创建备份：有基线时增量，否则完整")
    create.add_argument("--keep", type=_positive_int, help="创建后保留最近 N 份")
    create.add_argument("--no-prune", action="store_true", help="本次创建后不清理旧备份")
    create.add_argument(
        "--full", action="store_true",
        help="强制创建完整备份（默认有基线时创建增量）",
    )

    commands.add_parser("list", help="列出本模块创建的备份")

    restore = commands.add_parser("restore", help="校验并恢复备份（默认先创建安全备份）")
    restore.add_argument("archive", help="受控目录中的包名，或 .tar.gz 的完整路径")
    component = restore.add_mutually_exclusive_group()
    component.add_argument("--database-only", action="store_true", help="只恢复数据库")
    component.add_argument("--attachments-only", action="store_true", help="只恢复附件")
    restore.add_argument(
        "--no-safety-backup", action="store_true",
        help="明确跳过恢复前安全备份（不建议）",
    )

    prune = commands.add_parser("prune", help="只保留最近 N 份本模块备份")
    prune.add_argument("--keep", type=_positive_int, help="覆盖 LEDU_BACKUP_KEEP")
    return parser


def _manager(args) -> BackupManager:
    config = BackupConfig.from_env()
    changes = {}
    if args.backup_dir:
        changes["backup_dir"] = Path(args.backup_dir)
    if args.upload_dirs is not None:
        changes["upload_dirs"] = tuple(Path(p) for p in args.upload_dirs)
    keep = getattr(args, "keep", None)
    if keep is not None:
        changes["keep"] = keep
    if changes:
        config = replace(config, **changes)
    return BackupManager(config)


def _tick(manager: BackupManager) -> dict | None:
    """到点才执行一次自动增量备份；同一时段最多执行一次。"""
    from datetime import datetime, timedelta, timezone
    from core.settings import get as settings_get, set as settings_set

    now = datetime.now(timezone(timedelta(hours=8)))
    due = next_due_slot(load_schedule(), settings_get("backup.last_auto"), now)
    if due is None:
        return None
    with backup_operation_lock():
        result = manager.create(label="auto", prune=True)
    settings_set("backup.last_auto", now.isoformat(timespec="seconds"), "scheduler")
    return result


def main() -> int:
    args = build_parser().parse_args()
    try:
        manager = _manager(args)
        if args.command == "tick":
            result = _tick(manager)
            if result is not None:
                print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "create":
            result = manager.create(
                label="auto",
                prune=not args.no_prune,
                incremental=False if args.full else None,
            )
        elif args.command == "list":
            result = manager.list()
        elif args.command == "restore":
            result = manager.restore(
                args.archive,
                restore_database=not args.attachments_only,
                restore_attachments=not args.database_only,
                safety_backup=not args.no_safety_backup,
            )
        else:
            result = {"pruned": manager.prune(), "keep": manager.config.keep}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BackupError, OSError) as ex:
        print(f"备份操作失败：{ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
