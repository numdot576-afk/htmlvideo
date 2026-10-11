# htmlvideo: AI video maker

Type a topic, and Claude writes a 3D vertical (1080×1920) "How X works" explainer video as **one HTML file**, in the same style as the examples in `examples/`. The file is checked in headless Chromium, fixed automatically if it breaks, then rendered to MP4.

| Example | |
|---|---|
| `examples/how-morse-code-works.html` | 5 scenes, 22 s |
| `examples/how-a-clutch-works.html` | 5 scenes, 50 s |

Open any `.html` file in a browser to watch it (play/pause, scene buttons, seek, ● REC to record).

## Make a video on GitHub

1. Add your API key: **Settings → Secrets and variables → Actions → New repository secret**, name `ANTHROPIC_API_KEY`.
2. **Actions → Make video → Run workflow**, then type a topic, e.g. `How the offside rule works`.
3. When it finishes, the MP4 (and preview frames) are in the run's **Artifacts**, and the HTML is committed to `videos/`.

To change an existing video, run the workflow again with **revise file** set (e.g. `videos/how-the-offside-rule-works.html`) and describe the change in **topic**.

## Make a video locally

```bash
npm install
npx playwright install chromium        # once
export ANTHROPIC_API_KEY=sk-ant-...
node src/make.mjs "How the offside rule works" --notes "3D pitch, freeze at the pass, glowing offside line"
node src/make.mjs --revise videos/how-the-offside-rule-works.html "slow down scene 3"
```

Options: `--notes`, `--effort low|medium|high|xhigh|max` (default high), `--model` (default `claude-opus-5-5`), `--fixes N` (auto-fix rounds, default 2), `--no-render`, `--out dir`. Needs Node 20+ and `ffmpeg`.

Single steps:

```bash
node src/validate.mjs videos/x.html --shots out/x   # check it + save 8 preview frames
node src/render.mjs  videos/x.html --fps 30         # HTML -> MP4
```

## How it works

- `prompts/system.md`: the house style and hard rules Claude follows. The two example videos are sent with it as references (prompt-cached).
- `src/claude.mjs`: calls Claude (streaming, adaptive thinking, server-side refusal fallback), keeping the conversation so fix rounds have context.
- `src/validate.mjs`: loads the file in headless Chromium (WebGL via SwiftShader) and fails on page errors, a missing render hook, blank frames or a frozen animation.
- `src/render.mjs`: seeks frame by frame and pipes the 1080×1920 canvas into ffmpeg, so the MP4 is smooth however slow the machine is.

**Render contract.** Every video must expose `window.VIDEO = { duration, seek(seconds) }` and set `window.__ready = true`. Every frame must be a pure function of time. three.js r128 is served from `node_modules` during checks and renders, so they also work offline.
