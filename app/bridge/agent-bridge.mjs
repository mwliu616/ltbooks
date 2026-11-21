/*
 * LtBooks — bridge/agent-bridge.mjs
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */

/**
 * DSH HKFRS 财务守门人 — 桥接层
 *
 * 用途：让会计系统（PHP/Python）调用智能体**自己注册的工具**，
 * 而不是引用一份复刻实现。
 *
 * 做法：用最小宿主上下文加载智能体插件，收集它 ctx.tools.register 的四个工具，
 * 再按名称调用其 execute。**不修改智能体任何文件**，也不绕过它的白名单。
 *
 * 用法：node agent-bridge.mjs <工具名>   （参数 JSON 从 stdin 读）
 *       node agent-bridge.mjs --list
 */
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'

// 默认加载部署包内的只读预设，不依赖构建服务器上的绝对路径。
const PRESET = process.env.LEDU_AGENT_PRESET
  || fileURLToPath(new URL('../agent/', import.meta.url))

const { apply } = await import(PRESET + '/index.js')

const tools = new Map()
const ctx = {
  tools: {
    register(def) {
      if (def && typeof def.name === 'string') tools.set(def.name, def)
    },
    guard() { /* 桥接层直接按名调用，不经过守卫链 */ },
  },
  workingDirectory: { async ensure() { return PRESET } },
}

apply(ctx, { rulesDir: PRESET + '/rules' })

const argv = process.argv.slice(2)

if (argv.includes('--list')) {
  process.stdout.write(JSON.stringify({
    preset: PRESET,
    tools: [...tools.values()].map((t) => ({
      name: t.name,
      description: (t.description || '').split('\n')[0].slice(0, 120),
      parameters: t.parameters || null,
    })),
  }, null, 2))
  process.exit(0)
}

const toolName = argv[0]
if (!toolName) {
  console.error('用法: node agent-bridge.mjs <工具名> | --list')
  process.exit(2)
}

const tool = tools.get(toolName)
if (!tool) {
  process.stdout.write(JSON.stringify({
    error: 'TOOL_NOT_ALLOWED',
    message: `工具 ${toolName} 不在智能体白名单内（允许：${[...tools.keys()].join('、')}）`,
    allowed: [...tools.keys()],
  }))
  process.exit(3)
}

function readStdin() {
  return new Promise((resolve) => {
    let buf = ''
    const rl = createInterface({ input: process.stdin })
    rl.on('line', (l) => { buf += l })
    rl.on('close', () => resolve(buf))
  })
}

const raw = await readStdin()
let args = {}
if (raw.trim() !== '') {
  try {
    args = JSON.parse(raw)
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: 'BAD_JSON', message: String(e.message) }))
    process.exit(4)
  }
}

try {
  const result = await tool.execute(args)
  process.stdout.write(JSON.stringify(result ?? null))
} catch (e) {
  process.stdout.write(JSON.stringify({
    error: 'TOOL_ERROR', tool: toolName, message: String(e && e.message ? e.message : e),
  }))
  process.exit(5)
}
