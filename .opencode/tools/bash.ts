import { tool } from "@opencode-ai/plugin"

function referenceRoot(context: { worktree?: string; directory?: string }): string {
  const configured = Bun.env.KSPBENCH_REFERENCE_ROOT ?? process.env.KSPBENCH_REFERENCE_ROOT
  if (configured) return configured
  const root = context.worktree ?? context.directory ?? process.cwd()
  return `${root}/.opencode/ksp/krpc_reference`
}

export default tool({
  description:
    "Run read/search shell commands in a Just Bash overlay mounted on the kRPC reference tree.",
  args: {
    command: tool.schema
      .string()
      .describe("Shell command to run against the kRPC reference tree."),
  },
  async execute(args, context) {
    const root = referenceRoot(context)
    try {
      const proc = Bun.spawnSync(["just-bash", "-c", args.command, "--root", root, "--json"], {
        stdout: "pipe",
        stderr: "pipe",
      })
      const stdout = new TextDecoder().decode(proc.stdout)
      const stderr = new TextDecoder().decode(proc.stderr)
      if (stdout.trim().startsWith("{")) return stdout.trim()
      return JSON.stringify({
        stdout,
        stderr,
        exitCode: proc.exitCode,
        root,
      })
    } catch (error) {
      return JSON.stringify({
        stdout: "",
        stderr:
          "just-bash is not installed or not on PATH. Install it with `npm install -g just-bash`, or use OpenCode read/grep/glob on .opencode/ksp/krpc_reference.",
        exitCode: 127,
        root,
        error: error instanceof Error ? error.message : String(error),
      })
    }
  },
})
