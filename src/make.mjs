// AI video maker: topic in, checked HTML video + MP4 out.
//
//   node src/make.mjs "How a bicycle gear works"
//   node src/make.mjs "How a lock works" --notes "pin tumbler lock, show the key lifting the pins" --no-render
//   node src/make.mjs --revise videos/how-a-lock-works.html "make scene 3 slower and add a callout on the shear line"
//
// Options: --notes "..."   extra direction for Claude
//          --out dir       where to write (default: videos/)
//          --fixes N       automatic fix rounds when the headless check fails (default 2)
//          --effort level  low | medium | high | xhigh | max (default high)
//          --model id      Claude model (default claude-opus-5-5, or $VIDEO_MODEL)
//          --no-render     skip the MP4
import fs from "node:fs";
import path from "node:path";
import { Session, slugify, DEFAULT_MODEL } from "./claude.mjs";
import { validate } from "./validate.mjs";
import { render } from "./render.mjs";

const args = process.argv.slice(2);
const flags = new Set(["--no-render"]);
const opts = {};
const pos = [];
for (let i = 0; i < args.length; i++) {
  if (flags.has(args[i])) opts[args[i].slice(2)] = true;
  else if (args[i].startsWith("--")) opts[args[i].slice(2)] = args[++i];
  else pos.push(args[i]);
}
const revising = opts.revise !== undefined;
if (!pos[0]) {
  console.error('usage: node src/make.mjs "How X works" [--notes "..."] [--no-render]\n       node src/make.mjs --revise videos/file.html "what to change"');
  process.exit(2);
}
if (!process.env.ANTHROPIC_API_KEY && !process.env.ANTHROPIC_AUTH_TOKEN) {
  console.error("Set ANTHROPIC_API_KEY first (https://console.anthropic.com/settings/keys).");
  process.exit(2);
}

const session = new Session({ model: opts.model || DEFAULT_MODEL, effort: opts.effort || "high" });
const outDir = opts.out || "videos";
fs.mkdirSync(outDir, { recursive: true });

let html, file;
if (revising) {
  file = opts.revise;
  console.log(`Revising ${file}: ${pos.join(" ")}`);
  html = await session.revise(fs.readFileSync(file, "utf8"), pos.join(" "));
} else {
  const topic = pos.join(" ");
  file = path.join(outDir, `${slugify(topic)}.html`);
  console.log(`Writing "${topic}" with ${session.model}…`);
  html = await session.create(topic, opts.notes || "");
}

const maxFixes = Number(opts.fixes ?? 2);
let result;
for (let round = 0; ; round++) {
  fs.writeFileSync(file, html);
  console.log(`Checking ${file} in headless Chromium…`);
  result = await validate(file, { shotsDir: path.join("out", path.basename(file, ".html")) });
  if (result.ok) break;
  console.log(`  ${result.problems.length} problem(s):\n  - ${result.problems.join("\n  - ")}`);
  if (round >= maxFixes) break;
  console.log(`Asking Claude to fix them (round ${round + 1}/${maxFixes})…`);
  html = await session.fix(result.problems);
}

if (!result.ok) {
  console.error(`\n${file} still fails the check. It is saved so you can open it, or run:\n  node src/make.mjs --revise ${file} "fix: ${result.problems[0]}"`);
  process.exit(1);
}
console.log(`OK: ${file} (${result.duration.toFixed(1)} s). Preview frames: out/${path.basename(file, ".html")}/`);

if (!opts["no-render"]) {
  console.log("Rendering MP4…");
  const r = await render(file, {
    onProgress: (f, n) => { if (f % 30 === 0 || f === n) process.stdout.write(`\r  frame ${f}/${n}`); },
  });
  console.log(`\nDone: ${r.out}`);
}
