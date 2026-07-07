import { randomUUID } from "node:crypto";
import {
    existsSync,
    mkdirSync,
    readFileSync,
    rmSync,
    writeFileSync,
} from "node:fs";
import { join } from "node:path";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

type RpcRequest = {
    jsonrpc?: string;
    id?: string | number | null;
    method?: string;
    params?: Record<string, unknown>;
};

type PythonEnvelope = {
    result?: unknown;
    error?: { type?: string; message?: string };
};

type ToolDefinition = {
    name: string;
    description: string;
    inputSchema: Record<string, unknown>;
};

type TaskStatus = {
    task_id: string;
    status: string;
    running: boolean;
    stop_requested?: boolean;
    elapsed_s?: number;
    timeout_s?: number;
    stdout?: string;
    result?: unknown;
    error_type?: string | null;
    error?: string | null;
};

type TaskPayload = {
    ok: boolean;
    task: TaskStatus | null;
    tasks: TaskStatus[];
    latest_telemetry: unknown;
};

type TaskInfo = {
    taskID: string;
    process: Bun.Subprocess<"pipe", "pipe", "pipe">;
    statusPath: string;
    stopPath: string;
    startedMs: number;
    timeoutS: number;
    timeout: ReturnType<typeof setTimeout>;
    exitCode?: number;
    killedForTimeout: boolean;
    forceStopped: boolean;
};

const tools: ToolDefinition[] = [
    {
        name: "observe",
        description:
            "Read telemetry, vehicle state, stages, resources, engines, and target orbit.",
        inputSchema: objectSchema({}),
    },
    {
        name: "throttle",
        description: "Set vessel throttle from 0.0 to 1.0.",
        inputSchema: objectSchema({
            value: {
                type: "number",
                minimum: 0,
                maximum: 1,
                description: "Throttle setting.",
            },
        }),
    },
    {
        name: "stage",
        description: "Activate the next stage.",
        inputSchema: objectSchema({}),
    },
    {
        name: "reset_launchpad",
        description:
            "Revert KSP to the unpaused benchmark vessel on the launchpad.",
        inputSchema: objectSchema(
            {
                wait_s: {
                    type: "number",
                    minimum: 0,
                    description:
                        "Seconds to wait for the reverted vessel to become active. Defaults to 2.",
                },
            },
            [],
        ),
    },
    {
        name: "attitude",
        description:
            "Engage autopilot. Use mode=pitch_heading with pitch/heading, or hold prograde/retrograde/normal/anti_normal/radial/anti_radial in a reference frame.",
        inputSchema: objectSchema(
            {
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
                pitch: {
                    type: "number",
                    description:
                        "Pitch in degrees; required for pitch_heading.",
                },
                heading: {
                    type: "number",
                    description:
                        "Heading in degrees; required for pitch_heading.",
                },
                reference_frame: {
                    type: "string",
                    enum: ["orbital", "surface", "vessel_surface"],
                    description:
                        "Reference frame for vector modes. Defaults to orbital.",
                },
            },
            ["mode"],
        ),
    },
    {
        name: "wait",
        description:
            "Wait while flight continues and telemetry updates. Use if there's nothing to do for sometime, but be conservative and remember the game runs in realtime while you think",
        inputSchema: objectSchema({
            seconds: {
                type: "number",
                minimum: 0,
                description: "Seconds to wait.",
            },
        }),
    },
    {
        name: "execute_python",
        description:
            "Run a kRPC Python snippet for APIs the structured tools do not cover. It must return quickly; use it only for small control snippets. Use start_task for longer-running control logic.",
        inputSchema: objectSchema(
            {
                code: { type: "string", description: "Python code." },
                timeout_s: {
                    type: "number",
                    minimum: 0,
                    description: "Optional wall-clock timeout.",
                },
            },
            ["code"],
        ),
    },
    {
        name: "start_task",
        description:
            "Start a longer-running kRPC Python control loop. Returns a task_id for check_task/stop_task. This is where you could run more complex code/logic without blocking other actions.",
        inputSchema: objectSchema(
            {
                code: { type: "string", description: "Python code." },
                timeout_s: {
                    type: "number",
                    minimum: 0,
                    description: "Optional wall-clock timeout.",
                },
            },
            ["code"],
        ),
    },
    {
        name: "check_task",
        description:
            "Check background task status and latest telemetry. Omit task_id to list all tasks.",
        inputSchema: objectSchema(
            {
                task_id: {
                    type: "string",
                    description: "Optional task_id returned by start_task.",
                },
            },
            [],
        ),
    },
    {
        name: "stop_task",
        description:
            "Request cooperative stop for a background task. Pass task_id when multiple tasks are running.",
        inputSchema: objectSchema(
            {
                task_id: {
                    type: "string",
                    description: "Optional task_id returned by start_task.",
                },
            },
            [],
        ),
    },
];

