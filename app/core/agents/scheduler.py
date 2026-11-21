# LtBooks — core/agents/scheduler.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""学习固化定时任务：把「你怎么做」固化成规则，把不一致的降级。

边界（与 learning.py 一致，不得放宽）：
- 只学偏好类场景（map: / format: / period: / default:），判断类一律不学
- 冷启动 30 天只观察不固化（没有足够历史就先别下结论）
- 固化门槛：同一场景 ≥5 次采纳、一致率 ≥80%
- 同一场景近期出现 ≥2 次「没采纳」→ 规则降级为 paused，交回人工
- 每一次固化与降级都写审计链，规则可回滚（set_status）

用法：
    python run_learning.py             # 跑一次（cron 每天 02:30 HKT）
    python run_learning.py --dry-run   # 只报告，不写库
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..db import query, query_one, transaction
from . import learning


def _now() -> datetime:
    return datetime.now()


def observation_state(entity_id: int = 1) -> dict:
    """冷启动判断：第一条反馈到现在是否已满 OBSERVE_DAYS 天。"""
    row = query_one("""SELECT MIN(created_at) AS first_at, COUNT(*) AS n
                         FROM ai_feedback WHERE entity_id=%s""", (entity_id,))
    first_at = (row or {}).get("first_at")
    total = int((row or {}).get("n") or 0)
    if not first_at:
        return {"ready": False, "days": 0, "need": learning.OBSERVE_DAYS,
                "firstAt": None, "total": 0}
    if isinstance(first_at, str):
        first_at = datetime.fromisoformat(first_at)
    days = (_now() - first_at).days
    return {"ready": days >= learning.OBSERVE_DAYS, "days": days,
            "need": learning.OBSERVE_DAYS,
            "firstAt": first_at.isoformat(sep=" ", timespec="seconds"),
            "total": total}


def conflicts(entity_id: int = 1, days: int = 30) -> list:
    """找出「固化了但最近老被推翻」的规则。"""
    out = []
    for r in learning.active_rules(entity_id):
        key = r["scene_key"]
        hit = query_one("""SELECT COUNT(*) n FROM ai_feedback
                            WHERE entity_id=%s AND scene_key=%s AND adopted=0
                              AND created_at >= %s""",
                        (entity_id, key, _now() - timedelta(days=days)))
        n = int((hit or {}).get("n") or 0)
        if n >= learning.CONFUSE_LIMIT:
            out.append({"ruleId": r["rule_id"], "sceneKey": key,
                        "learned": r["learned"], "rejected": n, "days": days})
    return out


def run_daily(entity_id: int = 1, actor: str = "learning-bot", dry_run: bool = False) -> dict:
    """每日固化：先降级冲突规则，再固化够格的候选。"""
    obs = observation_state(entity_id)
    result = {
        "entityId": entity_id, "at": _now().isoformat(sep=" ", timespec="seconds"),
        "observation": obs, "demoted": [], "promoted": [], "dryRun": dry_run,
        "note": "",
    }

    # 1) 冲突降级：不做「先固化再打架」，先把不确定的收回去
    for c in conflicts(entity_id):
        result["demoted"].append(c)
        if not dry_run:
            learning.set_status(c["ruleId"], "paused", entity_id)
            with transaction() as conn:
                from ..service import append_audit
                append_audit(conn, {
                    "entity_id": entity_id, "actor": actor,
                    "action": "ai_learning.demote", "object_type": "ai_learning",
                    "object_id": str(c["ruleId"]),
                    "detail": {"sceneKey": c["sceneKey"], "learned": c["learned"],
                               "rejected": c["rejected"], "windowDays": c["days"],
                               "reason": "近期多次未被采纳，降级回观察"},
                })

    # 2) 票据识别规则固化：纠正样本来自人明确改过的字段，不受冷启动观察期约束
    try:
        from . import extractor_learning
        ext = extractor_learning.promote(entity_id)
        if ext:
            result["extractorRules"] = ext
            with transaction() as conn:
                from ..service import append_audit
                append_audit(conn, {
                    "entity_id": entity_id, "actor": actor,
                    "action": "extractor_rule.promote", "object_type": "extract_rules",
                    "object_id": ",".join(str(x["ruleId"]) for x in ext),
                    "detail": {"count": len(ext), "rules": ext},
                })
    except Exception as ex:          # 学习失败不影响主流程
        result["extractorRulesError"] = str(ex)

    # 3) 偏好固化：冷启动期内一律不动
    if not obs["ready"]:
        result["note"] = (f"观察期未满（{obs['days']}/{obs['need']} 天），本次只降级不固化")
        return result

    cands = learning.candidates(entity_id)
    if not cands:
        result["note"] = "没有达到固化门槛的候选"
        return result
    if dry_run:
        result["promoted"] = cands
        result["note"] = "dry-run：只报告，未写库"
        return result

    promoted = learning.promote(entity_id)
    result["promoted"] = promoted
    if promoted:
        with transaction() as conn:
            from ..service import append_audit
            append_audit(conn, {
                "entity_id": entity_id, "actor": actor,
                "action": "ai_learning.promote", "object_type": "ai_learning",
                "object_id": ",".join(str(p["ruleId"]) for p in promoted),
                "detail": {"count": len(promoted),
                           "rules": [{"sceneKey": p["sceneKey"], "learned": p["learned"],
                                      "samples": p["samples"]} for p in promoted]},
            })
        result["note"] = f"固化 {len(promoted)} 条"
    else:
        result["note"] = "候选已固化过，本次无新增"
    return result


def history(entity_id: int = 1, limit: int = 20) -> list:
    """最近的固化/降级动作（从审计链读，不另建日志表）。"""
    rows = query("""SELECT log_id, action, object_id, detail, created_at, actor
                      FROM audit_log
                     WHERE entity_id=%s AND action IN ('ai_learning.promote','ai_learning.demote')
                     ORDER BY log_id DESC LIMIT %s""", (entity_id, limit))
    out = []
    for r in rows:
        d = r["detail"]
        if isinstance(d, str):
            import json
            try:
                d = json.loads(d)
            except Exception:
                d = {}
        out.append({"at": r["created_at"].isoformat(sep=" ", timespec="seconds")
                    if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                    "action": r["action"], "actor": r["actor"],
                    "objectId": r["object_id"], "detail": d})
    return out
