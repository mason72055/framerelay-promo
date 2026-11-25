"""Before/after demo videos for the FrameRelay promos (1080x1920, about 15-30 s). Posts nothing.

Format:  BEFORE (4 s)  a glimpse of the long, wide source video + "60-minute episode..."
         AFTER         the vertical, captioned short clip made from it + "...turned into this."
         END CARD      "FrameRelay" / "Long videos into ready-to-post clips" / "framerelay.app"
No voiceover: on-screen text, burned-in captions (made with the free, local faster-whisper model)
and the source clip's own audio only.

COPYRIGHT RULE: a source must be a YouTube video whose license, as YouTube itself reports it, is
"Creative Commons Attribution license (reuse allowed)" (CC BY). The license is checked again from
YouTube every time a video is built; anything else is refused. The creator is credited on screen and in
the post caption ("Source: <channel>, CC BY"). Never use standard-license footage.

Driven by .github/ba-request.json through .github/workflows/before-after.yml:
  {"mode": "find", "queries": ["podcast full episode"], "min_minutes": 30}
      -> previews/ba/candidates.json  (CC BY videos only, license re-checked per video)
  {"mode": "inspect", "video": "<youtube id>"}
      -> previews/ba/<id>/transcript.txt + a few frames, to pick the moment and the crop
  {"mode": "build", "name": "ba-01", "video": "<id>", "before_at": 600, "clip_start": 1234.0,
   "clip_end": 1250.0, "crop_x": 0.5, "before_text": null, "after_text": "...turned into this.",
   "fix": {"misheard": "right"}}
      -> previews/ba/<name>.mp4 + previews/ba/<name>.json (source, license proof, post caption)
"""
import json, math, os, pathlib, re, subprocess, sys, tempfile, datetime as dt, urllib.parse, urllib.request
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "previews" / "ba"
W, H, FPS = 1080, 1920, 30
CC_BY = "Creative Commons Attribution license (reuse allowed)"
CC_FILTER = "EgIwAQ%3D%3D"          # YouTube search filter: Creative Commons
BG_TOP, BG_BOT = (12, 18, 32), (19, 30, 48)
TEXT, CYAN, ACCENT, DIM = (246, 247, 251), (124, 228, 207), (255, 214, 63), (150, 160, 180)
SITE = "framerelay.app"
BEFORE_SECONDS, END_SECONDS = 4.0, 3.0


def font(size, weight="Bold"):
    for p in (f"/usr/share/fonts/opentype/inter/Inter-{weight}.otf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if pathlib.Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-1500:]}")
    return r.stdout


