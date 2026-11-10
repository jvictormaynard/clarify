import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

type Reply = { id: number; result?: { accountState?: { usage?: Record<string, unknown> } }; error?: unknown };
type Request = { method: string; args?: unknown[] };

// One owner per test. A dead controller must reject callers instead of leaving
// route handlers waiting until the browser test times out.
export class SettingsProcess {
  readonly child: ChildProcessWithoutNullStreams;
  private sequence = 0;
  private pending = new Map<number, { resolve: (reply: Reply) => void; reject: (error: Error) => void }>();
  private failure?: Error;
  private closed: Promise<void>;
  private lines;

  constructor(command: string, args: string[], env: NodeJS.ProcessEnv) {
    this.child = spawn(command, args, { windowsHide: true, env });
    this.closed = new Promise(resolve => this.child.once("close", () => {
      this.fail(new Error("Settings controller closed"));
      resolve();
    }));
    this.child.on("error", error => this.fail(error));
    this.child.stdin.on("error", error => this.fail(error));
    this.child.stderr.on("data", data => process.stderr.write(data));
    this.lines = createInterface({ input: this.child.stdout });
    this.lines.on("line", line => {
      try {
        const reply = JSON.parse(line) as Reply;
        this.pending.get(reply.id)?.resolve(reply);
        this.pending.delete(reply.id);
      } catch {
        this.fail(new Error("Invalid Settings controller reply"));
      }
    });
  }

  private fail(error: Error) {
    this.failure ??= error;
    for (const request of this.pending.values()) request.reject(error);
    this.pending.clear();
  }

  request(request: Request): Promise<Reply> {
    if (this.failure) return Promise.reject(this.failure);
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.child.stdin.write(JSON.stringify({ ...request, id }) + "\n", error => {
        if (error) this.fail(error);
      });
    });
  }

  async stop() {
    this.fail(new Error("Settings controller stopped"));
    // The Python fixture owns a temporary profile and Qt cleanup. Let it quit
    // normally first, then kill and await close if startup or shutdown stalled.
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      if (!this.child.stdin.destroyed && !this.child.stdin.writableEnded) {
        this.child.stdin.end(JSON.stringify({ method: "quit" }) + "\n");
      }
      timer = setTimeout(() => this.child.kill(), 5_000);
      await this.closed;
    } finally {
      clearTimeout(timer);
      this.lines.close();
    }
  }
}