const privilegedToolNames = new Set(["reset_launchpad"]);
const exposedTools = tools.filter(
    (tool) => !privilegedToolNames.has(tool.name) || resetToolEnabled(),
);
const toolNames = new Set(exposedTools.map((tool) => tool.name));
const foregroundToolNames = new Set([
    "observe",
    "throttle",
    "stage",
    "reset_launchpad",
    "attitude",
    "wait",
    "execute_python",
]);
const decoder = new TextDecoder();
const encoder = new TextEncoder();
const tasks = new Map<string, TaskInfo>();
let nextTaskID = 1;
let generatedRunDir: string | undefined;

class PythonProcessError extends Error {
    constructor(message: string) {
        super(message);
        this.name = "PythonProcessError";
    }
}

class PythonProcessTimeout extends PythonProcessError {
    constructor(message: string) {
        super(message);
        this.name = "PythonProcessTimeout";
    }
}

async function main(): Promise<void> {
    const stdin = Bun.stdin.stream().pipeThrough(new TextDecoderStream());
    let buffer = "";
    try {
        for await (const chunk of stdin) {
            buffer += chunk;
            while (true) {
                const newline = buffer.indexOf("\n");
                if (newline < 0) break;
                const line = buffer.slice(0, newline);
                buffer = buffer.slice(newline + 1);
                await handleLine(line);
            }
        }
    } finally {
        shutdownTasks();
    }
}

async function handleLine(line: string): Promise<void> {
    if (!line.trim()) return;
    let request: RpcRequest;
    try {
        request = JSON.parse(line);
    } catch {
        write({
            jsonrpc: "2.0",
            id: null,
            error: { code: -32700, message: "Parse error" },
        });
        return;
    }

    if (request.method === "notifications/initialized") return;
    if (request.id === undefined) return;

    try {
        const result = await handleRequest(request);
        write({ jsonrpc: "2.0", id: request.id, result });
    } catch (error) {
        write({
            jsonrpc: "2.0",
            id: request.id,
            error: {
                code: -32000,
                message: error instanceof Error ? error.message : String(error),
            },
        });
    }
}

async function handleRequest(
    request: RpcRequest,
): Promise<Record<string, unknown>> {
    switch (request.method) {
        case "initialize":
            return {
                protocolVersion: "2024-11-05",
                capabilities: { tools: {} },
                serverInfo: { name: "ksp-mcp", version: "0.1.0" },
            };
        case "ping":
            return {};
        case "tools/list":
            return { tools: exposedTools };
        case "tools/call":
            return callTool(request.params ?? {});
        case "resources/list":
            return { resources: [] };
        case "prompts/list":
            return { prompts: [] };
        default:
            throw new Error(`unsupported MCP method: ${request.method}`);
    }
}

async function callTool(
    params: Record<string, unknown>,
): Promise<Record<string, unknown>> {
    const name = params.name;
    const args = params.arguments ?? {};
    if (typeof name !== "string" || !toolNames.has(name)) {
        throw new Error(`unknown KSP tool: ${String(name)}`);
    }
    if (!isObject(args)) throw new Error("tool arguments must be an object");
    validateToolArguments(name, args);

    let result: unknown;
    if (name === "start_task") {
        result = startTask(args);
    } else if (name === "check_task") {
        result = checkTask(optionalString(args.task_id));
    } else if (name === "stop_task") {
        result = await stopTask(optionalString(args.task_id));
    } else if (foregroundToolNames.has(name)) {
        result = await callForegroundTool(name, args);
    } else {
        throw new Error(`unknown KSP tool: ${name}`);
    }

    const text = JSON.stringify(result, null, 2);
    return {
        content: [{ type: "text", text }],
        isError: isObject(result) && result.ok === false,
    };
}

