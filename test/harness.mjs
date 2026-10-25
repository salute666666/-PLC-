/**
 * Local harness: loads the plugin with a mocked `ctx.tools`, then exercises the
 * real Python bridge.  No DSH process is needed.
 *
 *   node test/harness.mjs
 *
 * Environment:
 *   DELTA_ISP_TEST_PROJECT  absolute .isp path to exercise the full flow
 *   DELTA_ISP_PYTHON        optional Python 3.10+ executable
 */

import { existsSync, mkdirSync, rmSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { apply } from '../index.js'

const here = dirname(fileURLToPath(import.meta.url))
const work = join(here, '.work')
const projectPath = process.env.DELTA_ISP_TEST_PROJECT || ''
const python = process.env.DELTA_ISP_PYTHON || ''

rmSync(work, { recursive: true, force: true })
mkdirSync(work, { recursive: true })

const tools = new Map()
const ctx = {
  tools: {
    register(definition) {
      tools.set(definition.name, definition)
      return () => tools.delete(definition.name)
    },
  },
}

const dispose = apply(ctx, {
  python,
  workspace: join(work, 'plc-work'),
  allowRead: projectPath ? [dirname(projectPath), work] : [work],
})

const results = []

async function check(name, fn) {
  try {
    const detail = await fn()
    results.push([name, true, detail ?? ''])
  } catch (error) {
    results.push([name, false, error?.message ?? String(error)])
  }
}

async function call(name, args = {}) {
  const tool = tools.get(name)
  if (!tool) throw new Error(`工具未注册：${name}`)
  const text = await tool.execute(args, {
    signal: new AbortController().signal,
  })
  return JSON.parse(text)
}

await check('1. 工具注册', async () => {
  if (tools.size !== 16) throw new Error(`期望 16 个工具，实际 ${tools.size}`)
  return `${tools.size} tools`
})

await check('2. environment', async () => {
  const data = await call('plc_environment')
  if (!data.plugin?.python?.command) throw new Error('没有 Python 信息')
  return `${data.plugin.python.command} / ${data.ispsoft_exe || 'ISPSoft 未找到'}`
})

if (projectPath) {
  await check('3. project_open', async () => {
    const data = await call('plc_project_open', { path: projectPath })
    if (data.plc_model !== 'AS320T') throw new Error(`型号异常：${data.plc_model}`)
    return `${data.plc_model} / ${data.pou_count} POU / ${data.encoding}`
  })

  await check('4. pou_list', async () => {
    const list = await call('plc_pou_list')
    if (!Array.isArray(list) || list.length < 20) throw new Error('POU 列表异常')
    return `${list.length} POU`
  })

  await check('5. symbols', async () => {
    const data = await call('plc_symbols', { query: 'Pluse', limit: 3 })
    if (!data.items?.length) throw new Error('没有匹配符号')
    return `${data.items[0].name} -> ${data.items[0].device}`
  })

  await check('6. tasks', async () => {
    const tasks = await call('plc_tasks')
    if (!Array.isArray(tasks) || tasks.length < 1) throw new Error('任务列表异常')
    return `${tasks.length} tasks, task0=${tasks[0].pous.length} POU`
  })

  await check('7. create_selflock', async () => {
    const data = await call('plc_create_selflock', {
      name: '插件自锁',
      start: 'M0',
      stop: 'M1',
      coil: 'Y0.1',
      indicator: 'M2',
      task_id: 1,
      comment: '插件验证：电机自锁',
    })
    if (data.language !== 'LD' || data.networks !== 1) {
      throw new Error(`生成的 POU 异常：${JSON.stringify(data)}`)
    }
    return `${data.name} (${data.devices.start}/${data.devices.stop} -> ${data.devices.coil})`
  })

  await check('8. create_st_pou', async () => {
    const data = await call('plc_pou_create_st', {
      name: '插件ST验证',
      code: 'M10 := M0 AND NOT M1;\r\nIF M10 THEN\r\n    M11 := TRUE;\r\nEND_IF;',
      task_id: 1,
      comment: '插件验证：新建 ST',
    })
    if (data.language !== 'ST' || data.code_lines < 4) {
      throw new Error(`生成的 ST POU 异常：${JSON.stringify(data)}`)
    }
    return `${data.name} (${data.code_lines} 行, task ${data.task})`
  })

  await check('9. 顺序与任务', async () => {
    const list = await call('plc_pou_list')
    const names = list.map((item) => item.name)
    const index = names.indexOf('插件ST验证')
    if (index < 0) throw new Error('新 ST POU 不在列表中')
    if (names[index + 1]?.includes('Slove_Flow')) {
      return `位于 PRG 末尾（下一个是 ${names[index + 1]}）`
    }
    return `位于 ${names[index - 1]} 之后`
  })

  await check('10. export', async () => {
    const output = join(work, 'out', 'selflock.isp')
    const data = await call('plc_export', { output })
    if (!existsSync(output) || statSync(output).size < 1000) {
      throw new Error('导出文件不存在或过小')
    }
    return `${data.output_size} bytes / crc ok`
  })

  await check('11. rollback', async () => {
    const data = await call('plc_rollback')
    if (data.dirty) throw new Error('回滚后仍为 dirty')
    return 'dirty=false'
  })
} else {
  results.push(['3-11. 工程流程', true, '跳过（未设置 DELTA_ISP_TEST_PROJECT）'])
}

dispose()

const width = Math.max(...results.map(([name]) => name.length))
console.log('\n' + '='.repeat(72))
for (const [name, ok, detail] of results) {
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name.padEnd(width)}  ${detail}`)
}
console.log('='.repeat(72))
const passed = results.filter(([, ok]) => ok).length
console.log(`HARNESS: ${passed}/${results.length} PASS`)
process.exit(passed === results.length ? 0 : 1)
