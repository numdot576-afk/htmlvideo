// Talks to Claude: writes a new video, revises an existing one, or fixes one that failed validation.
// The house-style guide and the two example videos go in a cached system prompt, so follow-up
// calls (fix rounds, more videos) re-read them at a fraction of the cost.
import Anthropic from "@anthropic-ai/sdk";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const EXAMPLES = ["examples/how-morse-code-works.html", "examples/how-a-clutch-works.html"];

export const DEFAULT_MODEL = process.env.VIDEO_MODEL || "claude-opus-5-5";

function systemBlocks() {
  const blocks = [{ type: "text", text: read("prompts/system.md") }];
  for (const f of EXAMPLES) blocks.push({ type: "text", text: `<reference_video file="${path.basename(f)}">\n${read(f)}\n</reference_video>` });
  blocks[blocks.length - 1].cache_control = { type: "ephemeral" };
  return blocks;
}

export class Session {
  constructor({ model = DEFAULT_MODEL, effort = "high", log = (s) => process.stderr.write(s) } = {}) {
    this.client = new Anthropic();
    this.model = model;
    this.effort = effort;
    this.log = log;
    this.messages = [];
  }

  // first request for a brand-new video
  create(topic, notes = "") {
    let msg = `Make the video: "${topic}".`;
    if (notes) msg += `\n\nDirection from the producer:\n${notes}`;
    return this.#send(msg);
  }

  // start from an existing file and apply a change request
  revise(html, change) {
    return this.#send(`Here is the current video file:\n\n${html}\n\nRevise it: ${change}\n\nReturn the complete updated file.`);
  }

  // follow-up in the same conversation after the headless check found problems
  fix(problems) {
    return this.#send(
      `I loaded your file in headless Chromium and it failed these checks:\n- ${problems.join("\n- ")}\n\n` +
        `Fix the causes (keep everything that works) and return the complete corrected file.`,
    );
  }

  async #send(text) {
    this.messages.push({ role: "user", content: text });
    const stream = this.client.beta.messages.stream({
      model: this.model,
      max_tokens: 128000,
      thinking: { type: "adaptive" },
      output_config: { effort: this.effort },
      // if a safety classifier declines, the API retries on its recommended fallback model instead of failing
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: systemBlocks(),
      messages: this.messages,
    });
    let chars = 0;
    stream.on("text", (t) => {
      chars += t.length;
      if (chars % 4000 < t.length) this.log(`\r  writing… ${Math.round(chars / 1000)} kB`);
    });
    const msg = await stream.finalMessage();
    this.log(`\r  received ${Math.round(chars / 1000)} kB (${msg.usage.output_tokens} output tokens, ${msg.usage.cache_read_input_tokens ?? 0} cached input tokens)\n`);

    if (msg.stop_reason === "refusal") throw new Error(`Claude declined this request (${msg.stop_details?.category ?? "no category"}).`);
    if (msg.stop_reason === "max_tokens") throw new Error("The reply hit the output limit before the file was finished; try a simpler topic or fewer scenes.");
    // keep the reply exactly as returned (thinking blocks included) so the next turn continues the same conversation
    this.messages.push({ role: "assistant", content: msg.content });

    const out = msg.content.filter((b) => b.type === "text").map((b) => b.text).join("");
    return extractHtml(out);
  }
}

export function extractHtml(text) {
  const start = text.search(/<!doctype html/i);
  const end = text.toLowerCase().lastIndexOf("</html>");
  if (start < 0 || end < start) throw new Error("Claude's reply did not contain a complete HTML file.");
  return text.slice(start, end + "</html>".length) + "\n";
}

export const slugify = (s) =>
  s.toLowerCase().normalize("NFKD").replace(/[^\w\s-]/g, "").trim().replace(/[\s_-]+/g, "-").slice(0, 60) || "video";