async function callForegroundTool(
    name: string,
    args: Record<string, unknown>,
): Promise<unknown> {
    const result = await runPythonJson(
        "bench.ksp_call",
        {
            method: name,
            params: args,
            selected_vehicle: null,
        },
        toolTimeoutSeconds(name, args),
    );
    return result;
}

function startTask(args: Record<string, unknown>): Record<string, unknown> {
    const code = requiredString(args, "code");
    const timeoutS = taskTimeoutSeconds(args.timeout_s);
    const taskID = `task-${nextTaskID++}`;
    const taskDir = join(sessionRunDir(), "mcp_tasks", taskID);
    mkdirSync(taskDir, { recursive: true });
    const statusPath = join(taskDir, "status.json");
    const stopPath = join(taskDir, "stop");
    rmSync(stopPath, { force: true });

    const child = spawnPython("bench.ksp_task");
    const info: TaskInfo = {
        taskID,
        process: child,
        statusPath,
        stopPath,
        startedMs: Date.now(),
        timeoutS,
        timeout: setTimeout(() => {
            info.killedForTimeout = true;
            writeTaskPayload(info, timedOutTaskPayload(info));
            killProcess(info.process);
        }, (timeoutS + taskTimeoutPaddingSeconds()) * 1000),
        killedForTimeout: false,
        forceStopped: false,
    };
    tasks.set(taskID, info);

    void drainTaskOutput(info);
    void child.exited.then((code) => {
        info.exitCode = code;
        clearTimeout(info.timeout);
    });

    writeTaskPayload(info, runningTaskPayload(info));
    child.stdin.write(
        JSON.stringify({
            task_id: taskID,
            code,
            timeout_s: timeoutS,
            status_path: statusPath,
            stop_path: stopPath,
            selected_vehicle: null,
        }) + "\n",
    );
    child.stdin.end();
    return { ok: true, task_id: taskID, status: "running" };
}

function checkTask(taskID: string | undefined): TaskPayload {
    if (taskID) {
        const info = tasks.get(taskID);
        const payload = info ? readTaskPayload(info) : emptyTaskPayload();
        return {
            ok: true,
            task: payload.task,
            tasks: payload.task ? [payload.task] : [],
            latest_telemetry: payload.latest_telemetry,
        };
    }

    const payloads = [...tasks.values()].map(readTaskPayload);
    const statuses = payloads.flatMap((payload) =>
        payload.task ? [payload.task] : [],
    );
    return {
        ok: true,
        task: currentTaskStatus(statuses),
        tasks: statuses,
        latest_telemetry:
            [...payloads].reverse().find((payload) => payload.latest_telemetry)
                ?.latest_telemetry ?? null,
    };
}

async function stopTask(taskID: string | undefined): Promise<Record<string, unknown>> {
    const info = taskToStop(taskID);
    if (!info) return { ok: true, task: null };

    writeFileSync(info.stopPath, "stop\n", "utf-8");
    const graceMs = numberEnv("KSPBENCH_TASK_STOP_GRACE", 1) * 1000;
    await sleep(graceMs);
    const payload = readTaskPayload(info);
    if (payload.task?.running) {
        info.forceStopped = true;
        const stopped = stoppedTaskPayload(info, "force_stopped");
        writeTaskPayload(info, stopped);
        killProcess(info.process);
        return { ok: true, task: stopped.task };
    }
    return { ok: true, task: payload.task };
}

function taskToStop(taskID: string | undefined): TaskInfo | undefined {
    if (taskID) return tasks.get(taskID);

    const running = [...tasks.values()].filter(
        (task) => readTaskPayload(task).task?.running,
    );
    if (running.length > 1) {
        const ids = running.map((task) => task.taskID).join(", ");
        throw new Error(`multiple tasks are running; pass task_id (${ids})`);
    }
    if (running.length === 1) return running[0];
    return [...tasks.values()].at(-1);
}

