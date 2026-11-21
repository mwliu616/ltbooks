# LtBooks — core/agents/runtime.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""智能体运行时：多轮工具调用 + 审计落库 + 降级。

与 DSH 的区别：这里自己实现「规划 → 调工具 → 观察 → 再规划」的循环，
不再依赖 Node 进程。所有调用都写 ai_run，可回溯。
"""
from __future__ import annotations

import json
import time

from decimal import Decimal

from ..db import query, transaction
from . import learning, llm, registry, toolbox, tools_write

MAX_ROUNDS = 6
MAX_SECONDS = 90


def _enc(o):
    """兜底编码：Decimal → float，日期 → ISO。"""
    if isinstance(o, Decimal):
        return float(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def _audit(entity_id, agent, actor, scene, text_in, output, verdict,
           tokens, latency_ms, model, error, tools_used):
    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO ai_run
                    (entity_id, agent, trigger_by, scene, input, tools_used, output,
                     verdict, tokens, latency_ms, model, error)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (entity_id, agent, actor, scene, (text_in or "")[:60000],
                     json.dumps(tools_used, ensure_ascii=False)[:4000],
                     (output or "")[:60000], verdict, tokens, latency_ms,
                     model, (error or "")[:400]))
                return cur.lastrowid
    except Exception:
        return None


def _fail(entity_id, agent, actor, scene, user_text, error, tokens, started, model, tools_used, writes):
    run_id = _audit(entity_id, agent, actor, scene, user_text, "", "FAIL",
                    tokens, int((time.time() - started) * 1000), model, error, tools_used)
    return {"ok": False, "error": error, "runId": run_id,
            "tokens": tokens, "tools": tools_used, "model": model, "writes": writes}


def run(agent: str, user_text: str, *, actor="owner", scene=None,
        context=None, entity_id=1, temperature=0.2, max_tokens=1600,
        allow_write: bool = True, role: str = "admin"):
    """跑一个智能体，返回 {ok, text, verdict, tokens, runId, tools, error}。"""
    if agent not in registry.AGENTS:
        return {"ok": False, "error": f"未知智能体：{agent}"}

    started = time.time()
    tools_used = []
    tokens = 0
    model = None
    error = None
    proposed = []          # 本轮生成的待确认提案，前端据此渲染确认卡片
    writes = []            # 本轮真正写入账套的动作（执行级工具）
    write_count = 0

    sys_prompt = registry.prompt(agent)
    hints = learning.hints_text(entity_id)
    if hints:
        sys_prompt += "\n\n" + hints
    if context:
        sys_prompt += "\n\n【当前业务上下文】\n" + json.dumps(context, ensure_ascii=False)[:4000]

    # 工具分两类：只读（toolbox）与可执行（tools_write）。
    # 会话里关掉「可直接执行」时，执行工具连 schema 都不给模型。
    allow = registry.whitelist(agent)
    write_names = [n for n in allow if n in tools_write.WRITE_TOOLS] if allow_write else []
    read_names = [n for n in allow if n not in tools_write.WRITE_TOOLS]
    if allow_write and write_names:
        # 能直接执行时就不给 propose_document，免得模型走「先提案等人点」的老路
        read_names = [n for n in read_names if n != "propose_document"]
    elif not allow_write and "propose_document" in read_names:
        # 只提案模式：明确告诉模型走提案，不要只给建议（必须在拼 messages 之前追加）
        sys_prompt += ("\n\n【本次为「只提案」模式】你不能直接建单或记账。"
                       "要建单时调用 propose_document 生成待确认提案，"
                       "由用户在界面上确认后才会真正建单。")
    schemas = toolbox.openai_tools(read_names) + tools_write.openai_tools(write_names)

    messages = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_text}]

    try:
        for _ in range(MAX_ROUNDS):
            if time.time() - started > MAX_SECONDS:
                return _fail(entity_id, agent, actor, scene, user_text,
                             "超时（>90s），转人工", tokens, started, model, tools_used, writes)

            r = llm.chat(messages, tools=schemas or None,
                         temperature=temperature, max_tokens=max_tokens)
            tokens += r["tokens"]
            model = r["model"]
            msg = r["message"]
            messages.append(msg)

            calls = msg.get("tool_calls") or []
            if not calls:
                text = (msg.get("content") or "").strip()
                # 结论里出现 FAIL / 阻断，记成 REVIEW；否则 PASS
                verdict = "REVIEW" if ("FAIL" in text.upper() or "阻断" in text) else "PASS"
                run_id = _audit(entity_id, agent, actor, scene, user_text, text, verdict,
                                tokens, int((time.time() - started) * 1000), model,
                                None, tools_used)
                return {"ok": True, "text": text, "tokens": tokens,
                        "runId": run_id, "tools": tools_used, "model": model,
                        "proposed": proposed, "writes": writes}

            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    if name in tools_write.WRITE_TOOLS:
                        # 岗位授权在运行时硬拦：即使模型自己编出工具名，也不能越过岗位边界
                        if name not in write_names:
                            raise tools_write.WriteError(
                                f"{name} 不在本岗位授权内（会计管账不管钱、出纳管钱不管账）")
                        if not allow_write:
                            raise tools_write.WriteError(
                                "本次会话为「只提案」模式，不能直接写入；请改用 propose_document")
                        if write_count >= tools_write.MAX_WRITES_PER_TURN:
                            raise tools_write.WriteError(
                                f"单轮写操作已达上限 {tools_write.MAX_WRITES_PER_TURN} 笔，"
                                f"剩下的请下一轮再做")
                        args = dict(args)
                        args["_actor"] = agent
                        args["_requested_by"] = actor
                        args["_role"] = role
                        result = tools_write.call(name, args)
                        write_count += 1
                        writes.append({"tool": name, "ok": True,
                                       "docNo": result.get("docNo") or result.get("entryNo")
                                                or result.get("paymentNo")
                                                or result.get("reversalEntryNo"),
                                       "danger": tools_write.WRITE_TOOLS[name].get("danger"),
                                       "result": result})
                    else:
                        result = toolbox.call(name, args)
                    ok = True
                except Exception as e:              # 工具失败不打断循环
                    result = {"error": str(e)}
                    ok = False
                    if name in tools_write.WRITE_TOOLS:
                        writes.append({"tool": name, "ok": False, "error": str(e)})
                rec = {"tool": name, "ok": ok,
                       "args": args if len(str(args)) < 800 else "…"}
                # 导出的文件（PDF 等）：把链接带回前端，指令台里直接给下载按钮
                if isinstance(result, dict) and result.get("href"):
                    rec["file"] = {"href": result["href"],
                                   "name": result.get("fileName") or "",
                                   "kind": result.get("kind") or "",
                                   "lang": result.get("lang") or "",
                                   "from": result.get("from") or "",
                                   "to": result.get("to") or ""}
                tools_used.append(rec)
                # 提案类工具：把结果带回前端，让人在界面上点确认
                if name == "propose_document" and isinstance(result, dict) \
                        and result.get("actionId"):
                    proposed.append({"actionId": result["actionId"],
                                     "title": result.get("title"),
                                     "summary": result.get("summary"),
                                     "actionType": result.get("actionType")})
                messages.append({
                    "role": "tool",
                    "tool_call_id": c.get("id") or name,
                    "content": json.dumps(result, ensure_ascii=False, default=_enc)[:8000],
                })
        else:
            return _fail(entity_id, agent, actor, scene, user_text,
                         "工具调用轮次超限，转人工", tokens, started, model, tools_used, writes)

    except llm.LLMError as e:
        error = f"模型不可用：{e}"
    except Exception as e:
        error = f"运行时异常：{e}"

    run_id = _audit(entity_id, agent, actor, scene, user_text, "", "FAIL",
                    tokens, int((time.time() - started) * 1000), model, error, tools_used)
    return {"ok": False, "error": error, "runId": run_id,
            "tokens": tokens, "tools": tools_used, "model": model, "writes": writes}


# ---------------------------------------------------------------- 守门人直连
def guard_check(entry: dict, *, actor="system", scene="journal_check") -> dict:
    """不经过模型的分录校验：直接用确定性内核。

    这是「守门人不可用 → FAIL」的实现：内核本身不会失败，
    但调用方若拿不到结果，一律按 FAIL 处理。
    """
    try:
        res = toolbox.call("journal_check", {"entry": entry})
        res["agent"] = "guard"
        res["ranBy"] = "deterministic"
        return res
    except Exception as e:
        return {
            "task": "journal_entry_check",
            "verdict": "FAIL",
            "blockedReasons": [f"守门人不可用：{e}"],
            "reviewReasons": [],
            "balanced": None,
            "agent": "guard",
            "authorization": "NEVER_AUTHORIZES_POSTING",
            "disclaimer": "守门人不可用，校验未执行 —— 按最严处理，禁止过账",
            "unavailable": True,
        }


def stats(days=30):
    rows = query("""SELECT agent, COUNT(*) n, SUM(tokens) tk,
                           SUM(error IS NOT NULL AND error <> '') errs
                      FROM ai_run
                     WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                     GROUP BY agent""", (days,))
    return [{"agent": r["agent"], "runs": int(r["n"]),
             "tokens": int(r["tk"] or 0), "errors": int(r["errs"] or 0)} for r in rows]
