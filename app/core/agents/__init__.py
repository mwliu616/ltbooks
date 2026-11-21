# LtBooks — core/agents/__init__.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""自建财务智能体平台（脱离 DSH）。

分层：
  llm        模型接入（OpenAI 兼容 + function calling）
  toolbox    工具注册表（全部只读，无 execute）
  registry   智能体编制（三岗位 + 守门人 + 三参谋）
  runtime    多轮循环 + 审计 + 降级
  learning   自我进化（只学映射与偏好）
"""
from . import registry, runtime, toolbox  # noqa: F401
