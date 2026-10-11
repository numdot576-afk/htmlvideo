// Opens a video HTML file in headless Chromium with WebGL, waits until it is ready,
// and gives back the page plus every error the page reported.
import { chromium } from "playwright";
import { pathToFileURL } from "node:url";
import path from "node:path";
import fs from "node:fs";
import { createRequire } from "node:module";

// three.js r128 is served from node_modules instead of the CDN: renders work offline and never change under us
const THREE_JS = createRequire(import.meta.url).resolve("three/build/three.min.js");

export async function openVideo(file, { timeout = 60_000 } = {}) {
  const launch = {
    args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
  };
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH) launch.executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH;
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
  if (proxy) launch.proxy = { server: proxy };

  const browser = await chromium.launch(launch);
  const page = await browser.newPage({ viewport: { width: 1280, height: 1200 } });
  const errors = [];
  await page.route(/three(\.js)?\/r128\/three\.min\.js|three@0\.128\.0\/build\/three\.min\.js/, (route) =>
    route.fulfill({ contentType: "application/javascript", body: fs.readFileSync(THREE_JS) }),
  );
  // web fonts are nice to have: the pages fall back to system fonts, so a font that fails to load is only a warning
  const isFont = (url = "") => /fonts\.(googleapis|gstatic)\.com/.test(url);
  const warn = (m) => console.warn(`warning: ${m}`);
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (isFont(m.location()?.url)) warn(m.text());
    else errors.push(`console.error: ${m.text()}`);
  });
  page.on("requestfailed", (r) => {
    const msg = `request failed: ${r.url()} (${r.failure()?.errorText})`;
    isFont(r.url()) ? warn(msg) : errors.push(msg);
  });

  await page.goto(pathToFileURL(path.resolve(file)).href);
  try {
    await page.waitForFunction(() => window.__ready === true && window.VIDEO, null, { timeout });
  } catch {
    errors.push("timeout: the page never set window.__ready = true and window.VIDEO (see the render contract)");
  }
  return { browser, page, errors };
}

// Seek to a time (seconds) and return that frame as a JPEG/PNG data URL straight from the 1080x1920 canvas.
export async function grabFrame(page, t, type = "image/jpeg", quality = 0.92) {
  return page.evaluate(
    ([t, type, quality]) => {
      window.VIDEO.seek(t);
      return document.getElementById("out").toDataURL(type, quality);
    },
    [t, type, quality],
  );
}

export const dataUrlToBuffer = (u) => Buffer.from(u.slice(u.indexOf(",") + 1), "base64");
