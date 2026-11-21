# LtBooks — core/db.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""数据库访问：参数化查询、事务包裹、错误翻译。"""
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from config import DB

ER_DUP_ENTRY = 1062
ER_SIGNAL = 1644
ER_TRUNCATED = 1265
ER_TRUNCATED_WRONG_VALUE = 1292
ER_WRONG_VALUE = 1366


def connect():
    cfg = dict(DB)
    cfg["cursorclass"] = DictCursor
    cfg.pop("cursorclass", None)
    return pymysql.connect(cursorclass=DictCursor, autocommit=False,
                           host=DB["host"], port=DB["port"], user=DB["user"],
                           password=DB["password"], database=DB["database"],
                           charset="utf8mb4")


def query(sql, params=()):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def query_one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


@contextmanager
def transaction():
    conn = connect()
    try:
        conn.begin()
        yield conn
        conn.commit()
    except Exception as ex:
        conn.rollback()
        if isinstance(ex, DbError):
            raise
        # 把驱动层的数据库错误翻译成业务语义，避免报成 500 系统故障
        if ex.__class__.__module__.startswith(("pymysql", "MySQLdb")):
            raise describe_error(ex) from ex
        raise
    finally:
        conn.close()


class DbError(Exception):
    def __init__(self, kind, message, constraint=None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.constraint = constraint


def describe_error(e):
    """把数据库错误翻译为业务语义，避免把「会计上不允许」报成「系统故障」。"""
    code = getattr(e, "args", [None])[0]
    msg = str(e.args[-1]) if getattr(e, "args", None) else str(e)
    if code == ER_DUP_ENTRY:
        import re
        m = re.search(r"for key '([^']+)'", msg)
        return DbError("duplicate", f"重复记录：违反唯一约束 {m.group(1) if m else '唯一索引'}；已按「不重复入账」处理，未写入",
                       m.group(1) if m else None)
    if code in (ER_TRUNCATED, ER_TRUNCATED_WRONG_VALUE, ER_WRONG_VALUE):
        import re
        m = re.search(r"column '([^']+)'", msg)
        col = m.group(1) if m else "字段"
        return DbError("invalid_value", f"字段 {col} 的取值不合法，请检查选项后重试", col)
    if code == ER_SIGNAL:
        prefix = msg.split(":")[0].strip() if ":" in msg else ""
        kinds = {"IMMUTABLE": "immutable_violation", "INVALID_FLOW": "invalid_status_flow",
                 "AUDIT": "audit_requirement", "PERIOD_LOCK": "period_locked",
                 "RETENTION": "retention_violation"}
        # 触发器里的中文提示在部分 MySQL 版本上会变成 ???，且可能夹带内部表名。
        # 统一在这里换成面向用户的完整提示，避免把乱码抛到界面。
        clean = {
            "IMMUTABLE": "该单据已过账或已作废，不能直接修改或删除；请用冲销/作废流程处理。",
            "INVALID_FLOW": "单据状态流转不合法，请刷新页面后重试。",
            "AUDIT": "缺少操作人或操作时间，已拒绝写入。",
            "PERIOD_LOCK": "该会计期间已锁定或关闭，不能新增或修改分录；请先在「期间锁定」中解锁。",
            "RETENTION": "该记录仍在法定保存期内，不能删除。",
        }
        return DbError(kinds.get(prefix, "business_rule"),
                       clean.get(prefix, "该操作被会计规则拒绝，请检查单据状态后重试。"))
    return DbError("db_error", "数据库操作失败，请稍后重试；如持续出现请联系管理员。")
