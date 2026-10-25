"""Render demo_output.txt as a terminal-style mp4.

Timeline reconstructs the real run: banner + watcher line, then for each
invoice an email-arrival line, pickup ~0.6s later, and a 5s gap before the
next arrival; final summary at the end. Frames at 10 fps, 1280x720.
"""

import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "frames")
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 22)
BOLD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 22)
W, H, PAD, LH = 1280, 720, 40, 32
BG = (12, 12, 12)
WHITE = (224, 224, 224)
GREEN = (134, 239, 172)
BLUE = (125, 211, 252)
YELLOW = (253, 230, 138)
FPS = 10


def color_for(line):
    if line.strip().startswith("[watcher]") or "queued for 3-way match" in line:
        return GREEN
    if "[email]" in line:
        return BLUE
    if "[parser]" in line:
        return YELLOW if "!" in line else (192, 132, 252)
    if "DONE" in line or set(line.strip()) == {"-"}:
        return YELLOW
    return WHITE


def main():
    with open(os.path.join(HERE, "demo_output.txt")) as f:
        raw = f.read().splitlines()
    # Drop the machine-specific watcher path line, keep a generic one.
    lines = []
    for ln in raw:
        if ln.startswith("[watcher] Watching"):
            lines.append("[watcher] Watching ./demo_inbox (poll 0.3s) — Ctrl+C to stop")
        else:
            lines.append(ln)

    # Build timed events: (time, full_lines_snapshot, partial_line)
    events = []  # (t, visible_lines, typing_line)
    t = 0.0
    visible = []
    i = 0
    # Banner + watcher line first.
    while i < len(lines) and not lines[i].strip().startswith("[email]"):
        visible.append(lines[i])
        events.append((t, list(visible), ""))
        t += 0.35
        i += 1
    # Per-invoice blocks.
    while i < len(lines):
        if lines[i].strip().startswith("[email]"):
            # email line types in, then pickup lines follow 0.6s later
            events.append((t, list(visible), lines[i]))
            t += 0.4
            visible.append(lines[i])
            events.append((t, list(visible), ""))
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("[email]") \
                    and "DONE" not in lines[i]:
                events.append((t + 0.6, list(visible), lines[i]))
                t += 0.6
                visible.append(lines[i])
                events.append((t, list(visible), ""))
                i += 1
            t += 4.0  # gap before next arrival
        else:
            break
    # Final summary block.
    while i < len(lines):
        events.append((t, list(visible), lines[i]))
        t += 0.4
        visible.append(lines[i])
        events.append((t, list(visible), ""))
        i += 1
    t += 2.0  # hold on final frame

    os.makedirs(OUT, exist_ok=True)
    max_lines = (H - 2 * PAD) // LH
    n_frames = int(t * FPS) + 1
    for fi in range(n_frames):
        now = fi / FPS
        # find latest event at or before now
        vis, typing = [], ""
        for et, ev, tp in events:
            if et <= now:
                vis, typing = ev, tp
            else:
                break
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        shown = vis[-(max_lines - 1):] if typing else vis[-max_lines:]
        if typing:
            shown = shown + [typing]
        y = PAD
        for ln in shown:
            font = BOLD if set(ln.strip()) == {"="} else FONT
            d.text((PAD, y), ln, font=font, fill=color_for(ln))
            y += LH
        # block cursor
        d.rectangle([PAD, y, PAD + 12, y + 24], fill=(224, 224, 224))
        img.save(os.path.join(OUT, f"frame_{fi:04d}.png"))
    print(f"rendered {n_frames} frames, {t:.1f}s")

    subprocess.run([
        "ffmpeg", "-y", "-framerate", str(FPS),
        "-i", os.path.join(OUT, "frame_%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        os.path.join(HERE, "inbox_watcher_demo.mp4"),
    ], check=True, capture_output=True)
    print("wrote inbox_watcher_demo.mp4")


if __name__ == "__main__":
    main()
