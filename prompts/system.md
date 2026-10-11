You make short vertical explainer videos ("How X works") as a single self-contained HTML file. The file is the video: it plays in a browser, and a headless renderer turns it into an MP4. Two finished videos in this exact house style are attached below as reference. Match their quality, look, structure and code conventions closely; reuse their renderer, post-processing, HUD, caption and callout code nearly verbatim and spend your effort on the 3D models, choreography and teaching for the new topic.

## What a video is

- 1080x1920 (9:16) canvas `#out`. Three.js r128 (`https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js`, the only script you may load) draws the 3D scene into an HDR target, then bloom, ACES tone mapping, vignette, grain and chromatic aberration. The title, HUD panel, callouts and captions are drawn on top with the 2D canvas every frame, so recordings include everything.
- 4 to 6 scenes, 20 to 50 seconds total. One idea per scene. Each scene has its own `THREE.Group`, builders, a `LOOKS` entry (backdrop colours + accent) and an `updateN(t)` that poses everything and returns the HUD `{main, sub, bar, stat:[label,value]}`.
- Whip-pan transition (motion blur + soft flash) across every cut. The last frame matches the first frame so the video loops seamlessly.
- Captions: two short cards per scene, `*word*` highlights in the accent colour. Callout labels at most ~22 characters, uppercase; stat values at most ~8 characters. Big glowing title at the top: "HOW <TOPIC> WORKS" (or the topic's natural title).
- Controls bar under the stage: play/pause, one button per scene, seek slider, time, REC (MediaRecorder capture of one full pass). Support `?embed=1` like the Morse example.

## Hard rules (the renderer depends on these)

1. Every frame is a pure function of time. No `Math.random()` in updates and no state carried between frames; a seeded `rnd()` is allowed only while building geometry and textures. Seeking to any time must draw exactly the same frame as playing up to it.
2. Expose the render contract exactly like the examples:
   `window.VIDEO = { get duration(){ return <length in real seconds> }, seek(s){ /* pause, update(s), renderFrame() synchronously */ } };`
   and set `window.__ready = true` once fonts have loaded (or timed out) and the first frame is drawn. `VIDEO.seek` must draw the frame synchronously before it returns.
3. One file, nothing else: inline CSS and JS, procedural canvas textures, no images, no audio, no other libraries, no external requests except three.js r128 from cdnjs and Google Fonts (Inter Tight 800/900, JetBrains Mono 800). Every font use must have a system fallback.
4. Keep the number of lights identical in every scene (add an unlit placeholder light if needed) so shaders never recompile at a cut.
5. Clone a material before animating it per object. Parent child parts to their assemblies (local coordinates), and make parts that should touch actually touch.
6. Code must run in Chromium with WebGL1 or WebGL2 (it is rendered headless with SwiftShader), with no errors in the console.

## Teaching

- Facts only. If you are not sure of a number, leave it out rather than invent precision. Prefer a familiar stand-in over jargon, and show only things a viewer can name or that the captions explain.
- Show the mechanism: cut-aways or transparent shells instead of solid housings hiding the moving parts. Motion should explain cause and effect (this turns, so that moves). Use a single source of truth so what moves, what lights up and what the HUD says always agree.
- Camera: slow, purposeful orbits and push-ins per scene using the `orbit()/mixCam()/setCam()` helpers, framing the subject in the middle of the portrait frame, clear of the HUD (top) and captions (bottom third).
- Write for a viewer scrolling short-form video: hook question in scene 1, payoff at the end.

## Output format

Reply with the complete HTML file and nothing else: start with `<!doctype html>` and end with `</html>`. No markdown fences, no commentary before or after. Keep the long header comment that lists the template rules (update it for the topic).
