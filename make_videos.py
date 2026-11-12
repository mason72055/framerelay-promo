"""Builds the FrameRelay promo videos (1080x1920, text cards) from scripts.json.
Usage: python make_videos.py            (builds all into videos/)
Needs: ffmpeg, Pillow. Text only: no claims beyond what framerelay.app says."""
import json, subprocess, sys, textwrap, tempfile, pathlib, re
from PIL import Image, ImageDraw, ImageFont
ROOT = pathlib.Path(__file__).resolve().parent
W, H = 1080, 1920
BG1, BG2, TEXT, CYAN = (12, 18, 32), (19, 30, 48), (246, 247, 251), (124, 228, 207)
def font(size, bold=True):
    for q in ["/usr/share/fonts/opentype/inter/Inter-Bold.otf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/inter/Inter-Bold.ttf"]:
        if pathlib.Path(q).exists(): return ImageFont.truetype(q, size)
    return ImageFont.load_default()
def run(cmd): subprocess.run(cmd, check=True, capture_output=True)
import os, base64, urllib.request
VOICE_KEY = os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
VOICE_NAME = os.environ.get("VOICE_NAME", "en-US-Neural2-J")
def speakable(t):
    return (t.replace("framerelay.app", "frame relay dot app").replace("$149", "one hundred forty nine dollars")
             .replace("VOD", "V O D").replace("1.", "One.").replace("2.", "Two.").replace("3.", "Three."))
def tts(text, out):
    """Make a voiceover mp3. GOOGLE_TTS_API_KEY = real voice; VOICE_STUB=1 = silent test tone (tests only)."""
    if os.environ.get("VOICE_STUB"):
        run(["ffmpeg","-y","-f","lavfi","-i","sine=frequency=220:duration=%.1f" % max(1.5, len(text)/14),"-c:a","libmp3lame",str(out)]); return True
    if not VOICE_KEY: return False
    body = json.dumps({"input": {"text": speakable(text)}, "voice": {"languageCode": "en-US", "name": VOICE_NAME},
                       "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.05}}).encode()
    req = urllib.request.Request("https://texttospeech.googleapis.com/v1/text:synthesize?key=" + VOICE_KEY, body,
                                 {"Content-Type": "application/json"})
    out.write_bytes(base64.b64decode(json.loads(urllib.request.urlopen(req, timeout=60).read())["audioContent"]))
    return True
def audio_len(path):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(path)],capture_output=True,text=True)
    return float(r.stdout.strip())

import random, math
from PIL import ImageFilter
ACCENT = (255, 214, 63)
PALETTES = [((30,20,90),(120,40,160)), ((8,60,70),(14,120,120)), ((12,24,60),(30,70,150)),
            ((60,20,70),(150,40,110)), ((8,40,50),(20,100,90))]
BRAND_BG = ((12,18,32),(19,30,48))
_grad = {}
def gradient(top, bot):
    k = (top, bot)
    if k not in _grad:
        im = Image.new("RGB", (W, H)); d = ImageDraw.Draw(im)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
        _grad[k] = im
    return _grad[k].copy()
def wrap_px(words, f, maxw=900):
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and f.getlength(trial) > maxw: lines.append(cur); cur = [w]
        else: cur.append(w)
    if cur: lines.append(cur)
    return lines
