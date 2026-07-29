#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const launcherDir = path.dirname(fileURLToPath(import.meta.url));
const serverPath = path.join(launcherDir, "server.py");

const candidates = process.platform === "win32"
  ? [
      { command: "py", prefix: ["-3"] },
      { command: "python3", prefix: [] },
      { command: "python", prefix: [] },
    ]
  : [
      { command: "python3", prefix: [] },
      { command: "python", prefix: [] },
    ];

let selected = null;
for (const candidate of candidates) {
  const probe = spawnSync(candidate.command, [...candidate.prefix, "--version"], {
    encoding: "utf8",
    shell: false,
    windowsHide: true,
  });
  if (probe.status === 0) {
    selected = candidate;
    break;
  }
}

if (!selected) {
  process.stderr.write(
    "Code Ontology Companion requires Python 3.9 or newer. " +
      "The plugin does not install runtimes automatically.\n",
  );
  process.exit(1);
}

const child = spawn(selected.command, [...selected.prefix, serverPath], {
  cwd: path.dirname(launcherDir),
  env: process.env,
  shell: false,
  stdio: "inherit",
  windowsHide: true,
});

child.on("error", (error) => {
  process.stderr.write(`Failed to start Code Ontology Companion MCP: ${error.message}\n`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
