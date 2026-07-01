#!/usr/bin/env node
/**
 * Cursor hook — beforeSubmitPrompt
 * Bumps X on each user message unless opt-out "même X" / "same X".
 * Fail-open: never blocks the prompt.
 * stdout: { "continue": true } only (no agent_message — ignored by Cursor).
 */
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

function readStdin() {
  try {
    return readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function extractPromptText(data) {
  const candidates = [data.prompt, data.text, data.userMessage, data.message, data.content, data.input];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return "";
}

let promptText = "";
try {
  const data = JSON.parse(readStdin() || "{}");
  promptText = extractPromptText(data);
} catch {
  promptText = "";
}

if (/même\s*X|same\s*X/i.test(promptText)) {
  console.log(JSON.stringify({ continue: true }));
  process.exit(0);
}

spawnSync(process.execPath, [join(repoRoot, "scripts", "bump-prompt.mjs")], {
  cwd: repoRoot,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"],
});

console.log(JSON.stringify({ continue: true }));
process.exit(0);
