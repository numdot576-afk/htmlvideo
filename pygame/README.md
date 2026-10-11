# Pygame soccer demo

A 16.5 s vertical (1080x1920) soccer animation drawn with plain pygame plus a little 3D maths
(a look-at camera, near-plane clipping, perspective-correct line widths):

1. **Perspective**: the camera swoops down while 14 pitch stripes flip in on a stagger and the lines draw on.
2. **Formation**: 11 players drop in on a bounce ease, then switch 4-3-3 to 3-5-2 on an elastic ease.
3. **Free kick**: the ball curls along a 3D Bezier curve over a jumping wall, past a diving keeper, into a bulging net.

```bash
pip install -r requirements.txt
python soccer_demo.py                      # play in a window
python soccer_demo.py --render demo.mp4    # frame-exact MP4 (about a minute)
python soccer_demo.py --frames out --fps 30
```

Window keys: Space pause, Left/Right seek 1 s, 1/2/3 jump to a scene, R restart, S screenshot, Esc quit.

Every frame is a pure function of time, so the window and the export always match. Exports are drawn at
2x size and scaled down for smooth edges (`--ss 1` is faster, `--ss 3` smoother).
