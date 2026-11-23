# LtBooks — core/auth.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""认证：PBKDF2-HMAC-SHA256 口令、会话校验、登录节流。
口令与令牌只在服务端处理，绝不下发到前端。"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from .db import query, query_one, transaction

ITERATIONS = 260000
SESSION_TTL_HOURS = 12
MAX_FAILED = 5
LOCK_MINUTES = 15
ROLES = ("admin", "accountant", "auditor")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, expected = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), expected)
    except Exception:
        return False


def get_user(username: str):
    return query_one("SELECT * FROM users WHERE username=%s", (username,))


def get_user_by_id(user_id: int):
    return query_one("SELECT * FROM users WHERE user_id=%s", (user_id,))


def list_users():
    return query("""SELECT user_id, username, display_name, role, status, must_change,
                           last_login_at, created_at FROM users ORDER BY user_id""")


def create_user(username: str, display_name: str, password: str, role: str):
    if role not in ROLES:
        raise ValueError(f"非法角色：{role}")
    if len(password) < 10:
        raise ValueError("口令至少 10 位")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE username=%s", (username,))
            if cur.fetchone():
                raise ValueError("用户名已存在")
            cur.execute("""INSERT INTO users (username, display_name, password_hash, role, must_change)
                           VALUES (%s,%s,%s,%s,1)""",
                        (username, display_name, hash_password(password), role))
            return cur.lastrowid


def change_password(user_id: int, new_password: str):
    if len(new_password) < 10:
        raise ValueError("口令至少 10 位")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE users SET password_hash=%s, must_change=0
                            WHERE user_id=%s""", (hash_password(new_password), user_id))


def update_user(user_id: int, display_name: str, role: str, status: str, operator: str = ""):
    """修改显示名、角色、状态。内置 admin 必须保持管理员且启用。"""
    if role not in ROLES:
        raise ValueError(f"非法角色：{role}")
    if status not in ("active", "disabled"):
        raise ValueError("非法状态")
    u = query_one("SELECT user_id, username, role FROM users WHERE user_id=%s", (user_id,))
    if not u:
        raise ValueError("用户不存在")
    if u["username"] == "admin" and (role != "admin" or status != "active"):
        raise ValueError("内置 admin 账号不能降级或停用")
    if operator and u["username"] == operator and status != "active":
        raise ValueError("不能停用当前登录账号")
    if u["role"] == "admin" and role != "admin":
        n = query_one("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND status='active'")
        if int(n["n"]) <= 1:
            raise ValueError("系统至少保留一个管理员")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE users SET display_name=%s, role=%s, status=%s
                            WHERE user_id=%s""",
                        (display_name or u["username"], role, status, user_id))
            if status == "disabled":
                cur.execute("DELETE FROM user_sessions WHERE user_id=%s", (user_id,))


def delete_user(user_id: int, operator: str = ""):
    """删除用户。内置 admin、当前登录账号、最后一个管理员都不允许删除。"""
    u = query_one("SELECT user_id, username, role FROM users WHERE user_id=%s", (user_id,))
    if not u:
        raise ValueError("用户不存在")
    if u["username"] == "admin":
        raise ValueError("内置 admin 账号不能删除")
    if operator and u["username"] == operator:
        raise ValueError("不能删除当前登录账号")
    if u["role"] == "admin":
        n = query_one("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND status='active'")
        if int(n["n"]) <= 1:
            raise ValueError("系统至少保留一个管理员")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_sessions WHERE user_id=%s", (user_id,))
            cur.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
    return u["username"]


def login(username: str, password: str, ip: str = None, ua: str = None):
    """返回 (ok, payload)。失败不区分「用户不存在」与「口令错」，避免枚举。"""
    u = get_user(username)
    now = datetime.now()

    if not u:
        return False, {"error": "用户名或口令不正确"}

    if u["status"] != "active":
        return False, {"error": "账号已停用，请联系管理员"}

    if u["locked_until"] and u["locked_until"] > now:
        return False, {"error": "尝试次数过多，账号临时锁定，请稍后再试"}

    if not verify_password(password, u["password_hash"]):
        with transaction() as conn:
            with conn.cursor() as cur:
                n = u["failed_count"] + 1
                lock = (now + timedelta(minutes=LOCK_MINUTES)) if n >= MAX_FAILED else None
                cur.execute("UPDATE users SET failed_count=%s, locked_until=%s WHERE user_id=%s",
                            (n, lock, u["user_id"]))
        return False, {"error": "用户名或口令不正确"}

    sid = secrets.token_hex(32)
    csrf = secrets.token_hex(32)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE users SET failed_count=0, locked_until=NULL, last_login_at=NOW(3)
                            WHERE user_id=%s""", (u["user_id"],))
            cur.execute("""INSERT INTO user_sessions
                (session_id, user_id, csrf_token, ip, user_agent, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                        (sid, u["user_id"], csrf, ip, (ua or "")[:255],
                         now + timedelta(hours=SESSION_TTL_HOURS)))
    return True, {
        "sessionId": sid, "csrfToken": csrf,
        "user": {"id": u["user_id"], "username": u["username"],
                 "displayName": u["display_name"], "role": u["role"],
                 "mustChange": bool(u["must_change"])},
    }


def resolve_session(session_id: str):
    if not session_id or len(session_id) != 64:
        return None
    row = query_one("""SELECT s.session_id, s.csrf_token, s.expires_at,
                              u.user_id, u.username, u.display_name, u.role, u.status, u.must_change
                         FROM user_sessions s JOIN users u ON u.user_id = s.user_id
                        WHERE s.session_id=%s""", (session_id,))
    if not row:
        return None
    if row["expires_at"] < datetime.now():
        delete_session(session_id)
        return None
    if row["status"] != "active":
        return None
    return row


def touch_session(session_id: str):
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE user_sessions SET last_seen_at=NOW(3) WHERE session_id=%s",
                        (session_id,))


def delete_session(session_id: str):
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_sessions WHERE session_id=%s", (session_id,))


def purge_expired():
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_sessions WHERE expires_at < NOW(3)")
