/**
 * dsh-delta-isp — DeepSeek Harness Host plugin.
 *
 * Registers PLC tools that bridge to the bundled Python engine.  No DSH
 * package is imported: tools are registered through `ctx.tools.register`
 * with plain JSON Schema definitions, and the Python engine is spawned with
 * Node's own `child_process`, so installation needs no build step.
 */

import { execFileSync, spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { delimiter, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const PACKAGE_DIR = dirname(fileURLToPath(import.meta.url))
const PYTHON_SRC = join(PACKAGE_DIR, 'python', 'src')
const CONFIG_PATH = join(homedir(), '.dsh-delta-isp', 'config.json')
const DEFAULT_WORKSPACE = join(homedir(), '.dsh-delta-isp', 'plc-work')
const MAX_OUTPUT_BYTES = 16 * 1024 * 1024
const DEFAULT_TIMEOUT_MS = 180_000

export const name = 'delta-isp'
export const inject = ['tools']

const PLC_WORKFLOW = `【Delta ISPSoft PLC 工作流】
当用户要求读写台达 ISPSoft 工程时，按以下顺序操作：
1. 还没有打开工程时，先调用 plc_project_open。
2. 新建程序前先调用 plc_tasks 查看任务 ID，再决定 task_id。
3. 新增逻辑用 plc_pou_create_st（ST）或 plc_create_selflock（梯形图自锁）。
   不要对 Prog0 / Main 等梯形图 POU 调用 plc_pou_write（只读）。
4. 变量和设备地址必须先用 plc_symbols 查证，禁止编造。
5. 写入后调用 plc_lint、plc_diff，再调用 plc_export。
6. 编译和下载必须由人在 ISPSoft 中完成；不要声称已经编译或下载。
7. 原始 .isp 永远不会被修改，所有改动都在工作区副本里。`

/* ------------------------------------------------------------------ */
/* tool specs                                                          */
/* ------------------------------------------------------------------ */

const object = (properties = {}, required = []) => ({
  type: 'object',
  properties,
  required,
  additionalProperties: false,
})

const string = (description) => ({ type: 'string', description })
const integer = (description) => ({ type: 'integer', description })

const TOOL_SPECS = [
  {
    name: 'plc_environment',
    description:
      '检查 PLC 插件运行环境：Python 解释器、工作区、ISPSoft 路径与运行状态。排查安装问题时先调用它。',
    parameters: object(),
    op: 'environment',
  },
  {
    name: 'plc_project_open',
    description:
      '打开 Delta ISPSoft 的 .isp 工程。会把工程复制到工作区，原文件永不被修改；后续操作都针对该副本。',
    parameters: object({ path: string('绝对路径，例如 D:\\\\project\\\\Demo.isp') }, ['path']),
    op: 'project_open',
  },
  {
    name: 'plc_project_status',
    description: '返回当前工程概览：PLC 型号、ISPSoft 版本、POU 数量、任务数量、是否 dirty。',
    parameters: object(),
    op: 'project_status',
  },
  {
    name: 'plc_pou_list',
    description: '列出全部 POU：名称、类型（PRG/FB）、语言（LD/ST）、是否启用、所属任务。',
    parameters: object(),
    op: 'pou_list',
  },
  {
    name: 'plc_pou_read',
    description: '读取一个 POU：ST 代码或梯形图网络、局部变量、注释、所属任务。',
    parameters: object({ name: string('POU 名称，例如 Main 或 test') }, ['name']),
    op: 'pou_read',
  },
  {
    name: 'plc_symbols',
    description: '查询工程全局符号：变量名、设备地址（X/Y/M/D/T/C）、数据类型、注释，并返回 DUT 名称。',
    parameters: object({
      query: string('可选过滤关键字，匹配名称/地址/注释'),
      limit: integer('最多返回条数，默认 200'),
    }),
    op: 'symbols',
  },
  {
    name: 'plc_tasks',
    description:
      '列出工程任务（T_ID）、周期时间与调用 POU 顺序。新建 POU 前先用它选择 task_id。',
    parameters: object(),
    op: 'tasks',
  },
  {
    name: 'plc_pou_write',
    description:
      '改写一个 ST POU 的程序体（可选同时改局部变量）。只写工作区副本，并做 GBK 与静态检查；梯形图 POU 只读。',
    parameters: object(
      {
        name: string('POU 名称'),
        code: string('完整 ST 代码，必须能被 GBK 编码'),
        variables: string('可选：完整局部变量声明文本'),
      },
      ['name', 'code'],
    ),
    op: 'pou_write',
  },
  {
    name: 'plc_pou_create_st',
    description:
      '新建一个 ST 程序（P_Lang=4）：写入完整代码和可选局部变量，登记到程序树并挂到指定任务。空工程和现有工程都能用；创建后请编译确认。',
    parameters: object(
      {
        name: string('新 POU 名称，例如 MainLogic'),
        code: string('完整 ST 代码，必须能被 GBK 编码'),
        variables: string('可选：完整局部变量声明'),
        task_id: integer('可选：挂到哪个任务，例如 0'),
        comment: string('可选：POU 注释'),
      },
      ['name', 'code'],
    ),
    op: 'create_st_pou',
  },
  {
    name: 'plc_create_selflock',
    description:
      '新建一个梯形图 POU，写入“启动/停止/自锁”电机控制梯级：start 常开与 coil 常开并联，再串 stop 常闭，输出 coil（可选 indicator 指示）。这是模板生成，生成后请编译确认。',
    parameters: object(
      {
        name: string('新 POU 名称，例如 自锁'),
        start: string('启动触点，例如 M0'),
        stop: string('停止常闭触点，例如 M1'),
        coil: string('输出线圈兼自锁触点，例如 Y0.1'),
        indicator: string('可选：运行指示线圈，例如 M2'),
        task_id: integer('可选：挂到哪个任务，例如 1'),
        comment: string('可选：POU/网络注释'),
      },
      ['name', 'start', 'stop', 'coil'],
    ),
    op: 'create_selflock',
  },
  {
    name: 'plc_lint',
    description: '对 ST 代码做静态检查：IF/CASE 配对、全角标点、= 与 :=、GBK 可编码性。',
    parameters: object({
      pou: string('可选：检查已有 POU'),
      code: string('可选：直接检查一段代码'),
    }),
    op: 'lint',
  },
  {
    name: 'plc_diff',
    description: '显示工作区相对基线的 unified diff 与变更 POU 列表。',
    parameters: object(),
    op: 'diff',
  },
  {
    name: 'plc_export',
    description:
      '把工作区重新打包成 .isp，校验 CRC 与长度字段后写出。默认写到工作区 exports 目录。',
    parameters: object({ output: string('可选：输出绝对路径') }),
    op: 'export',
  },
  {
    name: 'plc_rollback',
    description: '放弃工作区改动，恢复到打开工程时的基线。',
    parameters: object(),
    op: 'rollback',
  },
  {
    name: 'plc_open_in_ispsoft',
    description: '导出工作区副本并用本机 ISPSoft 打开，供人工检查。不会改动原工程。',
    parameters: object(),
    op: 'open_in_ispsoft',
  },
  {
    name: 'plc_build',
    description:
      '导出并请求编译。ISPSoft 3.19 没有公开命令行编译接口，目前返回手动编译步骤与文件路径。',
    parameters: object({ timeout: integer('超时秒数，默认 180') }),
    op: 'build',
  },
]

/* ------------------------------------------------------------------ */
/* plugin entry                                                        */
/* ------------------------------------------------------------------ */

export function apply(ctx, config = {}) {
  const runtime = createRuntime(config)
  const disposers = TOOL_SPECS.map((spec) =>
    ctx.tools.register(makeToolDefinition(spec, runtime)),
  )

  let promptService
  try {
    promptService = typeof ctx.get === 'function' ? ctx.get('systemPrompt') : undefined
  } catch {
    promptService = undefined
  }
  if (promptService?.section) {
    disposers.push(
      promptService.section({
        name: 'delta-isp-workflow',
        order: 900,
        text: PLC_WORKFLOW,
      }),
    )
  }

  return () => {
    for (const dispose of disposers) {
      try {
        dispose()
      } catch {
        /* unload is best effort */
      }
    }
  }
}

function makeToolDefinition(spec, runtime) {
  return {
    name: spec.name,
    description: spec.description,
    parameters: spec.parameters,
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: String(value) }],
    },
    timeoutMs: spec.timeoutMs ?? DEFAULT_TIMEOUT_MS + 30_000,
    async execute(args, exec) {
      const data = await runtime.call(spec.op, args ?? {}, exec?.signal)
      if (spec.op === 'environment') {
        return JSON.stringify(
          {
            ...data,
            plugin: {
              python: runtime.pythonInfo(),
              node: process.version,
              packageDir: PACKAGE_DIR,
            },
          },
          null,
          2,
        )
      }
      return JSON.stringify(data, null, 2)
    },
  }
}

