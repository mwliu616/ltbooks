#!/usr/bin/env python3
# LtBooks — tools/create_admin.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""LtBooks 干净安装的管理员初始化工具。

仅在指定账号不存在时创建管理员；口令由系统随机生成并只写入权限为 600 的
本地凭据文件。重复执行不会重置既有口令，也不会覆盖既有凭据文件。
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import auth as authcore  # noqa: E402
from core.db import query_one  # noqa: E402


def main() -> int:
    username = os.environ.get("LTBOOKS_ADMIN_USER", "admin").strip() or "admin"
    if not username.replace("_", "").replace("-", "").isalnum() or len(username) > 64:
        raise SystemExit("管理员用户名只能包含字母、数字、横线和下划线，且最长 64 字符")
    if not query_one("SELECT entity_id FROM entities ORDER BY entity_id LIMIT 1"):
        raise SystemExit("尚未初始化会计实体，不能创建管理员")
    if authcore.get_user(username):
        print(f"管理员 {username} 已存在；未重置口令。")
        return 0

    password = os.environ.get("LTBOOKS_ADMIN_PASSWORD") or secrets.token_urlsafe(18)
    authcore.create_user(username, "LtBooks Administrator", password, "admin")
    target = Path(os.environ.get(
        "LTBOOKS_CREDENTIALS_FILE", str(ROOT / "storage" / "initial-credentials.txt")
    ))
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "LtBooks Ver 1.0 initial administrator\n"
        f"Username: {username}\n"
        f"Password: {password}\n"
        "The password must be changed after the first login.\n"
        "Delete this file after securely storing the credentials.\n"
    )
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"管理员已创建，但凭据文件已存在，未覆盖：{target}")
        return 0
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    target.chmod(0o600)
    print(f"管理员 {username} 已创建；首次登录口令保存在 {target}（权限 600）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
