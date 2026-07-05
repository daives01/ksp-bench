import { existsSync } from "node:fs"

type Json = null | boolean | number | string | Json[] | { [key: string]: Json }

type RpcRequest = {
  jsonrpc?: string
  id?: string | number | null
  method?: string
  params?: Record<string, unknown>
}

type WorkerRequest = {
  id: number
  method: string
  params: Record<string, unknown>
}

type WorkerResponse = {
  id: number | null
  result?: unknown
  error?: { type?: string; message?: string }
}

type ToolDefinition = {
  name: string
  description: string
  inputSchema: Record<string, unknown>
}

const tools: ToolDefinition[] = [
  {
    name: "observe",
    description: "Read telemetry, vehicle state, stages, resources, engines, and target orbit.",
    inputSchema: objectSchema({}),
  },
  {
    name: "throttle",
    description: "Set vessel throttle from 0.0 to 1.0.",
    inputSchema: objectSchema({
      value: { type: "number", minimum: 0, maximum: 1, description: "Throttle setting." },
    }),
  },
  {
    name: "stage",
    description: "Activate the next stage.",
    inputSchema: objectSchema({}),
  },
  {
    name: "list_vehicles",
    description: "List known KSP vehicles and show which one this MCP session is controlling.",
    inputSchema: objectSchema({}),
  },
  {
    name: "reset_launchpad",
    description: "Revert KSP to the unpaused benchmark vessel on the launchpad.",
    inputSchema: objectSchema({
      wait_s: {
        type: "number",
        minimum: 0,
        description: "Seconds to wait for the reverted vessel to become active. Defaults to 2.",
      },
    }, []),
  },
  {
    name: "set_vehicle",
    description: "Select the vehicle this MCP session controls by list index or exact name.",
    inputSchema: objectSchema({
      index: {
        type: "integer",
        minimum: 0,
        description: "Vehicle index from list_vehicles. Pass either index or name.",
      },
      name: {
        type: "string",
        description: "Exact vehicle name from list_vehicles. Pass either name or index.",
      },
      make_active: {
        type: "boolean",
        description: "Also make the selected vehicle active in KSP. Defaults to true.",
      },
    }, []),
  },
  {
    name: "attitude",
    description: "Engage autopilot. Use mode=pitch_heading with pitch/heading, or hold prograde/retrograde/normal/anti_normal/radial/anti_radial in a reference frame.",
    inputSchema: objectSchema({
      mode: {
        type: "string",
        enum: [
          "pitch_heading",
          "prograde",
          "retrograde",
          "normal",
          "anti_normal",
          "radial",
          "anti_radial",
        ],
        description: "Autopilot attitude mode.",
      },
      pitch: { type: "number", description: "Pitch in degrees; required for pitch_heading." },
      heading: { type: "number", description: "Heading in degrees; required for pitch_heading." },
      reference_frame: {
        type: "string",
        enum: ["orbital", "surface", "vessel_surface"],
        description: "Reference frame for vector modes. Defaults to orbital.",
      },
    }, ["mode"]),
  },
  {
    name: "wait",
    description: "Wait while flight continues and telemetry updates. In atmosphere this does not time warp; avoid very long atmospheric waits unless intentionally letting real time pass without spending agent tokens.",
    inputSchema: objectSchema({
      seconds: { type: "number", minimum: 0, description: "Seconds to wait." },
    }),
  },
  {
    name: "execute_python",
    description: "Run a short kRPC Python snippet for APIs the structured tools do not cover.",
    inputSchema: objectSchema({
      code: { type: "string", description: "Python code." },
      timeout_s: { type: "number", minimum: 0, description: "Optional wall-clock timeout." },
    }, ["code"]),
  },
  {
    name: "start_task",
    description: "Start a longer-running kRPC Python control loop. Returns a task_id for check_task/stop_task.",
    inputSchema: objectSchema({
      code: { type: "string", description: "Python code." },
      timeout_s: { type: "number", minimum: 0, description: "Optional wall-clock timeout." },
    }, ["code"]),
  },
  {
    name: "check_task",
    description: "Check background task status and latest telemetry. Omit task_id to list all tasks.",
    inputSchema: objectSchema({
      task_id: { type: "string", description: "Optional task_id returned by start_task." },
    }, []),
  },
  {
    name: "stop_task",
    description: "Request cooperative stop for a background task. Pass task_id when multiple tasks are running.",
    inputSchema: objectSchema({
      task_id: { type: "string", description: "Optional task_id returned by start_task." },
    }, []),
  },
]

const privilegedToolNames = new Set(["reset_launchpad"])
const exposedTools = tools.filter(
  (tool) => !privilegedToolNames.has(tool.name) || resetToolEnabled(),
)
const toolNames = new Set(exposedTools.map((tool) => tool.name))
const decoder = new TextDecoder()
const encoder = new TextEncoder()
let worker: WorkerClient | undefined