async function runPythonJson(
    moduleName: string,
    payload: Record<string, unknown>,
    timeoutS: number,
): Promise<unknown> {
    const child = spawnPython(moduleName);
    const stdoutPromise = readStream(child.stdout);
    const stderrPromise = readStream(child.stderr);
    let timedOut = false;
    const timeout = setTimeout(() => {
        timedOut = true;
        killProcess(child);
    }, timeoutS * 1000);

    child.stdin.write(JSON.stringify(payload) + "\n");
    child.stdin.end();
    const exitCode = await child.exited.finally(() => clearTimeout(timeout));
    const [stdout, stderr] = await Promise.all([stdoutPromise, stderrPromise]);
    if (stderr.trim()) process.stderr.write(stderr);
    if (timedOut) {
        throw new PythonProcessTimeout(
            `${moduleName} timed out after ${timeoutS.toFixed(3)}s`,
        );
    }

    const envelope = parsePythonEnvelope(stdout);
    if (envelope.error) {
        throw new PythonProcessError(
            `${envelope.error.type ?? "PythonError"}: ${envelope.error.message ?? ""}`,
        );
    }
    if (exitCode !== 0) {
        throw new PythonProcessError(
            `${moduleName} exited with code ${exitCode}${stderr.trim() ? `: ${stderr.trim()}` : ""}`,
        );
    }
    return envelope.result;
}

function spawnPython(moduleName: string): Bun.Subprocess<"pipe", "pipe", "pipe"> {
    const python =
        process.env.KSPBENCH_PYTHON ??
        (existsSync(".venv/bin/python") ? ".venv/bin/python" : "python");
    return Bun.spawn([python, "-m", moduleName], {
        stdin: "pipe",
        stdout: "pipe",
        stderr: "pipe",
        env: childEnv(),
    });
}

function childEnv(): Record<string, string | undefined> {
    return {
        ...process.env,
        KSPBENCH_RUN_DIR: sessionRunDir(),
    };
}

function sessionRunDir(): string {
    const configured = process.env.KSPBENCH_RUN_DIR;
    if (configured) {
        mkdirSync(configured, { recursive: true });
        return configured;
    }
    generatedRunDir ??= join(
        process.cwd(),
        "runs",
        `${timestamp()}_${randomUUID().slice(0, 8)}_opencode_agent`,
    );
    mkdirSync(generatedRunDir, { recursive: true });
    return generatedRunDir;
}

async function readStream(stream: ReadableStream<Uint8Array>): Promise<string> {
    let text = "";
    for await (const chunk of stream) {
        text += decoder.decode(chunk);
    }
    return text;
}

async function drainTaskOutput(info: TaskInfo): Promise<void> {
    const [stdout, stderr] = await Promise.all([
        readStream(info.process.stdout),
        readStream(info.process.stderr),
    ]);
    if (stdout.trim()) {
        process.stderr.write(`ksp task ${info.taskID} stdout: ${stdout}`);
    }
    if (stderr.trim()) {
        process.stderr.write(stderr);
    }
}

function parsePythonEnvelope(stdout: string): PythonEnvelope {
    const lines = stdout.split(/\r?\n/).filter((line) => line.trim());
    if (lines.length !== 1) {
        throw new PythonProcessError(
            `expected one JSON response from Python, got ${lines.length}`,
        );
    }
    const parsed = JSON.parse(lines[0]);
    if (!isObject(parsed)) {
        throw new PythonProcessError("Python response must be an object");
    }
    return parsed as PythonEnvelope;
}

function readTaskPayload(info: TaskInfo): TaskPayload {
    if (info.killedForTimeout) return timedOutTaskPayload(info);
    if (info.forceStopped) return stoppedTaskPayload(info, "force_stopped");
    try {
        const parsed = JSON.parse(readFileSync(info.statusPath, "utf-8"));
        if (isTaskPayload(parsed)) return parsed;
    } catch {
        // Fall through to process-derived status.
    }
    if (info.exitCode !== undefined && info.exitCode !== 0) {
        return failedTaskPayload(info, `task process exited with code ${info.exitCode}`);
    }
    if (info.exitCode !== undefined) return stoppedTaskPayload(info, "exited");
    return runningTaskPayload(info);
}

function writeTaskPayload(info: TaskInfo, payload: TaskPayload): void {
    mkdirSync(join(sessionRunDir(), "mcp_tasks", info.taskID), { recursive: true });
    writeFileSync(info.statusPath, JSON.stringify(payload, null, 2) + "\n", "utf-8");
}

