import fs from "node:fs/promises";
import path from "node:path";

export async function loadGraph(project) {
  const root = await fs.realpath(project);
  const file = path.join(root, "graphify-out", "graph.json");
  const stat = await fs.stat(file);
  if (stat.size > 64 * 1024 * 1024) throw new Error("Graph exceeds the 64 MiB local read limit; select a smaller project graph.");
  const data = JSON.parse(await fs.readFile(file, "utf8"));
  if (!Array.isArray(data.nodes)) throw new Error("Graph has no nodes array.");
  const vocab = new Set();
  for (const node of data.nodes) {
    const words = String(node.label ?? "").match(/[^\W\d_]+|[\p{L}]+/gu) ?? [];
    for (const word of words) for (const part of word.match(/[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+/g) ?? [word]) {
      const token = part.toLocaleLowerCase();
      if (token.length >= 3 && token.length <= 30) vocab.add(token);
    }
  }
  return { root, file, stat, data, vocabulary: [...vocab].sort() };
}

export async function graphStatus(graph) {
  let changed = 0, missing = 0, outside = 0;
  const sourceFiles = [...new Set(graph.data.nodes.map(n => n.source_file).filter(s => typeof s === "string" && s))];
  for (const src of sourceFiles.slice(0, 1000)) {
    const filename = path.resolve(graph.root, src);
    const relative = path.relative(graph.root, filename);
    if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) { outside++; continue; }
    try { if ((await fs.stat(filename)).mtimeMs > graph.stat.mtimeMs) changed++; }
    catch (error) { if (error.code === "ENOENT") missing++; else throw error; }
  }
  return {
    project: graph.root, graph: graph.file, modified: graph.stat.mtime.toISOString(),
    nodes: graph.data.nodes.length, vocabularyTokens: graph.vocabulary.length,
    sourceFiles: sourceFiles.length, checked: Math.min(sourceFiles.length, 1000),
    newerSources: changed, missingSources: missing, sourcesOutsideProject: outside,
    freshness: "mtime heuristic only; verify cited source files before relying on the graph",
  };
}

export function queryTerms(terms, graph) {
  if (!Array.isArray(terms) || terms.length < 1 || terms.length > 12 || terms.some(t => typeof t !== "string" || !graph.vocabulary.includes(t)))
    throw new Error("Choose 1–12 exact tokens returned by project_graph action=vocab. No invented synonyms.");
  return [...new Set(terms)];
}

export function clip(text, chars = 8000) {
  return text.length > chars ? text.slice(0, chars) + "\n[Output capped; narrow the query.]" : text;
}