class WorkerConnectionError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "WorkerConnectionError"
  }
}

class WorkerClient {
  private process: Bun.Subprocess<"pipe", "pipe", "pipe">
  private nextID = 1
  private pending = new Map<number, {
    resolve: (value: unknown) => void
    reject: (error: Error) => void
  }>()
  private buffer = ""

  constructor() {
    const python =
      process.env.KSPBENCH_PYTHON ?? (existsSync(".venv/bin/python") ? ".venv/bin/python" : "python")
    this.process = Bun.spawn([python, "-m", "bench.ksp_worker"], {
      stdin: "pipe",
      stdout: "pipe",
      stderr: "pipe",
      env: process.env,
    })
    void this.readStdout()
    void this.readStderr()
    void this.process.exited.then((code) => {
      this.rejectPending(new WorkerConnectionError(`KSP worker exited with code ${code}`))
    })
  }

  async call(method: string, params: Record<string, unknown>): Promise<unknown> {
    const id = this.nextID++
    const request: WorkerRequest = { id, method, params }
    const promise = new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
    })
    try {
      this.process.stdin.write(JSON.stringify(request) + "\n")
    } catch (error) {
      this.pending.delete(id)
      throw new WorkerConnectionError(
        `could not send request to KSP worker: ${error instanceof Error ? error.message : String(error)}`,
      )
    }
    return promise
  }

  async stop(): Promise<void> {
    try {
      this.process.stdin.end()
    } catch {
      // ignore shutdown races
    }
    await this.process.exited
  }

  private async readStdout(): Promise<void> {
    for await (const chunk of this.process.stdout) {
      this.buffer += decoder.decode(chunk)
      while (true) {
        const newline = this.buffer.indexOf("\n")
        if (newline < 0) break
        const line = this.buffer.slice(0, newline)
        this.buffer = this.buffer.slice(newline + 1)
        this.handleLine(line)
      }
    }
  }

  private async readStderr(): Promise<void> {
    for await (const chunk of this.process.stderr) {
      process.stderr.write(decoder.decode(chunk))
    }
  }

  private handleLine(line: string): void {
    if (!line.trim()) return
    let response: WorkerResponse
    try {
      response = JSON.parse(line)
    } catch (error) {
      process.stderr.write(`ksp worker emitted invalid JSON: ${line}\n`)
      return
    }
    if (response.id === null) {
      if (response.error) process.stderr.write(`ksp worker error: ${response.error.message}\n`)
      return
    }
    const pending = this.pending.get(response.id)
    if (!pending) return
    this.pending.delete(response.id)
    if (response.error) {
      pending.reject(new Error(`${response.error.type ?? "WorkerError"}: ${response.error.message ?? ""}`))
    } else {
      pending.resolve(response.result)
    }
  }

  private rejectPending(error: Error): void {
    for (const pending of this.pending.values()) {
      pending.reject(error)
    }
    this.pending.clear()
  }
}

async function main(): Promise<void> {
  const stdin = Bun.stdin.stream().pipeThrough(new TextDecoderStream())
  let buffer = ""
  for await (const chunk of stdin) {
    buffer += chunk
    while (true) {
      const newline = buffer.indexOf("\n")
      if (newline < 0) break
      const line = buffer.slice(0, newline)
      buffer = buffer.slice(newline + 1)
      await handleLine(line)
    }
  }
  await worker?.stop()
}

async function handleLine(line: string): Promise<void> {
  if (!line.trim()) return
  let request: RpcRequest
  try {
    request = JSON.parse(line)
  } catch {
    write({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } })
    return
  }

  if (request.method === "notifications/initialized") return
  if (request.id === undefined) return

  try {
    const result = await handleRequest(request)
    write({ jsonrpc: "2.0", id: request.id, result })
  } catch (error) {
    write({
      jsonrpc: "2.0",
      id: request.id,
      error: {
        code: -32000,
        message: error instanceof Error ? error.message : String(error),
      },
    })
  }
}

async function handleRequest(request: RpcRequest): Promise<Record<string, unknown>> {
  switch (request.method) {
    case "initialize":
      return {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "ksp-mcp", version: "0.1.0" },
      }
    case "ping":
      return {}
    case "tools/list":
      return { tools: exposedTools }
    case "tools/call":
      return callTool(request.params ?? {})
    case "resources/list":
      return { resources: [] }
    case "prompts/list":
      return { prompts: [] }
    default:
      throw new Error(`unsupported MCP method: ${request.method}`)
  }
}

