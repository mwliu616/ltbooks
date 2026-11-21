# LtBooks — core/numbering.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""统一单据编号：公司缩写 + 功能缩写 + 日期 + 当日份数。

例：LEDU-INV-20261108-001 = 乐度 2026-11-08 的第 1 份销售发票。

- 公司缩写取自 entities.entity_code（LEDU-HK → LEDU），可按实体不同而不同
- 功能缩写区分单据类型，各类独立编号
- 份数按 (实体, 日期, 功能) 原子递增，并发下不会重号
"""
from datetime import date

from .money import parse_date

# 功能缩写：单据类型 → 代码
KINDS = {
    "invoice": "INV",    # 销售发票
    "bill": "BILL",      # 采购发票
    "expense": "EXP",    # 费用
    "receipt": "RCT",    # 收款
    "payment": "PMT",    # 付款
    "journal": "JE",     # 日记账分录
    "contract": "CT",    # 收入合同
    "reval": "REV",      # 期末重估
    "opening": "OPN",    # 期初余额
    "quote": "QT",       # 报价单（不进总账，仅销售流程）
    "credit": "CN",      # 贷记单（红字单）
    "po": "PO",          # 采购订单（不进总账，仅采购流程）
    "so": "SO",          # 销售订单（不进总账，仅销售流程）
    "grn": "GRN",        # 采购收货单
    "dln": "DLN",        # 销售发货单
}


def company_prefix(conn, entity_id: int) -> str:
    """公司缩写：实体编码取「-」前的部分；缺失时退回 LEDU。"""
    with conn.cursor() as cur:
        cur.execute("SELECT entity_code FROM entities WHERE entity_id=%s", (entity_id,))
        row = cur.fetchone()
    code = str((row or {}).get("entity_code") or "").strip().upper()
    if not code:
        return "LEDU"
    return code.split("-")[0][:8] or "LEDU"


def _kind_code(kind: str) -> str:
    k = str(kind or "").strip()
    if not k:
        return "DOC"
    return KINDS.get(k.lower(), k.upper()[:4])


def format_no(prefix: str, kind: str, d: date, seq: int) -> str:
    return f"{prefix}-{_kind_code(kind)}-{d.strftime('%Y%m%d')}-{seq:03d}"


def next_no(conn, entity_id: int, doc_date, kind: str = "journal", prefix: str | None = None) -> str:
    """取下一个编号。必须在调用方的事务内执行。"""
    d = parse_date(doc_date) or date.today()
    scope = _kind_code(kind)
    pre = prefix or company_prefix(conn, entity_id)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO doc_sequences (entity_id, doc_date, scope, last_seq)
                       VALUES (%s, %s, %s, 1)
                       ON DUPLICATE KEY UPDATE last_seq = last_seq + 1""",
                    (entity_id, d.isoformat(), scope))
        cur.execute("""SELECT last_seq FROM doc_sequences
                        WHERE entity_id=%s AND doc_date=%s AND scope=%s""",
                    (entity_id, d.isoformat(), scope))
        seq = int(cur.fetchone()["last_seq"])
    return format_no(pre, kind, d, seq)


def peek_no(conn, entity_id: int, doc_date, kind: str = "journal", prefix: str | None = None) -> str:
    """预览下一个编号（不占用序号），供表单显示。"""
    d = parse_date(doc_date) or date.today()
    scope = _kind_code(kind)
    pre = prefix or company_prefix(conn, entity_id)
    with conn.cursor() as cur:
        cur.execute("""SELECT last_seq FROM doc_sequences
                        WHERE entity_id=%s AND doc_date=%s AND scope=%s""",
                    (entity_id, d.isoformat(), scope))
        row = cur.fetchone()
        seq = (int(row["last_seq"]) if row else 0) + 1
    return format_no(pre, kind, d, seq)
