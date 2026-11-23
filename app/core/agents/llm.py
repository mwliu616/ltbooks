# LtBooks — core/agents/llm.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""大模型接入层：OpenAI 兼容的 chat/completions + function calling。

与 DSH 用的是同一个 API（LEDU_LLM_BASE / LEDU_LLM_MODEL / LEDU_LLM_API_KEY），
只是把「工具调度循环」从 DSH 搬进了本系统。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from config import env

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
TIMEOUT = 60
RETRIES = 3


class LLMError(Exception):
    pass


def _cfg():
    """环境变量优先，其次界面里保存的配置（系统设置 → 大模型）。"""
    from ..settings import llm_config
    c = llm_config()
    if not c["apiKey"]:
        raise LLMError("未配置大模型 API Key：环境变量 LEDU_LLM_API_KEY 或 系统设置 → 大模型")
    return c["apiKey"], (c["base"] or DEFAULT_BASE).rstrip("/"), (c["model"] or DEFAULT_MODEL)


def _post(url, payload, headers, timeout=TIMEOUT):
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def chat(messages, tools=None, *, temperature=0.2, max_tokens=1600,
         model=None, json_mode=False, timeout=TIMEOUT, cfg=None):
    """一次对话调用。返回 message 字典（可能带 tool_calls）。

    cfg 可显式传入 (key, base, model)，用于「测试某个服务商」；
    不传则用当前生效的配置。
    失败重试 3 次（指数退避）；仍失败抛 LLMError，由上层降级。
    """
    key, base, default_model = cfg or _cfg()
    payload = {
        "model": model or default_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if json_mode and not tools:
        payload["response_format"] = {"type": "json_object"}

    last = None
    for attempt in range(RETRIES):
        try:
            data = _post(base + "/chat/completions", payload,
                         {"Authorization": "Bearer " + key}, timeout=timeout)
            msg = data["choices"][0]["message"]
            usage = data.get("usage") or {}
            return {
                "message": msg,
                "tokens": int(usage.get("total_tokens") or 0),
                "model": payload["model"],
            }
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
            if e.code < 500 and e.code != 429:
                break
        except Exception as e:                      # 网络 / 超时 / 解析
            last = str(e)
        time.sleep(0.6 * (2 ** attempt))
    raise LLMError(last or "模型调用失败")


def available() -> bool:
    try:
        _cfg()
        return True
    except LLMError:
        return False