function runningTaskPayload(info: TaskInfo): TaskPayload {
    const task: TaskStatus = {
        task_id: info.taskID,
        status: "running",
        running: true,
        stop_requested: false,
        elapsed_s: elapsedSeconds(info),
        timeout_s: info.timeoutS,
        stdout: "",
        result: null,
        error_type: null,
        error: null,
    };
    return { ok: true, task, tasks: [task], latest_telemetry: null };
}

function timedOutTaskPayload(info: TaskInfo): TaskPayload {
    const task: TaskStatus = {
        task_id: info.taskID,
        status: "timed_out",
        running: false,
        stop_requested: false,
        elapsed_s: elapsedSeconds(info),
        timeout_s: info.timeoutS,
        stdout: "",
        result: null,
        error_type: "TaskTimeout",
        error: `task exceeded ${info.timeoutS.toFixed(3)}s`,
    };
    return { ok: true, task, tasks: [task], latest_telemetry: null };
}

function stoppedTaskPayload(info: TaskInfo, status: string): TaskPayload {
    const task: TaskStatus = {
        task_id: info.taskID,
        status,
        running: false,
        stop_requested: true,
        elapsed_s: elapsedSeconds(info),
        timeout_s: info.timeoutS,
        stdout: "",
        result: null,
        error_type: null,
        error: null,
    };
    return { ok: true, task, tasks: [task], latest_telemetry: null };
}

function failedTaskPayload(info: TaskInfo, error: string): TaskPayload {
    const task: TaskStatus = {
        task_id: info.taskID,
        status: "failed",
        running: false,
        elapsed_s: elapsedSeconds(info),
        timeout_s: info.timeoutS,
        stdout: "",
        result: null,
        error_type: "TaskProcessError",
        error,
    };
    return { ok: true, task, tasks: [task], latest_telemetry: null };
}

function emptyTaskPayload(): TaskPayload {
    return { ok: true, task: null, tasks: [], latest_telemetry: null };
}

function isTaskPayload(value: unknown): value is TaskPayload {
    if (!isObject(value)) return false;
    return (
        typeof value.ok === "boolean" &&
        (value.task === null || isObject(value.task)) &&
        Array.isArray(value.tasks)
    );
}

function currentTaskStatus(statuses: TaskStatus[]): TaskStatus | null {
    const running = statuses.filter((status) => status.running);
    if (running.length) return running.at(-1) ?? null;
    return statuses.at(-1) ?? null;
}

function shutdownTasks(): void {
    for (const info of tasks.values()) {
        clearTimeout(info.timeout);
        if (readTaskPayload(info).task?.running) {
            killProcess(info.process);
        }
    }
}

function killProcess(child: Bun.Subprocess<"pipe", "pipe", "pipe">): void {
    try {
        child.kill();
    } catch {
        // ignore already-exited children
    }
}

function write(payload: Json): void {
    Bun.stdout.write(encoder.encode(JSON.stringify(payload) + "\n"));
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
    };
}

function resetToolEnabled(): boolean {
    return truthyEnv(process.env.KSPBENCH_ENABLE_RESET_TOOL);
}

function truthyEnv(value: string | undefined): boolean {
    return (
        value === "1" || value === "true" || value === "yes" || value === "on"
    );
}

function toolTimeoutSeconds(
    name: string,
    args: Record<string, unknown>,
): number {
    const defaultTimeout = numberEnv("KSPBENCH_MCP_TOOL_TIMEOUT", 5);
    const pollInterval = numberEnv("KSPBENCH_POLL_INTERVAL", 0.5);
    const padding = numberEnv(
        "KSPBENCH_MCP_TOOL_TIMEOUT_PADDING",
        Math.max(1, pollInterval * 2),
    );
    switch (name) {
        case "wait":
            return Math.max(defaultTimeout, optionalNumber(args.seconds) + padding);
        case "execute_python":
            return Math.max(
                defaultTimeout,
                boundedExecutionTimeout(args.timeout_s) + padding,
            );
        case "reset_launchpad":
            return Math.max(defaultTimeout, optionalNumber(args.wait_s) + padding);
        default:
            return defaultTimeout;
    }
}

function boundedExecutionTimeout(value: unknown): number {
    const requested = optionalNumber(value);
    const defaultExecution = numberEnv("KSPBENCH_EXECUTION_TIMEOUT", 15);
    const maxSync = numberEnv("KSPBENCH_MAX_SYNC_PYTHON", 8);
    const effective = requested > 0 ? requested : defaultExecution;
    return Math.min(effective, maxSync);
}

