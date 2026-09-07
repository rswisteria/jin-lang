import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

/** `jin_cli.editor.URL_PREFIX` と同じ文字列。ずれたら起動が読めなくなる。 */
const URL_PREFIX = "jin editor url: ";

const REPO_ROOT = resolve(import.meta.dirname, "../../..");

export interface RunningEditor {
  readonly url: string;
  readonly file: string;
  /** サーバ側の stderr。失敗したときに原因を見るために貯めておく。 */
  log(): string;
  stop(): void;
}

/** 一時ディレクトリに `.jin` を置き、`jin editor --no-browser` を起動して URL を読む。 */
export async function startEditor(source: string): Promise<RunningEditor> {
  const dir = mkdtempSync(join(tmpdir(), "jin-editor-e2e-"));
  const file = join(dir, "smoke.jin");
  writeFileSync(file, source, "utf8");

  const child = spawn(
    "uv",
    ["run", "jin", "editor", file, "--no-browser"],
    { cwd: REPO_ROOT, stdio: ["ignore", "pipe", "pipe"] },
  );

  let buffered = "";
  const url = await new Promise<string>((resolvePromise, rejectPromise) => {
    const timer = setTimeout(() => {
      rejectPromise(new Error(`jin editor が URL を出しません:\n${buffered}`));
    }, 60_000);
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      buffered += chunk;
      for (const line of buffered.split("\n")) {
        if (line.startsWith(URL_PREFIX)) {
          clearTimeout(timer);
          resolvePromise(line.slice(URL_PREFIX.length).trim());
          return;
        }
      }
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      rejectPromise(new Error(`jin editor が exit ${code} で終わりました:\n${buffered}`));
    });
  });

  return {
    url,
    file,
    log: () => buffered,
    stop: () => {
      child.kill("SIGINT");
    },
  };
}

export { REPO_ROOT };
