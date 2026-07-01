#!/usr/bin/env node
/**
 * Cursor hook — stop (fin de tour agent)
 * Bumps Y si le worktree a changé (hors meta version seule).
 * Opt-out : "même Y" / "same Y" via CURSOR_TRANSCRIPT_PATH si dispo.
 * Fail-open — stdout {} uniquement (pas de followup_message).
 */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  getChangedPaths,
  getWorktreeFingerprint,
  isVersionMetaOnlyChange,
  readRevisionState,
} from "../../scripts/lib/worktree-fingerprint.mjs";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

function readStdin() {
  try {
    return readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function readLastUserMessageFromTranscript() {
  const transcriptPath = process.env.CURSOR_TRANSCRIPT_PATH;
  if (!transcriptPath || !existsSync(transcriptPath)) {
    return "";
  }
  try {
    const lines = readFileSync(transcriptPath, "utf8").trim().split("\n");
    for (let index = lines.length - 1; index >= 0; index -= 1) {
      const line = lines[index]?.trim();
      if (!line) {
        continue;
      }
      const event = JSON.parse(line);
      const role = event.role || event.type;
      if (role === "user") {
        const body = event.message?.content || event.text || event.content || event.prompt;
        if (typeof body === "string" && body.trim()) {
          return body;
        }
        if (Array.isArray(body)) {
          const textPart = body.find((part) => typeof part?.text === "string");
          if (textPart?.text) {
            return textPart.text;
          }
        }
      }
    }
  } catch {
    return "";
  }
  return "";
}

let hookStatus = "completed";
try {
  const data = JSON.parse(readStdin() || "{}");
  hookStatus = String(data.status || "completed");
} catch {
  hookStatus = "completed";
}

if (hookStatus !== "completed") {
  console.log("{}");
  process.exit(0);
}

const lastUserMessage = readLastUserMessageFromTranscript();
if (/même\s*Y|same\s*Y/i.test(lastUserMessage)) {
  console.log("{}");
  process.exit(0);
}

const stored = readRevisionState(repoRoot);
const storedFingerprint = String(stored.fingerprint || "");
const currentFingerprint = getWorktreeFingerprint(repoRoot);

if (!storedFingerprint || storedFingerprint === currentFingerprint) {
  console.log("{}");
  process.exit(0);
}

const changedPaths = getChangedPaths(repoRoot);
if (isVersionMetaOnlyChange(changedPaths, repoRoot)) {
  console.log("{}");
  process.exit(0);
}

spawnSync(process.execPath, [join(repoRoot, "scripts", "bump-task.mjs")], {
  cwd: repoRoot,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"],
});

console.log("{}");
process.exit(0);
