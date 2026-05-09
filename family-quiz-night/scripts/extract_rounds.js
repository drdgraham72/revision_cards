#!/usr/bin/env node
// ABOUTME: One-shot migrator: extracts inline ROUNDS array from frontend/index.html
// ABOUTME: into per-round JSON files + a rounds-index.json. Run once after install.

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const HTML_PATH = path.join(ROOT, "frontend", "index.html");
const OUT_DIR = path.join(ROOT, "frontend", "data", "rounds");
const INDEX_PATH = path.join(ROOT, "frontend", "data", "rounds-index.json");

function extractArrayLiteral(code, name) {
  // Find `const NAME=` or `const NAME =` and walk to its matching `]`.
  const re = new RegExp(`const\\s+${name}\\s*=\\s*\\[`);
  const m = re.exec(code);
  if (!m) throw new Error(`${name} not found in script`);
  const start = m.index + m[0].length - 1; // index of the opening [
  let depth = 0;
  let inStr = null; // null | "'" | '"' | '`'
  let prev = "";
  for (let i = start; i < code.length; i++) {
    const c = code[i];
    if (inStr) {
      if (c === inStr && prev !== "\\") inStr = null;
    } else if (c === "'" || c === '"' || c === "`") {
      inStr = c;
    } else if (c === "[" || c === "{" || c === "(") {
      depth++;
    } else if (c === "]" || c === "}" || c === ")") {
      depth--;
      if (depth === 0 && c === "]") {
        return code.slice(start, i + 1);
      }
    }
    prev = c;
  }
  throw new Error(`Unterminated ${name} array`);
}

function main() {
  const html = fs.readFileSync(HTML_PATH, "utf8");
  const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!scriptMatch) throw new Error("No <script> block in index.html");
  const code = scriptMatch[1];

  const roundsLiteral = extractArrayLiteral(code, "ROUNDS");
  // Evaluate inside an isolated Function so we don't run any DOM code.
  const ROUNDS = new Function(`return ${roundsLiteral};`)();
  if (!Array.isArray(ROUNDS)) throw new Error("ROUNDS did not eval to an array");

  fs.mkdirSync(OUT_DIR, { recursive: true });

  const indexEntries = [];
  for (const round of ROUNDS) {
    const data = {
      id: round.id,
      topic: round.topic,
      title: round.title,
      desc: round.desc,
      type: round.type || "standard",
      isNew: !!round.isNew,
      questions: round.questions || [],
    };
    fs.writeFileSync(
      path.join(OUT_DIR, `${round.id}.json`),
      JSON.stringify(data, null, 2),
      "utf8"
    );
    indexEntries.push({
      id: data.id,
      topic: data.topic,
      title: data.title,
      desc: data.desc,
      type: data.type,
      isNew: data.isNew,
      count: data.questions.length,
    });
  }

  const indexDoc = {
    version: 1,
    generated: new Date().toISOString().slice(0, 10),
    rounds: indexEntries,
  };
  fs.mkdirSync(path.dirname(INDEX_PATH), { recursive: true });
  fs.writeFileSync(INDEX_PATH, JSON.stringify(indexDoc, null, 2), "utf8");

  console.log(`Wrote ${indexEntries.length} rounds → ${OUT_DIR}`);
  console.log(`Index: ${INDEX_PATH}`);
}

main();