/* ------------------------------------------------------------------ */
/* runtime                                                             */
/* ------------------------------------------------------------------ */

function createRuntime(config) {
  const settings = loadSettings(config)
  let python = null

  return {
    settings,
    async call(op, args, signal) {
      python ??= detectPython(settings)
      return runBridge(python, settings, op, args, signal)
    },
    pythonInfo() {
      python ??= detectPython(settings)
      return {
        command: python.command,
        args: [...python.args],
      }
    },
  }
}

function loadSettings(config) {
  let fileConfig = {}
  if (existsSync(CONFIG_PATH)) {
    try {
      fileConfig = JSON.parse(readFileSync(CONFIG_PATH, 'utf8'))
    } catch {
      fileConfig = {}
    }
  }

  const merged = { ...fileConfig, ...(config || {}) }
  const workspace = expandHome(
    typeof merged.workspace === 'string' && merged.workspace.trim()
      ? merged.workspace.trim()
      : DEFAULT_WORKSPACE,
  )
  mkdirSync(workspace, { recursive: true })

  const allowRead = Array.isArray(merged.allowRead)
    ? merged.allowRead.map((item) => expandHome(String(item)))
    : []

  return {
    python:
      (typeof merged.python === 'string' && merged.python.trim()) ||
      process.env.DELTA_ISP_PYTHON ||
      '',
    workspace,
    allowRead,
  }
}