async function callTool(params: Record<string, unknown>): Promise<Record<string, unknown>> {
  const name = params.name
  const args = params.arguments ?? {}
  if (typeof name !== "string" || !toolNames.has(name)) {
    throw new Error(`unknown KSP tool: ${String(name)}`)
  }
  if (!isObject(args)) throw new Error("tool arguments must be an object")
  validateToolArguments(name, args)
  worker ??= new WorkerClient()
  let result: unknown
  try {
    result = await worker.call(name, args)
  } catch (error) {
    if (!(error instanceof WorkerConnectionError)) throw error
    process.stderr.write(`ksp worker disconnected; restarting and retrying ${name}\n`)
    worker = new WorkerClient()
    result = await worker.call(name, args)
  }
  const text = JSON.stringify(result, null, 2)
  return {
    content: [{ type: "text", text }],
    isError: isObject(result) && result.ok === false,
  }
}

function write(payload: Json): void {
  Bun.stdout.write(encoder.encode(JSON.stringify(payload) + "\n"))
}

function objectSchema(
  properties: Record<string, unknown>,
  required = Object.keys(properties),
): Record<string, unknown> {
  return {
    type: "object",
    properties,
    required,
    additionalProperties: false,
  }
}

function resetToolEnabled(): boolean {
  return truthyEnv(process.env.KSPBENCH_ENABLE_RESET_TOOL)
}

function truthyEnv(value: string | undefined): boolean {
  return value === "1" || value === "true" || value === "yes" || value === "on"
}

function validateToolArguments(name: string, args: Record<string, unknown>): void {
  switch (name) {
    case "observe":
    case "stage":
    case "list_vehicles":
      rejectUnexpected(name, args, [])
      return
    case "reset_launchpad":
      rejectUnexpected(name, args, ["wait_s"])
      if (args.wait_s !== undefined && args.wait_s !== null) {
        const wait = requiredNumber(args, "wait_s")
        if (wait < 0) throw new Error("reset_launchpad.wait_s must be non-negative")
      }
      return
    case "throttle": {
      rejectUnexpected(name, args, ["value"])
      const value = requiredNumber(args, "value")
      if (value < 0 || value > 1) throw new Error("throttle.value must be between 0 and 1")
      return
    }
    case "set_vehicle": {
      rejectUnexpected(name, args, ["index", "name", "make_active"])
      const hasIndex = args.index !== undefined && args.index !== null
      const hasName = args.name !== undefined && args.name !== null
      if (hasIndex === hasName) throw new Error("set_vehicle requires exactly one of index or name")
      if (hasIndex) requiredInteger(args, "index")
      if (hasName && typeof args.name !== "string") throw new Error("set_vehicle.name must be a string")
      if (
        args.make_active !== undefined &&
        args.make_active !== null &&
        typeof args.make_active !== "boolean"
      ) {
        throw new Error("set_vehicle.make_active must be a boolean")
      }
      return
    }
    case "attitude": {
      rejectUnexpected(name, args, ["mode", "pitch", "heading", "reference_frame"])
      if (typeof args.mode !== "string") throw new Error("attitude.mode must be a string")
      if (args.mode === "pitch_heading") {
        requiredNumber(args, "pitch")
        requiredNumber(args, "heading")
      }
      if (
        args.reference_frame !== undefined &&
        args.reference_frame !== null &&
        typeof args.reference_frame !== "string"
      ) {
        throw new Error("attitude.reference_frame must be a string")
      }
      return
    }
    case "wait": {
      rejectUnexpected(name, args, ["seconds"])
      const seconds = requiredNumber(args, "seconds")
      if (seconds < 0) throw new Error("wait.seconds must be non-negative")
      return
    }
    case "execute_python":
    case "start_task": {
      rejectUnexpected(name, args, ["code", "timeout_s"])
      if (typeof args.code !== "string") throw new Error(`${name}.code must be a string`)
      if (args.timeout_s !== undefined && args.timeout_s !== null) {
        const timeout = requiredNumber(args, "timeout_s")
        if (timeout < 0) throw new Error(`${name}.timeout_s must be non-negative`)
      }
      return
    }
    case "check_task":
    case "stop_task":
      rejectUnexpected(name, args, ["task_id"])
      if (args.task_id !== undefined && args.task_id !== null && typeof args.task_id !== "string") {
        throw new Error(`${name}.task_id must be a string`)
      }
      return
    default:
      throw new Error(`unknown KSP tool: ${name}`)
  }
}

function rejectUnexpected(
  toolName: string,
  args: Record<string, unknown>,
  allowed: string[],
): void {
  for (const key of Object.keys(args)) {
    if (!allowed.includes(key)) throw new Error(`${toolName}.${key} is not a supported argument`)
  }
}

function requiredNumber(args: Record<string, unknown>, key: string): number {
  const value = args[key]
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${key} must be a finite number`)
  }
  return value
}

function requiredInteger(args: Record<string, unknown>, key: string): number {
  const value = requiredNumber(args, key)
  if (!Number.isInteger(value)) throw new Error(`${key} must be an integer`)
  return value
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

await main()
