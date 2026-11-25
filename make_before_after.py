"""Before/after demo videos for the FrameRelay promos (1080x1920, about 15-30 s). Posts nothing.

Format:  BEFORE (4 s)  a glimpse of the long, wide source video + "60-minute talk..."
         AFTER         the vertical, captioned short clip made from it + "...turned into this."
         END CARD      "FrameRelay" / "Long videos into ready-to-post clips" / "framerelay.app"
No voiceover: on-screen text, burned-in captions (free, local faster-whisper model) and the clip's own audio.

SOURCE RULES (owner decision, 2026-11-25):
  - Sources: Internet Archive (archive.org) and Wikimedia Commons only.
  - Allowed licenses: CC BY, CC0, Public Domain, read from the item's OWN license metadata at build time.
    Refused: CC BY-SA, anything NC or ND, anything else, and items with no clear license.
  - Credit on screen and in the post caption ("Source: <creator>, <license>"); source link + license saved per video.
  - Skip well-known brands/logos and famous people as the main subject (human review of the inspect frames;
    Commons items tagged with trademark/personality-rights restrictions are refused automatically).

A source is written "ia:<identifier>" or "commons:File:<name>". Driven by .github/ba-request.json:
  {"mode": "find", "terms": ["interview", "podcast"]}        -> previews/ba/candidates.json (+ thumbs)
  {"mode": "inspect", "source": "ia:..."}                    -> previews/ba/<slug>/ transcript + frames
  {"mode": "build", "name": "ba-test-01", "source": "ia:...", "before_at": 600, "clip_start": 1234.0,
   "clip_end": 1250.0, "crop_x": 0.5, "kind": "talk", "fix": {"misheard": "right"}}
      -> previews/ba/<name>.mp4 + previews/ba/<name>.json (source link, license proof, post caption)
"""
import html, json, math, os, pathlib, re, subprocess, sys, tempfile, datetime as dt, urllib.parse, urllib.request
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "previews" / "ba"
W, H, FPS = 1080, 1920, 30
BG_TOP, BG_BOT = (12, 18, 32), (19, 30, 48)
TEXT, CYAN, ACCENT, DIM = (246, 247, 251), (124, 228, 207), (255, 214, 63), (150, 160, 180)
SITE = "framerelay.app"
BEFORE_SECONDS, END_SECONDS = 4.0, 3.0
UA = "FrameRelayPromoBuilder/1.0 (https://framerelay.app)"
VIDEO_EXT = (".mp4", ".webm", ".ogv", ".mov", ".m4v", ".mkv")


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


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def hms(s):
    s = int(round(s)); h, r = divmod(s, 3600); mnt, sec = divmod(r, 60)
    return f"{h}:{mnt:02d}:{sec:02d}" if h else f"{mnt}:{sec:02d}"


def length_words(seconds, kind):
    mins = seconds / 60
    if mins >= 90:
        return f"{round(mins / 60 * 2) / 2:g}-hour {kind}"
    return f"{int(round(mins / 5) * 5) if mins >= 20 else int(round(mins))}-minute {kind}"


