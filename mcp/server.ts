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
    name: "pitch_heading",
    description: "Engage autopilot and target pitch and heading in degrees.",
    inputSchema: objectSchema({
      pitch: { type: "number", description: "Pitch in degrees." },
      heading: { type: "number", description: "Heading in degrees." },
    }),
  },
  {
    name: "prograde",
    description: "Engage autopilot and hold prograde.",
    inputSchema: objectSchema({
      reference_frame: {
        type: "string",
        enum: ["orbital", "surface", "vessel_surface"],
        description: "Reference frame. Defaults to orbital.",
      },
    }, []),
  },
  {
    name: "wait",
    description: "Wait while the harness samples telemetry.",
    inputSchema: objectSchema({
      seconds: { type: "number", minimum: 0, description: "Seconds to wait." },
    }),
  },
  {
    name: "execute_python",
    description: "Run short direct kRPC Python for APIs the structured tools do not cover.",
    inputSchema: objectSchema({
      code: { type: "string", description: "Python code." },
      timeout_s: { type: "number", minimum: 0, description: "Optional wall-clock timeout." },
    }, ["code"]),
  },
  {
    name: "start_task",
    description: "Start one background kRPC Python control loop.",
    inputSchema: objectSchema({
      code: { type: "string", description: "Python code." },
      timeout_s: { type: "number", minimum: 0, description: "Optional wall-clock timeout." },
    }, ["code"]),
  },
  {
    name: "check_task",
    description: "Check the background task status and latest telemetry.",
    inputSchema: objectSchema({}),
  },
  {
    name: "stop_task",
    description: "Request cooperative stop for the background task.",
    inputSchema: objectSchema({}),
  },
]

const toolNames = new Set(tools.map((tool) => tool.name))
const decoder = new TextDecoder()
const encoder = new TextEncoder()
let worker: WorkerClient | undefined

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
  }

  async call(method: string, params: Record<string, unknown>): Promise<unknown> {
    const id = this.nextID++
    const request: WorkerRequest = { id, method, params }
    const promise = new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
    })
    this.process.stdin.write(JSON.stringify(request) + "\n")
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
      return { tools }
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
  worker ??= new WorkerClient()
  const result = await worker.call(name, args)
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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

await main()
