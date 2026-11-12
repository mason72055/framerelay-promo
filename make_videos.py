"""Builds the FrameRelay promo videos (1080x1920, text cards) from scripts.json.
Usage: python make_videos.py            (builds all into videos/)
Needs: ffmpeg, Pillow. Text only: no claims beyond what framerelay.app says."""
import json, subprocess, sys, textwrap, tempfile, pathlib
from PIL import Image, ImageDraw, ImageFont
ROOT = pathlib.Path(__file__).resolve().parent
W, H = 1080, 1920
BG1, BG2, TEXT, CYAN = (12, 18, 32), (19, 30, 48), (246, 247, 251), (124, 228, 207)
def font(size, bold=True):
    for p in ["/usr/share/fonts/opentype/inter/Inter-Bold.otf" if bold else "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        if pathlib.Path(p).exists(): return ImageFont.truetype(p, size)
    return ImageFont.load_default()
def card(lines_text, path, big=True, footer=None):
    im = Image.new("RGB", (W, H), BG1)
    d = ImageDraw.Draw(im)
    for y in range(H):  # simple vertical gradient
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(BG1[i] + (BG2[i] - BG1[i]) * t) for i in range(3)))
    d.rounded_rectangle([70, 90, 126, 146], 14, fill=CYAN)
    d.text((98, 118), "F", font=font(38), fill=(11, 25, 32), anchor="mm")
    d.text((146, 118), "FrameRelay", font=font(40), fill=TEXT, anchor="lm")
    size = 96 if big else 76
    f = font(size)
    wrapped = []
    for para in lines_text.split("\n"):
        wrapped += textwrap.wrap(para, width=16 if big else 20) or [""]
    lh = int(size * 1.22)
    y0 = (H - lh * len(wrapped)) // 2
    for i, line in enumerate(wrapped):
        d.text((W // 2, y0 + i * lh), line, font=f, fill=TEXT, anchor="mt")
    if footer:
        d.text((W // 2, H - 170), footer, font=font(44), fill=CYAN, anchor="mm")
    im.save(path)
def run(cmd): subprocess.run(cmd, check=True, capture_output=True)
def build(v, out):
    tmp = pathlib.Path(tempfile.mkdtemp())
    segs = []
    def still(text, dur, name, **kw):
        png = tmp / f"{name}.png"; mp4 = tmp / f"{name}.mp4"
        card(text, png, **kw)
        run(["ffmpeg","-y","-loop","1","-i",str(png),"-f","lavfi","-i","anullsrc=r=44100:cl=stereo","-t",str(dur),
             "-r","30","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-shortest",str(mp4)])
        segs.append(mp4)
    if "demo" in v:
        still("\n".join(v["intro"]), 3, "intro")
        demo = tmp / "demo.mp4"
        run(["ffmpeg","-y","-i",str(ROOT / v["demo"]),"-t","20","-vf",
             f"scale=-2:1500,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0c1220,fps=30","-c:v","libx264","-pix_fmt","yuv420p",
             "-c:a","aac","-ar","44100","-ac","2",str(demo)])
        segs.append(demo)
        still(v["outro"], 3, "outro", footer="framerelay.app")
    else:
        for i, c in enumerate(v["cards"]):
            last = i == len(v["cards"]) - 1
            still(c, 3.5 if i else 3, f"c{i}", big=(i == 0 or last), footer=None if last else None)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),"-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-movflags","+faststart",str(out)])
if __name__ == "__main__":
    cfg = json.loads((ROOT / "scripts.json").read_text())
    (ROOT / "videos").mkdir(exist_ok=True)
    only = sys.argv[1:]
    for v in cfg["videos"]:
        if only and v["id"] not in only: continue
        out = ROOT / "videos" / f"{v['id']}.mp4"
        build(v, out); print("built", out.name)
