import {readFileSync} from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const runtimeRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
let installed = {};
try { installed = JSON.parse(readFileSync(path.join(runtimeRoot, "runtime.local.json"), "utf8")); }
catch (error) { if (error.code !== "ENOENT") throw error; }

export const paths = {
  python: process.env.OMP_KIT_PYTHON || installed.python,
  memoryDb: process.env.OMP_KIT_MEMORY_DB || installed.memoryDb,
  graphify: process.env.OMP_KIT_GRAPHIFY || installed.graphify,
  memoryScript: path.join(runtimeRoot, "python", "memory.py"),
};
