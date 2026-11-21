# LtBooks — core/agent.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""DSH HKFRS 财务守门人智能体 — 调用层。

会计系统的校验一律由该智能体执行，本模块只做进程桥接与结果归一化，
**不复刻任何校验逻辑**，避免两套实现各自漂移。

智能体的四个工具（只读，白名单固定）：
  finance_journal_entry_check      分录机械校验
  finance_reconciliation_snapshot  对账快照
  finance_variance_bridge          差异桥接
  mysql_query                      只读查询（本系统未启用）

可用性要求：智能体不可用时**一律返回 FAIL**，绝不降级为「通过」。
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

from config import APP_DIR, ENV_FILE

# 部署包把只读校验预设放在后端 agent/；外部路径可通过环境变量显式覆盖。
PRESET = Path(os.environ.get("LEDU_AGENT_PRESET", str(APP_DIR / "agent")))
BRIDGE = Path(__file__).resolve().parent.parent / "bridge" / "agent-bridge.mjs"
_cfg_node = os.environ.get("LEDU_NODE_BIN")


def _load_env_node():
    """从 .env 读 node 路径（服务环境 PATH 精简，不能依赖 which）。"""
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("LEDU_NODE_BIN="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return None


NODE = _cfg_node or _load_env_node() or shutil.which("node") or "/usr/bin/node"
TIMEOUT = 20

TOOL_CHECK = "finance_journal_entry_check"
TOOL_RECON = "finance_reconciliation_snapshot"
TOOL_VARIANCE = "finance_variance_bridge"
AGENT_TOOL_WHITELIST = (TOOL_CHECK, TOOL_RECON, TOOL_VARIANCE, "mysql_query")


class AgentUnavailable(Exception):
    """智能体不可用（未安装、Node 缺失、超时、返回异常）。"""


def _run(tool: str, args: dict) -> dict:
    if not BRIDGE.is_file():
        raise AgentUnavailable(f"桥接脚本缺失：{BRIDGE}")
    if not (PRESET / "index.js").is_file():
        raise AgentUnavailable(f"智能体未安装：{PRESET}")
    env = dict(os.environ, LEDU_AGENT_PRESET=str(PRESET))
    try:
        p = subprocess.run(
            [NODE, str(BRIDGE), tool],
            input=json.dumps(args, ensure_ascii=False),
            capture_output=True, text=True, timeout=TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        raise AgentUnavailable(f"智能体调用超时（>{TIMEOUT}s）：{tool}")
    except FileNotFoundError:
        raise AgentUnavailable("找不到 node，无法调用智能体")

    raw = (p.stdout or "").strip()
    if not raw:
        raise AgentUnavailable(f"智能体无输出：{p.stderr.strip()[:200]}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise AgentUnavailable(f"智能体返回非 JSON：{raw[:200]}")

    if isinstance(data, dict) and data.get("error"):
        if data["error"] == "TOOL_NOT_ALLOWED":
            raise AgentUnavailable(data.get("message") or "工具不在白名单")
        raise AgentUnavailable(f"{data.get('error')}: {data.get('message')}")
    return data


def check_entry(entry: dict) -> dict:
    """调用智能体的 finance_journal_entry_check。

    返回结构与智能体一致，另加 agent / ranBy 标记，便于审计追踪。
    """
    try:
        res = _run(TOOL_CHECK, {"entry": entry})
    except AgentUnavailable as e:
        return {
            "task": "journal_entry_check",
            "verdict": "FAIL",
            "blockedReasons": [f"智能体不可用：{e}"],
            "reviewReasons": [],
            "balanced": None,
            "agent": "hkfrs-finance-guardian",
            "authorization": "NEVER_AUTHORIZES_POSTING",
            "disclaimer": "智能体不可用，校验未执行 —— 按最严处理，禁止过账",
            "unavailable": True,
        }
    res["agent"] = "hkfrs-finance-guardian"
    res["ranBy"] = "dsh-agent-bridge"
    return res


def reconciliation_snapshot(snapshot: dict) -> dict:
    res = _run(TOOL_RECON, {"snapshot": snapshot})
    res["agent"] = "hkfrs-finance-guardian"
    res["ranBy"] = "dsh-agent-bridge"
    return res


def variance_bridge(bridge: dict) -> dict:
    res = _run(TOOL_VARIANCE, {"bridge": bridge})
    res["agent"] = "hkfrs-finance-guardian"
    res["ranBy"] = "dsh-agent-bridge"
    return res


def agent_info() -> dict:
    """智能体状态与工具清单（供界面与健康检查）。"""
    try:
        p = subprocess.run([NODE, str(BRIDGE), "--list"], capture_output=True,
                           text=True, timeout=TIMEOUT,
                           env=dict(os.environ, LEDU_AGENT_PRESET=str(PRESET)))
        data = json.loads(p.stdout)
        return {"available": True, "preset": data.get("preset"),
                "tools": [t["name"] for t in data.get("tools", [])],
                "whitelist": list(AGENT_TOOL_WHITELIST)}
    except Exception as e:
        return {"available": False, "error": str(e),
                "preset": str(PRESET), "whitelist": list(AGENT_TOOL_WHITELIST)}
