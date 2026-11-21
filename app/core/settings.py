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
      · 服务地址与密钥 —— **环境变量优先**（运维写死在 .env 的东西不被界面悄悄覆盖）
      · 模型名         —— **界面优先**（顶部切换是明确的人工动作，必须立刻生效）
    """
    from config import env

    # 界面设置优先、环境变量兜底：配置集中放在「设置」里，
    # .env 只是首次部署时的初始值，界面上改过就以界面为准。
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
            "source": "settings" if get("llm.api_key") else ("env" if env("LEDU_LLM_API_KEY") else "none")}


def set_model(model: str, actor: str = "system") -> None:
    """只切模型：地址与密钥保持不变。"""
    set("llm.model", model.strip(), actor)
    clear_cache()
