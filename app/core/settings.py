# LtBooks — core/settings.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""运行期设置：存在 app_settings 表里，优先于环境变量的只有「可改的那些」。

为什么要有：大模型的服务地址、模型名、密钥原来只能改 .env 再重启，
换个模型要动服务器。现在界面上能改，改完立刻生效。

优先级：**环境变量 > 数据库**。原因是运维在 .env 里写死的东西不应该被界面悄悄覆盖；
数据库里留给「没在环境里配置」或「临时切换模型」的场景。
"""
from __future__ import annotations

from .db import query, query_one, transaction

_CACHE: dict = {}


def get(key: str, default: str = "") -> str:
    if key in _CACHE:
        return _CACHE[key]
    row = query_one("SELECT v FROM app_settings WHERE k=%s", (key,))
    val = (row or {}).get("v")
    val = default if val is None else str(val)
    _CACHE[key] = val
    return val


def get_many(*keys: str) -> dict:
    return {k: get(k) for k in keys}


def set(key: str, value: str, actor: str = "system") -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO app_settings (k, v, updated_by) VALUES (%s,%s,%s)
                           ON DUPLICATE KEY UPDATE v=VALUES(v), updated_by=VALUES(updated_by)""",
                        (key[:64], value, actor[:64]))
    _CACHE[key] = value


def all_settings() -> dict:
    return {r["k"]: r["v"] for r in query("SELECT k, v FROM app_settings")}


def clear_cache() -> None:
    _CACHE.clear()


# ---- 大模型（这一组键名固定，界面与代码共用） ---------------------------------
LLM_KEYS = ("llm.base", "llm.model", "llm.api_key", "llm.temperature")


def llm_config() -> dict:
    """当前生效的模型配置。

    优先级：
      · 配了服务商 —— 用「当前」那一个（界面可切换）
      · 没配服务商 —— 退回旧的单条设置 / 环境变量
    """
    from config import env

    rows = _provider_rows()
    if rows:
        r = rows[0]                        # 已按 is_active DESC 排序
        try:
            temp = float(r.get("temperature") or 0.2)
        except (TypeError, ValueError):
            temp = 0.2
        return {"base": str(r.get("base") or "").rstrip("/"),
                "model": str(r.get("model") or "deepseek-chat"),
                "apiKey": str(r.get("api_key") or ""),
                "temperature": temp,
                "fromEnv": False,
                "keyFromEnv": False,
                "source": "provider" if str(r.get("api_key") or "") else "none",
                "providerId": int(r["provider_id"]),
                "providerName": str(r.get("name") or ""),
                "providerCount": len(rows)}

    base = get("llm.base") or env("LEDU_LLM_BASE") or "https://api.deepseek.com"
    model = get("llm.model") or env("LEDU_LLM_MODEL") or "deepseek-chat"
    key = get("llm.api_key") or env("LEDU_LLM_API_KEY") or ""
    try:
        temp = float(env("LEDU_LLM_TEMPERATURE") or get("llm.temperature") or 0.2)
    except (TypeError, ValueError):
        temp = 0.2
    return {"base": base.rstrip("/"), "model": model, "apiKey": key, "temperature": temp,
            "fromEnv": bool(env("LEDU_LLM_API_KEY") or env("LEDU_LLM_MODEL")),
            "keyFromEnv": bool(env("LEDU_LLM_API_KEY")),
            "source": "settings" if get("llm.api_key") else ("env" if env("LEDU_LLM_API_KEY") else "none"),
            "providerId": 0, "providerName": "", "providerCount": 0}


def set_model(model: str, actor: str = "system") -> None:
    """只切模型：地址与密钥保持不变。"""
    set("llm.model", model.strip(), actor)
    clear_cache()


# ---- 大模型服务商（可配多个，选一个当前生效） ---------------------------------
LLM_PROVIDER_FIELDS = ("name", "base", "model", "api_key", "temperature", "is_active")


def mask_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    return (key[:4] + "…" + key[-4:]) if len(key) >= 12 else "已设置"


def _provider_rows() -> list:
    """全部服务商；表还没建（未跑迁移）时返回空列表，退回旧的单配置。"""
    cached = _CACHE.get("__llm_providers")
    if cached is not None:
        return cached
    try:
        rows = query("""SELECT provider_id, name, base, api_key, model, temperature, is_active
                        FROM llm_providers ORDER BY is_active DESC, provider_id""")
    except Exception:
        rows = []
    _CACHE["__llm_providers"] = rows
    return rows


def provider_list() -> list:
    """给界面用：密钥只回掩码。"""
    out = []
    for r in _provider_rows():
        key = str(r.get("api_key") or "")
        out.append({
            "providerId": int(r["provider_id"]),
            "name": str(r.get("name") or ""),
            "base": str(r.get("base") or ""),
            "model": str(r.get("model") or ""),
            "temperature": float(r.get("temperature") or 0.2),
            "active": bool(int(r.get("is_active") or 0)),
            "keySet": bool(key),
            "keyMask": mask_key(key),
        })
    return out


def provider_by_id(provider_id: int) -> dict | None:
    for r in _provider_rows():
        if int(r["provider_id"]) == int(provider_id):
            return r
    return None


def save_provider(provider_id, name, base, model, api_key, temperature,
                  actor: str = "system") -> int:
    """新增或更新服务商；api_key 为空表示保持原密钥。新增且无其它服务商时自动设为当前。"""
    name = name.strip()
    base = base.strip().rstrip("/")
    model = model.strip()
    api_key = (api_key or "").strip()
    try:
        temp = float(temperature)
    except (TypeError, ValueError):
        temp = 0.2
    with transaction() as conn:
        with conn.cursor() as cur:
            if provider_id:
                if api_key:
                    cur.execute("""UPDATE llm_providers SET name=%s, base=%s, model=%s,
                                   api_key=%s, temperature=%s WHERE provider_id=%s""",
                                (name, base, model, api_key, temp, int(provider_id)))
                else:
                    cur.execute("""UPDATE llm_providers SET name=%s, base=%s, model=%s,
                                   temperature=%s WHERE provider_id=%s""",
                                (name, base, model, temp, int(provider_id)))
                pid = int(provider_id)
            else:
                cur.execute("SELECT COUNT(*) AS n FROM llm_providers")
                first = int((cur.fetchone() or {}).get("n") or 0) == 0
                cur.execute("""INSERT INTO llm_providers (name, base, api_key, model,
                               temperature, is_active) VALUES (%s,%s,%s,%s,%s,%s)""",
                            (name, base, api_key or None, model, temp, 1 if first else 0))
                pid = int(cur.lastrowid)
    clear_cache()
    return pid


def activate_provider(provider_id: int) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE llm_providers SET is_active=0")
            cur.execute("UPDATE llm_providers SET is_active=1 WHERE provider_id=%s",
                        (int(provider_id),))
    clear_cache()


def delete_provider(provider_id: int) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM llm_providers WHERE provider_id=%s", (int(provider_id),))
            cur.execute("SELECT provider_id FROM llm_providers ORDER BY provider_id LIMIT 1")
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE llm_providers SET is_active=1 WHERE provider_id=%s",
                            (int(row["provider_id"]),))
    clear_cache()