def ytdlp(*args):
    return run([sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-playlist", *args])


# ---------------------------------------------------------------- source + license
def meta(video_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise SystemExit(f"REFUSED: not a YouTube video id: {video_id!r}")
    return json.loads(ytdlp("-J", "--skip-download", f"https://www.youtube.com/watch?v={video_id}"))


def require_cc_by(m):
    lic = (m.get("license") or "").strip()
    if lic != CC_BY:
        raise SystemExit(f"REFUSED: {m.get('id')} license is {lic or 'standard YouTube license'!r}, not CC BY")
    if m.get("is_live") or m.get("live_status") in ("is_live", "is_upcoming"):
        raise SystemExit("REFUSED: live or upcoming video")
    return lic


def channel_of(m):
    return (m.get("channel") or m.get("uploader") or "").strip() or "unknown channel"


def hms(s):
    s = int(round(s)); h, r = divmod(s, 3600); mnt, sec = divmod(r, 60)
    return f"{h}:{mnt:02d}:{sec:02d}" if h else f"{mnt}:{sec:02d}"


def length_words(seconds, kind):
    mins = seconds / 60
    if mins >= 90:
        hrs = round(mins / 60 * 2) / 2
        return f"{hrs:g}-hour {kind}"
    return f"{int(round(mins / 5) * 5) if mins >= 20 else int(round(mins))}-minute {kind}"


# ---------------------------------------------------------------- mode: find
def find(req):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "thumbs").mkdir(exist_ok=True)
    min_s = 60 * req.get("min_minutes", 30)
    seen, out = set(), []
    for q in req.get("queries", ["podcast full episode"]):
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(q)}&sp={CC_FILTER}"
        try:
            flat = json.loads(ytdlp("-J", "--flat-playlist", "--playlist-end", str(req.get("per_query", 30)), url))
        except Exception as e:
            print("search failed:", q, e); continue
        for e in flat.get("entries") or []:
            vid = e.get("id")
            if not vid or vid in seen or (e.get("duration") or 0) < min_s:
                continue
            seen.add(vid)
            try:
                m = meta(vid); lic = (m.get("license") or "").strip()
            except Exception as ex:
                print("skip", vid, ex); continue
            if lic != CC_BY:
                print("skip (not CC BY):", vid, lic or "standard"); continue
            row = {"id": vid, "title": m.get("title"), "channel": channel_of(m), "channel_url": m.get("channel_url"),
                   "minutes": round((m.get("duration") or 0) / 60), "views": m.get("view_count"),
                   "uploaded": m.get("upload_date"), "license": lic, "url": m.get("webpage_url"),
                   "has_subtitles": sorted(set(k.split("-")[0] for k in (m.get("subtitles") or {}))),
                   "query": q}
            out.append(row); print("CC BY:", row["id"], row["minutes"], "min |", row["channel"], "|", row["title"])
            try:
                th = OUT / "thumbs" / f"{vid}.jpg"
                urllib.request.urlretrieve(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", th)
            except Exception:
                pass
            if len(out) >= req.get("max", 20):
                break
    (OUT / "candidates.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(len(out), "CC BY candidates")


# ---------------------------------------------------------------- mode: inspect
def parse_vtt(text):
    cues, last = [], ""
    for block in re.split(r"\n\s*\n", text):
        m = re.search(r"(\d+):(\d\d):(\d\d)\.(\d+)\s+-->", block)
        if not m:
            continue
        t = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        lines = [re.sub(r"<[^>]+>", "", ln).strip() for ln in block.splitlines()[1:] if "-->" not in ln]
        line = " ".join(x for x in lines if x)
        if line and line != last:
            new = line[len(last):].strip() if line.startswith(last) else line
            if new:
                cues.append((t, new))
            last = line
    return cues


def inspect(req):
    m = meta(req["video"]); require_cc_by(m)
    d = OUT / m["id"]; d.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            ytdlp("--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "en.*,en", "--sub-format", "vtt",
                  "-o", f"{tmp}/s", m["webpage_url"])
        except Exception as e:
            print("subtitles failed:", e)
        vtts = sorted(pathlib.Path(tmp).glob("*.vtt"), key=lambda p: ("orig" in p.name, len(p.name)))
        lines, cur_t, cur = [], None, []
        if vtts:
            for t, s in parse_vtt(vtts[0].read_text(errors="replace")):
                if cur_t is None:
                    cur_t = t
                cur.append(s)
                if t - cur_t >= 12:
                    lines.append(f"[{hms(cur_t)}] {' '.join(cur)}"); cur_t, cur = None, []
            if cur:
                lines.append(f"[{hms(cur_t)}] {' '.join(cur)}")
        (d / "transcript.txt").write_text("\n".join(lines) or "(no English subtitles found)")
        dur = m.get("duration") or 0
        for frac in (0.1, 0.3, 0.5, 0.7):
            t = int(dur * frac)
            try:
                ytdlp("-f", "bv*[height<=480]/b[height<=480]", "--download-sections", f"*{t}-{t + 2}",
                      "-o", f"{tmp}/f{t}.%(ext)s", m["webpage_url"])
                src = next(pathlib.Path(tmp).glob(f"f{t}.*"))
                run(["ffmpeg", "-y", "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2", str(d / f"frame_{hms(t).replace(':', '-')}.jpg")])
            except Exception as e:
                print("frame failed at", t, e)
    info = {k: m.get(k) for k in ("id", "title", "channel", "channel_url", "duration", "license", "webpage_url", "width", "height")}
    (d / "info.json").write_text(json.dumps(info, indent=1, ensure_ascii=False))
    print("inspected", m["id"], channel_of(m), hms(m.get("duration") or 0))


# ---------------------------------------------------------------- rendering pieces (no network)
def gradient():
    im = Image.new("RGB", (W, H)); d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)))
    return im


def brand(d, y=128):
    d.rounded_rectangle([70, y - 28, 126, y + 28], 14, fill=CYAN)
    d.text((98, y), "F", font=font(38), fill=(11, 25, 32), anchor="mm")
    d.text((146, y), "FrameRelay", font=font(40), fill=TEXT, anchor="lm")


def pill(d, cx, cy, text, fill, ink, size=44):
    f = font(size); w = f.getlength(text) + 64
    d.rounded_rectangle([cx - w / 2, cy - size * 0.9, cx + w / 2, cy + size * 0.9], int(size * 0.9), fill=fill)
    d.text((cx, cy), text, font=f, fill=ink, anchor="mm")


def shadow_text(d, xy, text, f, fill, anchor="mm", off=5):
    d.text((xy[0] + off, xy[1] + off), text, font=f, fill=(0, 0, 0, 200), anchor=anchor)
    d.text(xy, text, font=f, fill=fill, anchor=anchor)


