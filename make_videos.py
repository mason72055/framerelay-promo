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
def build(v, out):
    tmp = pathlib.Path(tempfile.mkdtemp())
    segs = []
    def still(text, dur, name, speak=True, **kw):
        png = tmp / f"{name}.png"; mp4 = tmp / f"{name}.mp4"; mp3 = tmp / f"{name}.mp3"
        card(text, png, **kw)
        voiced = speak and tts(text, mp3)
        if voiced:
            dur = max(dur, audio_len(mp3) + 0.5)
            src = ["-i", str(mp3), "-af", "apad,aresample=44100,aformat=channel_layouts=stereo"]
        else:
            src = ["-f","lavfi","-i","anullsrc=r=44100:cl=stereo"]
        run(["ffmpeg","-y","-loop","1","-i",str(png),*src,"-t",f"{dur:.2f}",
             "-r","30","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-ar","44100","-ac","2",str(mp4)])
        segs.append(mp4)
    if "demo" in v:
        still("\n".join(v["intro"]), 3, "intro", speak=False)
        demo = tmp / "demo.mp4"
        run(["ffmpeg","-y","-i",str(ROOT / v["demo"]),"-t","20","-vf",
             f"scale=-2:1500,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0c1220,fps=30","-c:v","libx264","-pix_fmt","yuv420p",
             "-c:a","aac","-ar","44100","-ac","2",str(demo)])
        segs.append(demo)
        still(v["outro"], 3, "outro", speak=False, footer="framerelay.app")
    else:
        for i, c in enumerate(v["cards"]):
            last = i == len(v["cards"]) - 1
            still(c, 3.5 if i else 3, f"c{i}", big=(i == 0 or last), footer=None if last else None)
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
