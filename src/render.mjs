// Renders a video HTML file to MP4, frame by frame (so it is smooth no matter how slow the machine is).
//   node src/render.mjs videos/how-a-bicycle-works.html [--out file.mp4] [--fps 30]
import { spawn } from "node:child_process";
import { openVideo, grabFrame, dataUrlToBuffer } from "./browser.mjs";

export async function render(file, { out = file.replace(/\.html?$/i, ".mp4"), fps = 30, onProgress } = {}) {
  const { browser, page, errors } = await openVideo(file);
  try {
    if (errors.length) throw new Error(`page has errors, run validate first:\n  ${errors.join("\n  ")}`);
    const duration = await page.evaluate(() => Number(window.VIDEO.duration));
    const frames = Math.round(duration * fps);
    const ff = spawn(
      "ffmpeg",
      ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "mjpeg", "-i", "-",
       "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
      { stdio: ["pipe", "inherit", "inherit"] },
    );
    const done = new Promise((res, rej) => {
      ff.on("error", rej);
      ff.on("close", (code) => (code === 0 ? res() : rej(new Error(`ffmpeg exited with ${code}`))));
    });
    for (let f = 0; f < frames; f++) {
      const buf = dataUrlToBuffer(await grabFrame(page, f / fps, "image/jpeg", 0.95));
      if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
      onProgress?.(f + 1, frames);
    }
    ff.stdin.end();
    await done;
    return { out, duration, frames };
  } finally {
    await browser.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const args = process.argv.slice(2);
  const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
  const file = args[0];
  if (!file) {
    console.error("usage: node src/render.mjs <video.html> [--out file.mp4] [--fps 30]");
    process.exit(2);
  }
  const r = await render(file, {
    out: opt("--out"),
    fps: Number(opt("--fps") || 30),
    onProgress: (f, n) => { if (f % 30 === 0 || f === n) process.stdout.write(`\rframe ${f}/${n}`); },
  });
  console.log(`\nwrote ${r.out}  (${r.duration.toFixed(1)} s, ${r.frames} frames)`);
}