function expandHome(value) {
  if (value === '~') return homedir()
  if (value.startsWith('~/') || value.startsWith('~\\')) {
    return join(homedir(), value.slice(2))
  }
  return value
}

/* ------------------------------------------------------------------ */
/* Python discovery                                                    */
/* ------------------------------------------------------------------ */

function detectPython(settings) {
  const candidates = []
  const push = (command, args = []) => {
    if (command) candidates.push({ command, args })
  }

  push(settings.python)
  if (process.platform === 'win32') {
    for (const version of ['-3.13', '-3.12', '-3.11', '-3.10']) {
      push('py', [version])
    }
  }
  push('python3')
  push('python')

  for (const executable of dshPythonExecutables()) push(executable)
  for (const executable of localPythonExecutables()) push(executable)

  const seen = new Set()
  for (const candidate of candidates) {
    const key = `${candidate.command} ${candidate.args.join(' ')}`
    if (seen.has(key)) continue
    seen.add(key)
    if (pythonSupports3_10(candidate)) return candidate
  }

  throw new Error(
    '未找到 Python 3.10+。请安装 Python 3.10 及以上，或在 ' +
      CONFIG_PATH +
      ' 中设置 {"python": "C:\\\\path\\\\to\\\\python.exe"}。',
  )
}

function pythonSupports3_10({ command, args }) {
  try {
    const output = execFileSync(
      command,
      [
        ...args,
        '-c',
        'import sys; print("PYVER=%d.%d" % sys.version_info[:2])',
      ],
      {
        encoding: 'utf8',
        timeout: 8000,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'ignore'],
      },
    )
    const match = /PYVER=(\d+)\.(\d+)/.exec(output)
    return Boolean(match) && Number(match[1]) === 3 && Number(match[2]) >= 10
  } catch {
    return false
  }
}

function dshPythonExecutables() {
  const executables = []
  const homes = new Set()
  if (process.env.DSH_HOME) homes.add(process.env.DSH_HOME)
  homes.add(join(homedir(), '.dsh'))

  for (const home of homes) {
    const runtimes = join(home, 'dsh-runtimes')
    if (!existsSync(runtimes)) continue
    let names = []
    try {
      names = readdirSync(runtimes)
    } catch {
      continue
    }
    for (const runtimeName of names) {
      const base = join(runtimes, runtimeName, 'dependencies', 'python')
      const executable =
        process.platform === 'win32'
          ? join(base, 'python.exe')
          : join(base, 'bin', 'python3')
      if (existsSync(executable)) executables.push(executable)
    }
  }
  return executables
}