function taskTimeoutSeconds(value: unknown): number {
    const requested = optionalNumber(value);
    return requested > 0 ? requested : numberEnv("KSPBENCH_TASK_TIMEOUT", 180);
}

function taskTimeoutPaddingSeconds(): number {
    return numberEnv("KSPBENCH_TASK_TIMEOUT_PADDING", 2);
}

function elapsedSeconds(info: TaskInfo): number {
    return Math.round(((Date.now() - info.startedMs) / 1000) * 1000) / 1000;
}

function timestamp(): string {
    return new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function validateToolArguments(
    name: string,
    args: Record<string, unknown>,
): void {
    switch (name) {
        case "observe":
        case "stage":
            rejectUnexpected(name, args, []);
            return;
        case "reset_launchpad":
            rejectUnexpected(name, args, ["wait_s"]);
            if (args.wait_s !== undefined && args.wait_s !== null) {
                const wait = requiredNumber(args, "wait_s");
                if (wait < 0)
                    throw new Error(
                        "reset_launchpad.wait_s must be non-negative",
                    );
            }
            return;
        case "throttle": {
            rejectUnexpected(name, args, ["value"]);
            const value = requiredNumber(args, "value");
            if (value < 0 || value > 1)
                throw new Error("throttle.value must be between 0 and 1");
            return;
        }
        case "attitude": {
            rejectUnexpected(name, args, [
                "mode",
                "pitch",
                "heading",
                "reference_frame",
            ]);
            if (typeof args.mode !== "string")
                throw new Error("attitude.mode must be a string");
            if (args.mode === "pitch_heading") {
                requiredNumber(args, "pitch");
                requiredNumber(args, "heading");
            }
            if (
                args.reference_frame !== undefined &&
                args.reference_frame !== null &&
                typeof args.reference_frame !== "string"
            ) {
                throw new Error("attitude.reference_frame must be a string");
            }
            return;
        }
        case "wait": {
            rejectUnexpected(name, args, ["seconds"]);
            const seconds = requiredNumber(args, "seconds");
            if (seconds < 0)
                throw new Error("wait.seconds must be non-negative");
            return;
        }
        case "execute_python":
        case "start_task": {
            rejectUnexpected(name, args, ["code", "timeout_s"]);
            if (typeof args.code !== "string")
                throw new Error(`${name}.code must be a string`);
            if (args.timeout_s !== undefined && args.timeout_s !== null) {
                const timeout = requiredNumber(args, "timeout_s");
                if (timeout < 0)
                    throw new Error(`${name}.timeout_s must be non-negative`);
            }
            return;
        }
        case "check_task":
        case "stop_task":
            rejectUnexpected(name, args, ["task_id"]);
            if (
                args.task_id !== undefined &&
                args.task_id !== null &&
                typeof args.task_id !== "string"
            ) {
                throw new Error(`${name}.task_id must be a string`);
            }
            return;
        default:
            throw new Error(`unknown KSP tool: ${name}`);
    }
}

function rejectUnexpected(
    toolName: string,
    args: Record<string, unknown>,
    allowed: string[],
): void {
    for (const key of Object.keys(args)) {
        if (!allowed.includes(key))
            throw new Error(`${toolName}.${key} is not a supported argument`);
    }
}

function requiredString(args: Record<string, unknown>, key: string): string {
    const value = args[key];
    if (typeof value !== "string") throw new Error(`${key} must be a string`);
    return value;
}

function requiredNumber(args: Record<string, unknown>, key: string): number {
    const value = args[key];
    if (typeof value !== "number" || !Number.isFinite(value)) {
        throw new Error(`${key} must be a finite number`);
    }
    return value;
}

function requiredInteger(args: Record<string, unknown>, key: string): number {
    const value = requiredNumber(args, key);
    if (!Number.isInteger(value)) throw new Error(`${key} must be an integer`);
    return value;
}

function optionalNumber(value: unknown): number {
    return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function optionalString(value: unknown): string | undefined {
    return typeof value === "string" ? value : undefined;
}

function numberEnv(name: string, fallback: number): number {
    const value = process.env[name];
    if (value === undefined) return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

await main();
