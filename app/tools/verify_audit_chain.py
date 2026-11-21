#!/usr/bin/env python3
# LtBooks — tools/verify_audit_chain.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""审计哈希链校验：逐条重算 sha256(prev | 规范化载荷)。

用法：  ./venv/bin/python tools/verify_audit_chain.py [--entity 1]
退出码：0 完整；1 断链（会打印第一条不符的 seq_no 与原因）。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.audit import compute_hash, GENESIS, PAYLOAD_FIELDS   # noqa: E402
from core.db import query                                     # noqa: E402


def _detail(v):
    """库里 detail 是 JSON 文本；哈希时是 dict。两层都要能还原。"""
    if v is None or isinstance(v, dict):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return v


def _created(v):
    """created_at 在库里是 datetime，哈希时是 'YYYY-MM-DD HH:MM:SS.mmm' 字符串。"""
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="milliseconds")
    return str(v) if v is not None else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entity", type=int, default=0, help="只校验某个实体（默认全部）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    sql = "SELECT * FROM audit_log"
    args = ()
    if a.entity:
        sql += " WHERE entity_id=%s"
        args = (a.entity,)
    rows = query(sql + " ORDER BY entity_id, seq_no", args)
    if not rows:
        print("审计日志为空（空链视为完整）")
        return 0

    prev_by_entity, checked, bad = {}, 0, []
    for r in rows:
        eid = r["entity_id"]
        prev = prev_by_entity.get(eid, GENESIS)
        rec = {k: r.get(k) for k in PAYLOAD_FIELDS if k in r}
        rec["detail"] = _detail(rec.get("detail"))
        rec["created_at"] = _created(rec.get("created_at"))
        calc = compute_hash(rec, prev)
        checked += 1
        if calc != r["record_hash"]:
            bad.append((eid, r["seq_no"], r["action"],
                        "prev_hash 与上一条不接" if r["prev_hash"] != prev else "内容被改动"))
        prev_by_entity[eid] = r["record_hash"]

    print(f"校验 {checked} 条 · 实体 {len(prev_by_entity)} 个 · "
          + ("全部通过" if not bad else f"{len(bad)} 条不符"))
    for b in bad[:10]:
        print(f"  实体 {b[0]} seq {b[1]} {b[2]}：{b[3]}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