def plain(s):
    s = " ".join(s) if isinstance(s, list) else (s or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


# ---------------------------------------------------------------- license rules
class Refused(Exception):
    pass


def classify(license_url="", code=""):
    """Return the short license name if allowed (CC BY / CC0 / Public Domain), else raise Refused."""
    u = (license_url or "").strip().lower().replace("https://", "http://")
    c = (code or "").strip().lower()
    blob = f"{u} {c}"
    if re.search(r"(^|[/\s-])(by-)?(sa|nc|nd)([/\s-]|$)|by-sa|by-nc|by-nd|share.?alike|noncommercial|noderiv", blob):
        raise Refused(f"share-alike / non-commercial / no-derivatives license: {license_url or code}")
    m = re.search(r"creativecommons\.org/licenses/by/(\d(?:\.\d)?)", u) or re.fullmatch(r"cc-by-(\d(?:\.\d)?)", c)
    if m:
        return f"CC BY {m.group(1)}"
    if "creativecommons.org/publicdomain/zero/" in u or c == "cc0":
        return "CC0"
    if "creativecommons.org/publicdomain/mark/" in u or c in ("pd", "public domain") or c.startswith("pd-"):
        return "Public Domain"
    raise Refused(f"license not allowed or unclear: {license_url or code or 'none'}")


def caption_license(short):
    return "CC BY" if short.startswith("CC BY") else short


# ---------------------------------------------------------------- sources
def source(spec):
    """Look up a source and check its license from the item's own metadata. Raises Refused."""
    if spec.startswith("ia:"):
        ident = spec[3:].split("/")[0]
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", ident):
            raise Refused(f"bad Internet Archive identifier {ident!r}")
        m = get_json(f"https://archive.org/metadata/{ident}")
        md = m.get("metadata") or {}
        if not md:
            raise Refused("item not found")
        if md.get("mediatype") != "movies":
            raise Refused(f"not a video item ({md.get('mediatype')})")
        lic = classify(plain(md.get("licenseurl")))
        files = [f for f in m.get("files", []) if f.get("name", "").lower().endswith(VIDEO_EXT)]
        want = spec[3:].split("/", 1)[1] if "/" in spec[3:] else None
        if want:
            files = [f for f in files if f["name"] == want]
        def score(f):
            return (f.get("source") == "derivative" and "h.264" in (f.get("format") or "").lower(),
                    (f.get("format") or "").lower() in ("mpeg4", "h.264", "h.264 ia"), int(f.get("height") or 0) <= 1080,
                    int(f.get("height") or 0), int(f.get("size") or 0))
        files.sort(key=score, reverse=True)
        if not files:
            raise Refused("no video file in item")
        f = files[0]
        creator = plain(md.get("creator")) or plain(md.get("uploader", "")).split("@")[0]
        return {"kind": "ia", "spec": f"ia:{ident}/{f['name']}", "title": plain(md.get("title")), "creator": creator,
                "license": lic, "license_url": plain(md.get("licenseurl")),
                "page": f"https://archive.org/details/{ident}",
                "media": f"https://archive.org/download/{ident}/{urllib.parse.quote(f['name'])}",
                "duration": float(f.get("length") or 0) if re.fullmatch(r"[\d.]+", str(f.get("length") or "")) else 0.0,
                "subjects": plain(md.get("subject"))}
    if spec.startswith("commons:"):
        title = spec[len("commons:"):]
        if not title.startswith("File:"):
            raise Refused("Commons source must be a File: page")
        q = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "imageinfo", "format": "json",
                                    "iiprop": "url|extmetadata|mediatype|size", "iiurlwidth": 480})
        pages = get_json(f"https://commons.wikimedia.org/w/api.php?{q}")["query"]["pages"]
        p = next(iter(pages.values()))
        if "imageinfo" not in p:
            raise Refused("file not found")
        ii = p["imageinfo"][0]; em = {k: plain(v.get("value")) for k, v in (ii.get("extmetadata") or {}).items()}
        if ii.get("mediatype") != "VIDEO":
            raise Refused(f"not a video ({ii.get('mediatype')})")
        if em.get("NonFree", "").lower() in ("true", "1"):
            raise Refused("marked non-free")
        restr = em.get("Restrictions", "")
        if re.search(r"trademark|personality|insignia", restr, re.I):
            raise Refused(f"restricted ({restr}): brand or personality rights")
        lic = classify(em.get("LicenseUrl", ""), em.get("License", "") or em.get("LicenseShortName", ""))
        creator = em.get("Artist") or em.get("Credit") or ""
        return {"kind": "commons", "spec": f"commons:{p['title']}", "title": p["title"][5:], "creator": creator[:80],
                "license": lic, "license_url": em.get("LicenseUrl", ""), "page": ii.get("descriptionurl"),
                "media": ii["url"], "duration": float(ii.get("duration") or 0), "thumb": ii.get("thumburl"),
                "subjects": em.get("Categories", "")[:300]}
    raise Refused("source must start with ia: or commons:")


def probe_duration(url):
    out = run(["ffprobe", "-v", "error", "-user_agent", UA, "-show_entries", "format=duration", "-of", "csv=p=0", url])
    return float(out.strip() or 0)


def cut(url, start, length, out, height=1080):
    run(["ffmpeg", "-y", "-user_agent", UA, "-ss", f"{start:.2f}", "-i", url, "-t", f"{length:.2f}",
         "-vf", f"scale=-2:'min({height},ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-ar", "44100", "-ac", "2", str(out)])


def slug(spec):
    return re.sub(r"[^a-z0-9]+", "-", spec.lower()).strip("-")[:60]


# ---------------------------------------------------------------- mode: find
def find(req):
    OUT.mkdir(parents=True, exist_ok=True); (OUT / "thumbs").mkdir(exist_ok=True)
    min_s = 60 * req.get("min_minutes", 15)
    found, specs = [], []
    for term in req.get("terms", ["interview", "podcast", "lecture", "talk"]):
        q = f'mediatype:movies AND (subject:"{term}" OR title:"{term}") AND licenseurl:*'
        url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
            [("q", q), ("fl[]", "identifier"), ("rows", req.get("rows", 60)), ("output", "json"), ("sort[]", "downloads desc")])
        try:
            specs += ["ia:" + d["identifier"] for d in get_json(url)["response"]["docs"]]
        except Exception as e:
            print("IA search failed:", term, e)
        cq = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": f"filetype:video {term}",
                                     "srnamespace": 6, "srlimit": req.get("rows", 60), "format": "json"})
        try:
            specs += ["commons:" + s["title"] for s in get_json(f"https://commons.wikimedia.org/w/api.php?{cq}")["query"]["search"]]
        except Exception as e:
            print("Commons search failed:", term, e)
    seen = set()
    for spec in specs:
        if spec in seen:
            continue
        seen.add(spec)
        try:
            s = source(spec)
        except Refused as e:
            print("refused", spec, "-", e); continue
        except Exception as e:
            print("error", spec, e); continue
        if not s["duration"]:
            try:
                s["duration"] = probe_duration(s["media"])
            except Exception:
                pass
        if s["duration"] < min_s:
            continue
        s["minutes"] = round(s["duration"] / 60)
        found.append(s); print("OK", s["license"], s["minutes"], "min |", s["spec"], "|", s["creator"], "|", s["title"][:70])
        try:
            th = s.get("thumb") or f"https://archive.org/services/img/{s['spec'][3:].split('/')[0]}"
            req_ = urllib.request.Request(th, headers={"User-Agent": UA})
            (OUT / "thumbs" / f"{slug(s['spec'])}.jpg").write_bytes(urllib.request.urlopen(req_, timeout=30).read())
        except Exception:
            pass
        if len(found) >= req.get("max", 25):
            break
    (OUT / "candidates.json").write_text(json.dumps(found, indent=1, ensure_ascii=False))
    print(len(found), "allowed candidates")