function localPythonExecutables() {
  if (process.platform !== 'win32') return []
  const roots = [
    join(process.env.LOCALAPPDATA || '', 'Programs', 'Python'),
    'C:\\',
  ]
  const executables = []
  for (const root of roots) {
    if (!existsSync(root)) continue
    let names = []
    try {
      names = readdirSync(root)
    } catch {
      continue
    }
    for (const entry of names) {
      if (!/^Python3\d+$/i.test(entry)) continue
      const executable = join(root, entry, 'python.exe')
      if (existsSync(executable)) executables.push(executable)
    }
  }
  return executables
}

/* ------------------------------------------------------------------ */
/* bridge                                                              */
/* ------------------------------------------------------------------ */

function bridgeEnvironment(settings) {
  const pythonPath = [PYTHON_SRC, process.env.PYTHONPATH]
    .filter(Boolean)
    .join(delimiter)
  return {
    ...process.env,
    PYTHONPATH: pythonPath,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    PYTHONDONTWRITEBYTECODE: '1',
    DELTA_ISP_WORKSPACE: settings.workspace,
  }
}

function runBridge(python, settings, op, args, signal) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      python.command,
      [...python.args, '-m', 'delta_isp_mcp', 'bridge'],
      {
        cwd: settings.workspace,
        env: bridgeEnvironment(settings),
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
      },
    )

    let stdout = ''
    let stderr = ''
    let settled = false
    const finish = (error, value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      signal?.removeEventListener?.('abort', onAbort)
      if (error) reject(error)
      else resolve(value)
    }
    const onAbort = () => {
      child.kill()
      finish(new Error('PLC 操作已取消'))
    }
    const timer = setTimeout(() => {
      child.kill()
      finish(
        new Error(
          `PLC 操作超时（${DEFAULT_TIMEOUT_MS} ms）；ISPSoft 是否弹出对话框？`,
        ),
      )
    }, DEFAULT_TIMEOUT_MS)

    if (signal?.aborted) {
      child.kill()
      finish(new Error('PLC 操作已取消'))
      return
    }
    signal?.addEventListener?.('abort', onAbort, { once: true })

    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdin.on('error', () => {})
    child.stdout.on('data', (chunk) => {
      stdout += chunk
      if (stdout.length > MAX_OUTPUT_BYTES) {
        child.kill()
        finish(new Error('PLC 引擎输出超过 16 MB，已中止'))
      }
    })
    child.stderr.on('data', (chunk) => {
      stderr += chunk
      if (stderr.length > 20_000) stderr = stderr.slice(-20_000)
    })
    child.on('error', (error) => finish(error))
    child.on('close', (code) => {
      if (settled) return
      if (code !== 0) {
        finish(
          new Error(
            `PLC 引擎退出码 ${code}${stderr ? `：${stderr.trim()}` : ''}`,
          ),
        )
        return
      }
      let payload
      try {
        payload = JSON.parse(stdout)
      } catch {
        finish(
          new Error(
            `PLC 引擎返回非 JSON${stderr ? `：${stderr.trim()}` : `：${stdout.slice(0, 500)}`}`,
          ),
        )
        return
      }
      if (!payload.ok) {
        const codeText = payload?.error?.code ?? 'ERROR'
        const message = payload?.error?.message ?? '未知错误'
        finish(new Error(`${codeText}: ${message}`))
        return
      }
      finish(null, payload.data)
    })

    child.stdin.end(
      JSON.stringify({
        op,
        args,
        workspace: settings.workspace,
        allow_read: settings.allowRead,
      }),
    )
  })
}

/* ------------------------------------------------------------------ */
/* exports for tests                                                   */
/* ------------------------------------------------------------------ */

export const __test__ = {
  TOOL_SPECS,
  createRuntime,
  detectPython,
  runBridge,
  loadSettings,
  PYTHON_SRC,
}
