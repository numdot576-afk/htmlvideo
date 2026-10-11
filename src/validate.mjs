// Checks that a video HTML file actually works: loads with no errors, follows the render
// contract, and draws real pictures (not a black or frozen canvas) across its whole length.
//   node src/validate.mjs videos/how-a-bicycle-works.html [--shots out/dir]
import fs from "node:fs";
import path from "node:path";
import { openVideo, grabFrame, dataUrlToBuffer } from "./browser.mjs";

export async function validate(file, { shotsDir, samples = 8 } = {}) {
  const { browser, page, errors } = await openVideo(file);
  const problems = [...errors];
  let duration = 0;
  try {
    if (!problems.some((p) => p.startsWith("timeout"))) {
      duration = await page.evaluate(() => Number(window.VIDEO.duration));
      if (!(duration >= 5 && duration <= 180)) problems.push(`window.VIDEO.duration is ${duration}; expected 5-180 seconds`);
      else {
        if (shotsDir) fs.mkdirSync(shotsDir, { recursive: true });
        const stats = [];
        for (let i = 0; i < samples; i++) {
          const t = (duration * (i + 0.5)) / samples;
          try {
            const url = await grabFrame(page, t);
            if (shotsDir) fs.writeFileSync(path.join(shotsDir, `frame-${String(i).padStart(2, "0")}.jpg`), dataUrlToBuffer(url));
            stats.push({ t, ...(await frameStats(page)) });
          } catch (e) {
            problems.push(`VIDEO.seek(${t.toFixed(2)}) threw: ${e.message.split("\n")[0]}`);
          }
        }
        for (const s of stats) {
          if (s.std < 6) problems.push(`frame at ${s.t.toFixed(1)}s is almost flat (std ${s.std.toFixed(1)}): blank or black picture`);
        }
        if (stats.length > 2 && new Set(stats.map((s) => s.hash)).size === 1) problems.push("every sampled frame is identical: the animation does not move");
      }
      // errors raised while seeking land in the same array
      for (const e of errors) if (!problems.includes(e)) problems.push(e);
    }
  } finally {
    await browser.close();
  }
  return { ok: problems.length === 0, problems, duration };
}

// brightness spread and a cheap fingerprint of the current canvas, sampled on a coarse grid
function frameStats(page) {
  return page.evaluate(() => {
    const c = document.getElementById("out"),
      g = c.getContext("2d"),
      d = g.getImageData(0, 0, c.width, c.height).data;
    let n = 0, sum = 0, sq = 0, hash = 0;
    for (let y = 0; y < c.height; y += 24)
      for (let x = 0; x < c.width; x += 24) {
        const i = (y * c.width + x) * 4, l = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
        n++; sum += l; sq += l * l; hash = (hash * 31 + (l | 0)) | 0;
      }
    const mean = sum / n;
    return { std: Math.sqrt(Math.max(0, sq / n - mean * mean)), hash };
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const file = process.argv[2];
  if (!file) {
    console.error("usage: node src/validate.mjs <video.html> [--shots dir]");
    process.exit(2);
  }
  const i = process.argv.indexOf("--shots");
  const r = await validate(file, { shotsDir: i > 0 ? process.argv[i + 1] : undefined });
  console.log(r.ok ? `OK  ${file}  (${r.duration.toFixed(1)} s)` : `FAILED  ${file}\n  - ${r.problems.join("\n  - ")}`);
  process.exit(r.ok ? 0 : 1);
}