def credit(d, channel, y):
    shadow_text(d, (W // 2, y), f"Source: {channel} (CC BY)", font(30, "SemiBold"), (230, 232, 240), off=2)


def before_layers(tmp, before_text, channel, at, total, vid_y, vid_h):
    bg = gradient(); d = ImageDraw.Draw(bg); brand(d); bg.save(tmp / "before_bg.png")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    pill(d, W // 2, 420, "BEFORE", (255, 255, 255, 40), TEXT, 40)
    shadow_text(d, (W // 2, 560), before_text, font(92), TEXT)
    # player bar under the wide video: shows how long the original is
    by = vid_y + vid_h + 70
    d.rounded_rectangle([60, by, W - 60, by + 14], 7, fill=(80, 86, 104))
    px = 60 + (W - 120) * max(0.0, min(1.0, at / total))
    d.rounded_rectangle([60, by, px, by + 14], 7, fill=(230, 60, 60))
    d.ellipse([px - 16, by - 9, px + 16, by + 23], fill=(230, 60, 60))
    d.text((60, by + 60), f"{hms(at)} / {hms(total)}", font=font(40, "SemiBold"), fill=DIM, anchor="lm")
    credit(d, channel, 1720)
    ov.save(tmp / "before_ov.png")


def after_layers(tmp, after_text, channel):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    pill(d, W // 2, 250, "AFTER", (255, 214, 63, 235), (30, 20, 40), 40)
    shadow_text(d, (W // 2, 380), after_text, font(84), TEXT)
    ov.save(tmp / "after_title.png")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    credit(d, channel, 1830)
    ov.save(tmp / "after_credit.png")


def end_card(tmp):
    im = gradient(); d = ImageDraw.Draw(im)
    d.rounded_rectangle([W // 2 - 90, 600, W // 2 + 90, 780], 40, fill=CYAN)
    d.text((W // 2, 690), "F", font=font(120), fill=(11, 25, 32), anchor="mm")
    d.text((W // 2, 900), "FrameRelay", font=font(120), fill=TEXT, anchor="mm")
    d.text((W // 2, 1030), "Long videos into", font=font(64, "SemiBold"), fill=(210, 216, 230), anchor="mm")
    d.text((W // 2, 1110), "ready-to-post clips", font=font(64, "SemiBold"), fill=(210, 216, 230), anchor="mm")
    pill(d, W // 2, 1300, SITE, CYAN, (9, 34, 27), 56)
    im.save(tmp / "end.png")


def ass_time(t):
    cs = int(round(t * 100)); h, r = divmod(cs, 360000); m, r = divmod(r, 6000); s, c = divmod(r, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def chunk_words(words, max_words=3, max_chars=16):
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(x["w"] for x in cur + [w])) > max_chars
                    or w["s"] - cur[-1]["e"] > 0.6):
            chunks.append(cur); cur = []
        cur.append(w)
        if re.search(r"[.?!,]$", w["w"]):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    return chunks


def write_ass(words, path, y=1380):
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Cap,Inter,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    for ch in chunk_words(words):
        for i, w in enumerate(ch):
            s = w["s"]; e = ch[i + 1]["s"] if i + 1 < len(ch) else ch[-1]["e"] + 0.15
            parts = [("{\\c&H3FD6FF&}" + x["w"].upper() + "{\\c&HFFFFFF&}") if j == i else x["w"].upper() for j, x in enumerate(ch)]
            ev.append(f"Dialogue: 0,{ass_time(s)},{ass_time(max(e, s + 0.05))},Cap,,0,0,0,,{{\\pos(540,{y})}}{' '.join(parts)}")
    path.write_text(head + "\n".join(ev) + "\n")


def transcribe(clip, fix):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small.en"), device="cpu", compute_type="int8")
    segs, _ = model.transcribe(str(clip), language="en", word_timestamps=True, beam_size=5)
    words = []
    for sg in segs:
        for w in sg.words or []:
            t = w.word.strip()
            for a, b in (fix or {}).items():
                t = re.sub(rf"\b{re.escape(a)}\b", b, t, flags=re.I)
            if t:
                words.append({"w": t.replace("{", "").replace("}", "").replace("\\", ""), "s": float(w.start), "e": float(w.end)})
    return words


ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
       "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]


def render(before_src, clip_src, words, out, *, channel, before_text, after_text, at, total, crop_x):
    """Pure local rendering: two downloaded source pieces -> finished vertical video."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    vid_h = int(W * 9 / 16) // 2 * 2; vid_y = 760
    before_layers(tmp, before_text, channel, at, total, vid_y, vid_h)
    after_layers(tmp, after_text, channel)
    end_card(tmp)
    write_ass(words, tmp / "cap.ass")
    b, a, e = tmp / "b.mp4", tmp / "a.mp4", tmp / "e.mp4"
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(tmp / "before_bg.png"), "-i", str(before_src), "-loop", "1", "-i", str(tmp / "before_ov.png"),
         "-filter_complex",
         f"[1:v]scale={W}:{vid_h}:force_original_aspect_ratio=increase,crop={W}:{vid_h},setsar=1[v];"
         f"[0:v][v]overlay=0:{vid_y}[x];[x][2:v]overlay=0:0,format=yuv420p[vo];"
         f"[1:a]aresample=44100,afade=t=out:st={BEFORE_SECONDS - 0.3}:d=0.3[ao]",
         "-map", "[vo]", "-map", "[ao]", "-t", str(BEFORE_SECONDS), *ENC, str(b)])
    clip_len = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip_src)]).strip())
    ass = str(tmp / "cap.ass").replace(":", r"\:")
    run(["ffmpeg", "-y", "-i", str(clip_src), "-loop", "1", "-i", str(tmp / "after_title.png"), "-loop", "1", "-i", str(tmp / "after_credit.png"),
         "-filter_complex",
         f"[0:v]crop=ih*9/16:ih:(iw-ih*9/16)*{crop_x}:0,scale={W}:{H},setsar=1,ass={ass}[c];"
         f"[c][1:v]overlay=0:0:enable='lt(t,2.2)'[t];[t][2:v]overlay=0:0,format=yuv420p[vo];"
         f"[0:a]aresample=44100,afade=t=in:d=0.15,afade=t=out:st={max(0.0, clip_len - 0.35):.2f}:d=0.35[ao]",
         "-map", "[vo]", "-map", "[ao]", "-t", f"{clip_len:.2f}", *ENC, str(a)])
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(tmp / "end.png"), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-vf", "format=yuv420p", "-t", str(END_SECONDS), *ENC, str(e)])
    lst = tmp / "list.txt"; lst.write_text("".join(f"file '{p}'\n" for p in (b, a, e)))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), *ENC, "-movflags", "+faststart", str(out)])
    return BEFORE_SECONDS + clip_len + END_SECONDS


# ---------------------------------------------------------------- mode: build
def build(req):
    m = meta(req["video"]); lic = require_cc_by(m); channel = channel_of(m)
    total = float(m.get("duration") or 0)
    at, c0, c1 = float(req["before_at"]), float(req["clip_start"]), float(req["clip_end"])
    if not (8 <= c1 - c0 <= 22):
        raise SystemExit("clip must be 8-22 s so the whole video stays within about 15-30 s")
    if not (0 <= at and at + BEFORE_SECONDS <= total and c1 <= total):
        raise SystemExit("times are outside the video")
    kind = req.get("kind", "episode")
    before_text = req.get("before_text") or f"{length_words(total, kind)}..."
    after_text = req.get("after_text") or "...turned into this."
    name = re.sub(r"[^a-z0-9-]", "", req["name"].lower())
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        fmt = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b"
        ytdlp("-f", fmt, "--merge-output-format", "mp4", "--force-keyframes-at-cuts",
              "--download-sections", f"*{at}-{at + BEFORE_SECONDS + 0.5}", "-o", f"{tmp}/before.%(ext)s", m["webpage_url"])
        ytdlp("-f", fmt, "--merge-output-format", "mp4", "--force-keyframes-at-cuts",
              "--download-sections", f"*{c0}-{c1}", "-o", f"{tmp}/clip.%(ext)s", m["webpage_url"])
        bsrc = next(pathlib.Path(tmp).glob("before.*")); csrc = next(pathlib.Path(tmp).glob("clip.*"))
        words = transcribe(csrc, req.get("fix"))
        secs = render(bsrc, csrc, words, OUT / f"{name}.mp4", channel=channel, before_text=before_text,
                      after_text=after_text, at=at, total=total, crop_x=float(req.get("crop_x", 0.5)))
    caption = (f"Demo: a {length_words(total, kind)} turned into a ready-to-post vertical clip with captions. "
               f"Source: {channel}, CC BY. {SITE}")
    rec = {"name": name, "seconds": round(secs, 1), "caption": caption,
           "yt_title": f"Long {kind} into a short captioned clip #shorts",
           "captions_text": " ".join(w["w"] for w in words),
           "source": {"id": m["id"], "url": m["webpage_url"], "title": m.get("title"), "channel": channel,
                      "channel_url": m.get("channel_url"), "license": lic,
                      "license_checked_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "before_at": at, "clip_start": c0, "clip_end": c1, "crop_x": req.get("crop_x", 0.5)}}
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    print("built", name, rec["seconds"], "s |", caption)


if __name__ == "__main__":
    req = json.loads(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / ".github" / "ba-request.json").read_text())
    {"find": find, "inspect": inspect, "build": build}[req["mode"]](req)
