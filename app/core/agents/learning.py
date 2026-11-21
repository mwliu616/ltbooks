# LtBooks — core/agents/learning.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""自我进化：只学「你怎么做」，不学「什么是对的」。

学（映射 / 格式 / 期间 / 常用值）：顺丰→运输费 6240、摘要写法、默认币种
不学（判断口径 / 税率 / 科目性质 / 校验结论）：收入何时确认、8.25%/16.5%、该不该 PASS

循环：观察 → 归因 → 固化（≥5 次一致）→ 提示进化 → 可见 → 可回滚
"""
from __future__ import annotations

import json

from ..db import query, query_one, transaction

PROMOTE_SAMPLES = 5          # 固化阈值
OBSERVE_DAYS = 30            # 冷启动：前 30 天只观察
CONFUSE_LIMIT = 2            # 冲突 2 次即降级

# 只有这些前缀的场景才允许学习（判断类一律拒绝入库）
LEARNABLE_PREFIX = ("map:", "format:", "period:", "default:")

# 明确不学的情形，命中即丢弃
FORBIDDEN_KEYS = ("hkfrs15", "tax_rate", "tax_status", "verdict", "posting", "approval")


def learnable(scene_key: str) -> bool:
    k = (scene_key or "").lower()
    if any(f in k for f in FORBIDDEN_KEYS):
        return False
    return k.startswith(LEARNABLE_PREFIX)


def record(agent: str, scene_key: str, suggested, accepted, *, entity_id=1) -> bool:
    """记一次「AI 建议 → 用户最终采用」。不可学的场景直接丢弃。"""
    if not learnable(scene_key):
        return False
    adopted = 1 if str(suggested) == str(accepted) and suggested not in (None, "") else 0
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO ai_feedback
                (entity_id, agent, scene_key, suggested, accepted, adopted)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (entity_id, agent, scene_key, str(suggested)[:200],
                 str(accepted)[:200], adopted))
    return True


def candidates(entity_id=1):
    """统计每个场景的一致采纳率，够样本且够一致就返回。

    已被降级（paused）的场景不再作为候选：降级是「这条学得不对」的信号，
    要等人工在看板上重新启用，定时任务不能自己把它推回去。
    """
    rows = query("""SELECT scene_key,
                           COUNT(*) n,
                           SUM(adopted) ok,
                           MAX(created_at) last_at
                      FROM ai_feedback
                     WHERE entity_id=%s AND adopted=1
                       AND scene_key NOT IN (
                             SELECT scene_key FROM ai_learning
                              WHERE entity_id=%s AND status='paused')
                     GROUP BY scene_key
                    HAVING n >= %s""", (entity_id, entity_id, PROMOTE_SAMPLES))
    out = []
    for r in rows:
        # 取该场景下最一致的「采用值」
        top = query_one("""SELECT accepted, COUNT(*) n
                             FROM ai_feedback
                            WHERE entity_id=%s AND scene_key=%s AND adopted=1
                            GROUP BY accepted ORDER BY n DESC LIMIT 1""",
                        (entity_id, r["scene_key"]))
        if not top:
            continue
        share = int(top["n"]) / max(1, int(r["n"]))
        if share >= 0.8:
            out.append({"sceneKey": r["scene_key"], "learned": top["accepted"],
                        "samples": int(r["n"]), "share": round(share, 3)})
    return out


def promote(entity_id=1) -> list:
    """把够格的候选固化为规则。

    同场景已有规则时的三种情形：
    - active/observing 且学到的值相同 → 跳过（已经在用）
    - paused（刚被降级）且值相同        → 跳过，等人工确认后再启用，别自己复活
    - 值变了                          → 旧规则 retired，插入新版本（version+1）
    """
    promoted = []
    for c in candidates(entity_id):
        exist = query_one("""SELECT rule_id, learned, status, version FROM ai_learning
                              WHERE entity_id=%s AND scene_key=%s
                                AND status IN ('active','observing','paused')
                              ORDER BY rule_id DESC LIMIT 1""",
                          (entity_id, c["sceneKey"]))
        version = 1
        if exist:
            if str(exist["learned"]) == str(c["learned"]):
                continue
            version = int(exist["version"] or 1) + 1
            with transaction() as conn:
                with conn.cursor() as cur:
                    cur.execute("""UPDATE ai_learning SET status='retired'
                                    WHERE rule_id=%s""", (exist["rule_id"],))
        conf = "high" if c["samples"] >= 10 else "medium"
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO ai_learning
                    (entity_id, scene_key, scene_desc, learned, samples, confidence, status, version)
                    VALUES (%s,%s,%s,%s,%s,%s,'active',%s)""",
                    (entity_id, c["sceneKey"], scene_desc(c["sceneKey"]),
                     c["learned"], c["samples"], conf, version))
                rid = cur.lastrowid
        promoted.append({"ruleId": rid, **c, "version": version})
    return promoted


def scene_desc(key: str) -> str:
    kind, _, rest = key.partition(":")
    label = {"map": "科目映射", "format": "填写格式", "period": "期间习惯",
             "default": "常用默认值"}.get(kind, kind)
    return f"{label} · {rest[:200]}"


def active_rules(entity_id=1):
    rows = query("""SELECT rule_id, scene_key, learned, samples, confidence
                      FROM ai_learning
                     WHERE entity_id=%s AND status='active'
                     ORDER BY samples DESC LIMIT 100""", (entity_id,))
    return [dict(r) for r in rows]


def hints_text(entity_id=1, limit=20) -> str:
    """给智能体的「已学到」提示附注。"""
    rules = active_rules(entity_id)[:limit]
    if not rules:
        return ""
    lines = ["【已从该用户的历史操作中学到的偏好，优先采纳】"]
    for r in rules:
        lines.append(f"- {scene_desc(r['scene_key'])}：{r['learned']}（{r['samples']} 次）")
    return "\n".join(lines)


def set_status(rule_id: int, status: str, entity_id=1) -> bool:
    if status not in ("active", "paused", "retired"):
        return False
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE ai_learning SET status=%s
                            WHERE rule_id=%s AND entity_id=%s""",
                        (status, rule_id, entity_id))
    return True


def list_rules(entity_id=1):
    rows = query("""SELECT rule_id, scene_key, scene_desc, learned, samples,
                           confidence, status, version, updated_at
                      FROM ai_learning WHERE entity_id=%s
                     ORDER BY status='active' DESC, samples DESC LIMIT 200""", (entity_id,))
    return [dict(r) for r in rows]


def summary(entity_id=1):
    r = query_one("""SELECT
        SUM(status='active') act, SUM(status='observing') obs,
        SUM(status='paused') pau, COUNT(*) total
        FROM ai_learning WHERE entity_id=%s""", (entity_id,))
    fb = query_one("""SELECT COUNT(*) n, SUM(adopted) ok FROM ai_feedback
                       WHERE entity_id=%s""", (entity_id,))
    n = int((fb or {}).get("n") or 0)
    ok = int((fb or {}).get("ok") or 0)
    return {
        "rules": {"active": int(r["act"] or 0), "observing": int(r["obs"] or 0),
                  "paused": int(r["pau"] or 0), "total": int(r["total"] or 0)},
        "feedback": {"total": n, "adopted": ok,
                     "rate": round(ok / n, 3) if n else None},
    }