def frame(text, upto, idx, progress, last, path, seed):
    pal = BRAND_BG if last else PALETTES[idx % len(PALETTES)]
    im = gradient(*pal).convert("RGBA")
    rnd = random.Random(idx * 77)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    for _ in range(3):
        r = rnd.randint(220, 420); x = rnd.randint(-100, W + 100); y = rnd.randint(150, H - 300)
        od.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 18))
    im = Image.alpha_composite(im, ov).convert("RGB"); d = ImageDraw.Draw(im)
    # progress bar + brand
    d.rounded_rectangle([60, 50, W - 60, 62], 6, fill=(255, 255, 255, 40) if False else (70, 70, 90))
    d.rounded_rectangle([60, 50, 60 + int((W - 120) * progress), 62], 6, fill=ACCENT)
    d.rounded_rectangle([70, 100, 126, 156], 14, fill=CYAN)
    d.text((98, 128), "F", font=font(38), fill=(11, 25, 32), anchor="mm")
    d.text((146, 128), "FrameRelay", font=font(40), fill=TEXT, anchor="lm")
    m = re.match(r"^(\d)\.\s+(.*)$", text)
    body = m.group(2) if m else text
    words = body.split()
    size = 112 if len(words) <= 6 else 92
    f = font(size); lh = int(size * 1.2)
    lines = wrap_px(words, f)
    top = (H - lh * len(lines)) // 2 + (90 if m else 0)
    if m:  # number badge
        d.ellipse([W // 2 - 110, top - 330, W // 2 + 110, top - 110], fill=ACCENT)
        d.text((W // 2, top - 220), m.group(1), font=font(150), fill=(30, 20, 40), anchor="mm")
    n = 0
    for li, line in enumerate(lines):
        total = sum(f.getlength(w) for w in line) + f.getlength(" ") * (len(line) - 1)
        x = (W - total) / 2; y = top + li * lh
        for w in line:
            n += 1
            if n <= upto:
                d.text((x, y), w, font=f, fill=ACCENT if n == upto else TEXT)
            x += f.getlength(w) + f.getlength(" ")
    # moving waveform
    rr = random.Random(seed)
    for i in range(17):
        hgt = 30 + rr.randint(0, 150)
        x0 = W // 2 - 17 * 26 // 2 + i * 26
        d.rounded_rectangle([x0, 1700 - hgt // 2, x0 + 14, 1700 + hgt // 2], 7, fill=CYAN)
    if last:
        d.rounded_rectangle([W // 2 - 300, 1470, W // 2 + 300, 1570], 50, fill=CYAN)
        d.text((W // 2, 1520), "Link in bio", font=font(52), fill=(9, 34, 27), anchor="mm")
    im.save(path)
    return len(words)

def build(v, out):
    tmp = pathlib.Path(tempfile.mkdtemp())
    texts = []   # (text, kind)
    if "demo" in v:
        texts.append((" ".join(v["intro"]), False))
    else:
        texts += [(c, i == len(v["cards"]) - 1) for i, c in enumerate(v["cards"])]
    # phase 1: voice + durations
    plan = []
    for i, (t, last) in enumerate(texts):
        mp3 = tmp / f"a{i}.mp3"
        voiced = ("demo" not in v) and tts(re.sub(r"^\d\.\s+", "", t), mp3)
        nw = len(re.sub(r"^\d\.\s+", "", t).split())
        dur = (audio_len(mp3) + 0.25) if voiced else max(1.7, 0.42 * nw + 0.7)
        plan.append((t, last, mp3 if voiced else None, dur))
    total = sum(p[3] for p in plan) + (23 if "demo" in v else 0) + (3 if "demo" in v else 0)
    segs, clock = [], 0.0
    def make_card(i, t, last, mp3, dur, name):
        nonlocal clock
        words = re.sub(r"^\d\.\s+", "", t).split()
        n = len(words); wts = [len(w) + 2 for w in words]; scale = (dur - 0.25) / sum(wts)
        lst = tmp / f"{name}.txt"; rows = []
        for k in range(n):
            png = tmp / f"{name}_{k}.png"
            frame(t, k + 1, i, (clock + dur * (k + 1) / n) / total, last, png, seed=i * 100 + k)
            d_k = max(0.12, wts[k] * scale) + (0.25 if k == n - 1 else 0)
            rows.append(f"file '{png}'\nduration {d_k:.3f}\n")
        rows.append(f"file '{png}'\n")
        lst.write_text("".join(rows))
        mp4 = tmp / f"{name}.mp4"
        src = ["-i", str(mp3), "-af", "apad,aresample=44100,aformat=channel_layouts=stereo"] if mp3 else ["-f","lavfi","-i","anullsrc=r=44100:cl=stereo"]
        run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),*src,"-vf","fps=30,tpad=stop=-1:stop_mode=clone","-t",f"{dur:.2f}",
             "-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-ar","44100","-ac","2",str(mp4)])
        segs.append(mp4); clock += dur
    if "demo" in v:
        make_card(0, *plan[0][:2], None, 2.4, "hook")
        demo = tmp / "demo.mp4"
        run(["ffmpeg","-y","-i",str(ROOT / v["demo"]),"-t","20","-vf",
             f"scale=-2:1500,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0c1220,fps=30","-c:v","libx264","-pix_fmt","yuv420p",
             "-c:a","aac","-ar","44100","-ac","2",str(demo)])
        segs.append(demo); clock += 20
        make_card(1, v["outro"], True, None, 3.0, "outro")
    else:
        for i, (t, last, mp3, dur) in enumerate(plan):
            make_card(i, t, last, mp3, dur, f"c{i}")
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),"-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-movflags","+faststart",str(out)])

def build_one(video_id):
    cfg = json.loads((ROOT / "scripts.json").read_text())
    v = next(x for x in cfg["videos"] if x["id"] == video_id)
    (ROOT / "videos").mkdir(exist_ok=True)
    out = ROOT / "videos" / f"{video_id}.mp4"; build(v, out); return out

if __name__ == "__main__":
    cfg = json.loads((ROOT / "scripts.json").read_text())
    (ROOT / "videos").mkdir(exist_ok=True)
    only = sys.argv[1:]
    for v in cfg["videos"]:
        if only and v["id"] not in only: continue
        out = ROOT / "videos" / f"{v['id']}.mp4"
        build(v, out); print("built", out.name)
