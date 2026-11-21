# LtBooks — core/audit.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""审计日志哈希链：record_hash = sha256(prev_hash | 规范化载荷)。"""
import hashlib
import json
from datetime import date, datetime

GENESIS = "0" * 64
PAYLOAD_FIELDS = ("entity_id", "seq_no", "actor", "actor_role", "action",
                  "object_type", "object_id", "detail", "client_ip", "created_at")


def canonical(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (date, datetime)):
        return json.dumps(v.isoformat()[:10] if not isinstance(v, datetime) else v.isoformat(sep=" ", timespec="milliseconds"), ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(canonical(x) for x in v) + "]"
    if isinstance(v, dict):
        # 与 Node 侧 canonicalize 对齐：只过滤 undefined（Python 无此概念），
        # 显式的 null 必须参与哈希，否则链会与既有记录失配。
        keys = sorted(v.keys())
        return "{" + ",".join(f"{json.dumps(k, ensure_ascii=False)}:{canonical(v[k])}" for k in keys) + "}"
    return "null"


def payload_of(entry):
    return {k: v for k, v in (entry or {}).items() if k not in ("record_hash", "prev_hash")}


def compute_hash(record, prev_hash):
    return hashlib.sha256(f"{prev_hash}|{canonical(record)}".encode()).hexdigest()


def append_record(record, prev_hash=None):
    prev = prev_hash or GENESIS
    payload = payload_of(record)
    return dict(payload, prev_hash=prev, record_hash=compute_hash(payload, prev))


def verify_chain(chain):
    if not chain:
        return {"valid": True, "checked": 0, "brokenAt": None, "reason": "空链，视为完整", "details": []}
    details, prev = [], GENESIS
    for i, e in enumerate(chain):
        if not isinstance(e, dict):
            return {"valid": False, "checked": i, "brokenAt": i, "reason": f"第 {i+1} 条不是对象", "details": details}
        if i == 0 and e.get("prev_hash") != GENESIS:
            return {"valid": False, "checked": i, "brokenAt": i, "reason": f"创世记录 prev_hash 应为 {GENESIS}", "details": details}
        if i > 0 and e.get("prev_hash") != prev:
            return {"valid": False, "checked": i, "brokenAt": i, "reason": f"第 {i+1} 条 prev_hash 与上一条 record_hash 不连续", "details": details}
        if compute_hash(payload_of(e), e.get("prev_hash")) != e.get("record_hash"):
            return {"valid": False, "checked": i, "brokenAt": i, "reason": f"第 {i+1} 条内容与其 record_hash 不符（记录已被改动）", "details": details}
        prev = e["record_hash"]
    return {"valid": True, "checked": len(chain), "brokenAt": None,
            "reason": f"链完整，共校验 {len(chain)} 条", "details": details, "head": prev}