# ---------------------------------------------------------------- mode: inspect
def inspect(req):
    s = source(req["source"])
    d = OUT / slug(s["spec"]); d.mkdir(parents=True, exist_ok=True)
    total = s["duration"] or probe_duration(s["media"])
    upto = min(total, 60 * req.get("transcribe_minutes", 20))
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "a.wav"
        run(["ffmpeg", "-y", "-user_agent", UA, "-i", s["media"], "-t", f"{upto:.0f}", "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        from faster_whisper import WhisperModel
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(str(wav), language="en", vad_filter=True)
        (d / "transcript.txt").write_text("\n".join(f"[{sg.start:7.1f}] {sg.text.strip()}" for sg in segs))
    for frac in (0.05, 0.25, 0.5, 0.75):
        t = total * frac
        try:
            run(["ffmpeg", "-y", "-user_agent", UA, "-ss", f"{t:.1f}", "-i", s["media"], "-frames:v", "1", "-vf", "scale=640:-2",
                 str(d / f"frame_{int(t):05d}.jpg")])
        except Exception as e:
            print("frame failed", t, e)
    s["duration"] = total
    (d / "info.json").write_text(json.dumps(s, indent=1, ensure_ascii=False))
    print("inspected", s["spec"], s["license"], hms(total))


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


def credit(d, label, y):
    f = font(30, "SemiBold")
    while f.getlength(f"Source: {label}") > W - 80 and f.size > 18:
        f = font(f.size - 2, "SemiBold")
    shadow_text(d, (W // 2, y), f"Source: {label}", f, (230, 232, 240), off=2)


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


def transcribe(clip, fix):  # word timings for the burned-in captions
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
    s = source(req["source"])                     # license re-checked from the item's own metadata
    total = s["duration"] or probe_duration(s["media"])
    at, c0, c1 = float(req["before_at"]), float(req["clip_start"]), float(req["clip_end"])
    if not (8 <= c1 - c0 <= 22):
        raise SystemExit("clip must be 8-22 s so the whole video stays within about 15-30 s")
    if not (0 <= at and at + BEFORE_SECONDS <= total and 0 <= c0 and c1 <= total):
        raise SystemExit("times are outside the video")
    if not s["creator"] and s["license"].startswith("CC BY"):
        raise SystemExit("REFUSED: CC BY needs a named creator to credit")
    who = s["creator"] or ("Internet Archive" if s["kind"] == "ia" else "Wikimedia Commons")
    kind = req.get("kind", "talk")
    before_text = req.get("before_text") or f"{length_words(total, kind)}..."
    after_text = req.get("after_text") or "...turned into this."
    name = re.sub(r"[^a-z0-9-]", "", req["name"].lower())
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        cut(s["media"], at, BEFORE_SECONDS + 0.5, tmp / "before.mp4")
        cut(s["media"], c0, c1 - c0, tmp / "clip.mp4")
        words = transcribe(tmp / "clip.mp4", req.get("fix"))
        secs = render(tmp / "before.mp4", tmp / "clip.mp4", words, OUT / f"{name}.mp4", channel=f"{who} ({s['license']})",
                      before_text=before_text, after_text=after_text, at=at, total=total, crop_x=float(req.get("crop_x", 0.5)))
    caption = (f"Demo: a {length_words(total, kind)} turned into a ready-to-post vertical clip with captions. "
               f"Source: {who}, {caption_license(s['license'])}. {SITE}")
    rec = {"name": name, "seconds": round(secs, 1), "caption": caption,
           "yt_title": f"Long {kind} into a short captioned clip #shorts",
           "captions_text": " ".join(w["w"] for w in words),
           "source": {**{k: s.get(k) for k in ("spec", "page", "media", "title", "creator", "license", "license_url")},
                      "credited_as": who,
                      "license_checked_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "before_at": at, "clip_start": c0, "clip_end": c1, "crop_x": req.get("crop_x", 0.5)}}
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    print("built", name, rec["seconds"], "s |", caption)


if __name__ == "__main__":
    req = json.loads(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / ".github" / "ba-request.json").read_text())
    try:
        {"find": find, "inspect": inspect, "build": build}[req["mode"]](req)
    except Refused as e:
        raise SystemExit(f"REFUSED: {e}")
