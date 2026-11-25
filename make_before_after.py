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
DISCLAIMER = "Example clip. Not a FrameRelay customer or endorsement."
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
        if re.match(r"(youtube|twitch|afreecatv|soop|tiktok|kick|dvd)[-_]", ident.lower()) or re.search(r"youtube\.com|youtu\.be", plain(md.get("source")) + plain(md.get("originalurl"))):
            raise Refused("re-upload from YouTube/Twitch/TV: the uploader's license label can't be trusted")
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
    for spec in req.get("sources") or [req["source"]]:
        try:
            inspect_one(spec, req)
        except Exception as e:
            print("inspect failed:", spec, e)


def inspect_one(spec, req):
    s = source(spec)
    d = OUT / slug(s["spec"]); d.mkdir(parents=True, exist_ok=True)
    total = s["duration"] or probe_duration(s["media"])
    start = 60 * req.get("transcribe_from_minute", 0)
    upto = min(total - start, 60 * req.get("transcribe_minutes", 20))
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "a.wav"
        run(["ffmpeg", "-y", "-user_agent", UA, "-ss", f"{start:.0f}", "-i", s["media"], "-t", f"{upto:.0f}", "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        from faster_whisper import WhisperModel
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(str(wav), language="en", vad_filter=True)
        name = "transcript.txt" if not start else f"transcript_from_{int(start)}.txt"
        (d / name).write_text("\n".join(f"[{sg.start + start:7.1f}] {sg.text.strip()}" for sg in segs))
    for t in req.get("frames_at") or [total * f for f in (0.05, 0.25, 0.5, 0.75)]:
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


def disclaimer(d, y=1782):
    shadow_text(d, (W // 2, y), DISCLAIMER, font(28, "SemiBold"), (230, 232, 240), off=2)


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
    tw = font(84).getlength(after_text)
    d.rounded_rectangle([W / 2 - tw / 2 - 40, 190, W / 2 + tw / 2 + 40, 450], 36, fill=(8, 12, 22, 150))
    pill(d, W // 2, 250, "AFTER", (255, 214, 63, 235), (30, 20, 40), 40)
    shadow_text(d, (W // 2, 380), after_text, font(84), TEXT)
    ov.save(tmp / "after_title.png")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    credit(d, channel, 1830)
    ov.save(tmp / "after_credit.png")


def end_card(tmp, with_disclaimer=""):
    im = gradient(); d = ImageDraw.Draw(im)
    d.rounded_rectangle([W // 2 - 90, 600, W // 2 + 90, 780], 40, fill=CYAN)
    d.text((W // 2, 690), "F", font=font(120), fill=(11, 25, 32), anchor="mm")
    d.text((W // 2, 900), "FrameRelay", font=font(120), fill=TEXT, anchor="mm")
    d.text((W // 2, 1030), "Long videos into", font=font(64, "SemiBold"), fill=(210, 216, 230), anchor="mm")
    d.text((W // 2, 1110), "ready-to-post clips", font=font(64, "SemiBold"), fill=(210, 216, 230), anchor="mm")
    pill(d, W // 2, 1300, SITE, CYAN, (9, 34, 27), 56)
    if with_disclaimer:
        disclaimer(d, 1780); credit(d, with_disclaimer, 1830)
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
    chunks = chunk_words(words)
    for ci, ch in enumerate(chunks):
        limit = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else 1e9   # never overlap the next group
        for i, w in enumerate(ch):
            s = w["s"]; e = ch[i + 1]["s"] if i + 1 < len(ch) else min(ch[-1]["e"] + 0.15, limit)
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
def norm(t):
    return re.sub(r"[^a-z0-9']", "", t.lower())


def find_phrase(words, phrase, last=False):
    target = [norm(x) for x in phrase.split() if norm(x)]
    hits = [i for i in range(len(words) - len(target) + 1)
            if [norm(w["w"]) for w in words[i:i + len(target)]] == target]
    if not hits:
        raise SystemExit(f"phrase not found in captions: {phrase!r}; heard: {' '.join(w['w'] for w in words)}")
    i = hits[-1] if last else hits[0]
    return i, i + len(target) - 1


def cutaways(clip):
    """Time ranges where the picture is very different from the usual shot (e.g. a Zoom switch to someone else)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip), "-vf", "scale=32:18,fps=10", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 18, 32, 3).astype(float)
    if not len(f):
        return []
    med = np.median(f, axis=0); d = np.abs(f - med).mean(axis=(1, 2, 3))
    bad = d > max(35.0, 3 * float(np.median(d)))
    out, start = [], None
    for i, b in enumerate(list(bad) + [False]):
        if b and start is None:
            start = i
        if not b and start is not None:
            if i - start >= 4:
                out.append([round(start / 10, 1), round(i / 10, 1)])
            start = None
    return out


def prepare_clip(s, c0, c1, req, tmp, tag="clip"):
    """Cut a window, transcribe it, trim it to start_text..end_after. Returns (clip, words, t0, t1)."""
    win = tmp / f"{tag}_window.mp4"
    cut(s["media"], c0, c1 - c0, win)
    words = transcribe(win, req.get("fix"))
    t0, t1 = 0.0, c1 - c0
    if req.get("start_text"):
        i, _ = find_phrase(words, req["start_text"])
        t0 = max(words[i - 1]["e"] if i else 0.0, words[i]["s"] - 0.15)
    if req.get("end_after"):
        _, j = find_phrase(words, req["end_after"], last=True)
        t1 = min(words[j]["e"] + 0.35, words[j + 1]["s"] - 0.02) if j + 1 < len(words) else words[j]["e"] + 0.35
    if not (8 <= t1 - t0 <= 22):
        raise SystemExit(f"clip is {t1 - t0:.1f} s; it must be 8-22 s so the video stays about 15-30 s")
    clip = tmp / f"{tag}.mp4"
    run(["ffmpeg", "-y", "-ss", f"{t0:.3f}", "-i", str(win), "-t", f"{t1 - t0:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", str(clip)])
    words = [{**w, "s": max(0.0, w["s"] - t0), "e": min(t1 - t0, w["e"] - t0)} for w in words
             if w["s"] >= t0 - 0.05 and w["e"] <= t1 + 0.05]
    return clip, words, t0, t1


def build(req):
    for one in req.get("builds") or [req]:
        (build_showcase if one.get("style") == "showcase" else build_one)(one)


def build_one(req):
    s = source(req["source"])                     # license re-checked from the item's own metadata
    total = s["duration"] or probe_duration(s["media"])
    at, c0, c1 = float(req["before_at"]), float(req["clip_start"]), float(req["clip_end"])
    if not (0 <= at and at + BEFORE_SECONDS <= total and 0 <= c0 < c1 <= total and c1 - c0 <= 40):
        raise SystemExit("times are outside the video (or window longer than 40 s)")
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
        clip, words, t0, t1 = prepare_clip(s, c0, c1, req, tmp)
        cuts = cutaways(clip)
        secs = render(tmp / "before.mp4", clip, words, OUT / f"{name}.mp4", channel=f"{who} ({s['license']})",
                      before_text=before_text, after_text=after_text, at=at, total=total, crop_x=float(req.get("crop_x", 0.5)))
    caption = (f"Demo: a {length_words(total, kind)} turned into a ready-to-post vertical clip with captions. "
               f"Source: {who}, {caption_license(s['license'])}. {SITE}")
    rec = {"name": name, "seconds": round(secs, 1), "caption": caption,
           "yt_title": f"Long {kind} into a short captioned clip #shorts",
           "captions_text": " ".join(w["w"] for w in words), "cutaways_in_clip": cuts,
           "source": {**{k: s.get(k) for k in ("spec", "page", "media", "title", "creator", "license", "license_url")},
                      "credited_as": who,
                      "license_checked_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "before_at": at, "clip_start": round(c0 + t0, 2), "clip_end": round(c0 + t1, 2),
                      "crop_x": req.get("crop_x", 0.5)},
           "words": words}
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    print("built", name, rec["seconds"], "s | cutaways", cuts, "|", rec["captions_text"])


# ---------------------------------------------------------------- showcase style
# 1) the whole long video scrubs past on a timeline, 2) markers drop where the best moments are,
# 3) those moments fan out as vertical clip cards, 4) one clip plays full screen with captions, 5) end card.
PANEL = (40, 600, 1000, 562)          # x, y, w, h of the wide video
LINE_Y, LX0, LX1 = 1470, 70, 1010     # timeline
SCRUB_S, MARK_S, FAN_S = 1.2, 1.8, 1.6     # quick recap after the clip
CARD_W, CARD_H, CARD_Y = 300, 534, 600


def grab(url, t, out):
    run(["ffmpeg", "-y", "-user_agent", UA, "-ss", f"{t:.2f}", "-i", url, "-frames:v", "1", "-vf", "scale=1280:-2", str(out)])
    return Image.open(out).convert("RGB")


def fit(img, w, h):
    r = max(w / img.width, h / img.height)
    im = img.resize((max(w, int(img.width * r + 0.5)), max(h, int(img.height * r + 0.5))), Image.BICUBIC)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))


def vcrop(img, cx):
    cw = int(img.height * 9 / 16); x = int((img.width - cw) * cx)
    return img.crop((x, 0, x + cw, img.height))


def ease(x):
    x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3


def wrap(text, f, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if cur and f.getlength(t) > maxw:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def rounded(im, r):
    m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, im.width - 1, im.height - 1], r, fill=255)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0)); out.paste(im, (0, 0), m); return out


def card(frame_v, hook, n, w=CARD_W, h=CARD_H, text=True):
    im = fit(frame_v, w, h).convert("RGBA")
    if text:
        ov = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
        for y in range(h // 3, h):
            d.line([(0, y), (w, y)], fill=(0, 0, 0, int(215 * (y - h / 3) / (h * 2 / 3))))
        f = font(max(22, int(w * 0.105))); lh = int(f.size * 1.18)
        lines = wrap(hook, f, w - 40)[:4]
        for i, ln in enumerate(lines):
            d.text((20, h - 28 - lh * (len(lines) - i)), ln, font=f, fill=TEXT)
        fs = font(max(16, int(w * 0.07)))
        tw = fs.getlength(f"CLIP {n}") + 28
        d.rounded_rectangle([16, 16, 16 + tw, 16 + fs.size + 18], (fs.size + 18) // 2, fill=ACCENT)
        d.text((16 + tw / 2, 16 + (fs.size + 18) / 2), f"CLIP {n}", font=fs, fill=(30, 20, 40), anchor="mm")
        im = Image.alpha_composite(im, ov)
    return rounded(im, max(12, w // 14))


def title(d, text, y=440):
    f = font(80); lines = wrap(text, f, W - 120)
    for i, ln in enumerate(lines):
        shadow_text(d, (W // 2, y + (i - (len(lines) - 1) / 2) * 96), ln, f, TEXT)


def mx(t, total):
    return LX0 + (LX1 - LX0) * t / total


def intro_frame(t, bg, scrub, moments, feat, total, before_text, label=""):
    im = bg.copy(); d = ImageDraw.Draw(im, "RGBA")
    x, y, w, h = PANEL
    n = len(moments)
    shown = 0
    if t < SCRUB_S:                                    # 1) the long video
        p = t / SCRUB_S; pos = p * total
        im.paste(rounded(fit(scrub[min(len(scrub) - 1, int(p * len(scrub)))], w, h), 24), (x, y), rounded(fit(scrub[0], w, h), 24))
        title(d, before_text)
        panel_alpha = 1.0
    elif t < SCRUB_S + MARK_S:                         # 2) finding the moments
        tt = t - SCRUB_S; pos = total
        shown = sum(1 for k in range(n) if tt >= 0.15 + k * 0.45)
        frame = moments[shown - 1]["wide"] if shown else scrub[-1]
        im.paste(rounded(fit(frame, w, h), 24), (x, y), rounded(fit(frame, w, h), 24))
        title(d, f"...{n} moments worth posting")
    else:                                              # 3) the clips
        tt = t - SCRUB_S - MARK_S; pos = total; shown = n
        a = 1 - ease(tt / 0.3)
        if a > 0:
            fr = rounded(fit(moments[-1]["wide"], w, h), 24); fr.putalpha(fr.getchannel("A").point(lambda v: int(v * a)))
            im.paste(fr, (x, y), fr)
        title(d, "...each one ready to post")
    # timeline
    d.rounded_rectangle([LX0, LINE_Y, LX1, LINE_Y + 16], 8, fill=(80, 86, 104))
    d.rounded_rectangle([LX0, LINE_Y, mx(pos, total), LINE_Y + 16], 8, fill=(230, 60, 60))
    if t < SCRUB_S:
        px = mx(pos, total); d.ellipse([px - 17, LINE_Y - 9, px + 17, LINE_Y + 25], fill=(230, 60, 60))
    if t < SCRUB_S:
        d.text((LX0, LINE_Y + 70), f"{hms(pos)} / {hms(total)}", font=font(40, "SemiBold"), fill=DIM, anchor="lm")
    for k in range(shown):                             # markers drop in
        m = moments[k]; age = (t - SCRUB_S - 0.15 - k * 0.45) if t < SCRUB_S + MARK_S else 9
        drop = 1 - ease(age / 0.25); px = mx(m["at"], total)
        top = LINE_Y - (110 + 85 * (k % 3)) - 60 * drop
        d.line([(px, top + 40), (px, LINE_Y + 8)], fill=ACCENT, width=6)
        d.ellipse([px - 14, LINE_Y - 6, px + 14, LINE_Y + 22], fill=ACCENT)
        f = font(38); lw = f.getlength(m["label"]) + 44; cx = min(max(px, LX0 + lw / 2), LX1 - lw / 2)
        d.rounded_rectangle([cx - lw / 2, top, cx + lw / 2, top + 64], 32, fill=ACCENT)
        d.text((cx, top + 32), m["label"], font=f, fill=(30, 20, 40), anchor="mm")
        d.text((px, LINE_Y + 50), hms(m["at"]), font=font(28, "SemiBold"), fill=ACCENT, anchor="mm")
    disclaimer(d); credit(d, label, 1830)
    if t >= SCRUB_S + MARK_S:                          # cards fan out, then the featured one fills the screen
        tt = t - SCRUB_S - MARK_S
        z = 0.0                                # the clip already played first
        xs = [W / 2 + (k - (n - 1) / 2) * (CARD_W + 40) for k in range(n)]
        order = [k for k in range(n) if k != feat] + [feat]
        for k in order:
            m = moments[k]; e = ease((tt - 0.05 - k * 0.12) / 0.5)
            sx, sy = mx(m["at"], total), LINE_Y
            cxk = sx + (xs[k] - sx) * e; cyk = sy + (CARD_Y + CARD_H / 2 - sy) * e
            sc = 0.15 + 0.85 * e
            if k == feat and z > 0:
                cw = CARD_W * sc + (W - CARD_W * sc) * z; ch = CARD_H * sc + (H - CARD_H * sc) * z
                cxk = cxk + (W / 2 - cxk) * z; cyk = cyk + (H / 2 - cyk) * z
                c = card(m["vert"], m["hook"], k + 1, int(cw), int(ch), text=z < 0.35)
            else:
                if e <= 0:
                    continue
                c = card(m["vert"], m["hook"], k + 1, int(CARD_W * sc), int(CARD_H * sc))
                if k != feat and z > 0:
                    c.putalpha(c.getchannel("A").point(lambda v: int(v * (1 - z))))
            im.paste(c, (int(cxk - c.width / 2), int(cyk - c.height / 2)), c)
    return im


def clip_layers(tmp, hook, n, of, label, badge):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    f = font(70); lines = wrap(hook, f, W - 200)[:3]; lh = 84
    top = 230; bottom = top + 90 + lh * len(lines)
    d.rounded_rectangle([60, top - 40, W - 60, bottom], 36, fill=(8, 12, 22, 165))
    pill(d, W // 2, top + 6, f"CLIP {n} OF {of}", (255, 214, 63, 240), (30, 20, 40), 34)
    for i, ln in enumerate(lines):
        shadow_text(d, (W // 2, top + 90 + lh * i), ln, f, TEXT, off=3)
    disclaimer(d); credit(d, label, 1830)
    ov.save(tmp / "clip_ov.png")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    pill(d, W // 2, bottom + 70, badge, (8, 12, 22, 200), TEXT, 38)
    ov.save(tmp / "clip_badge.png")


def build_showcase(req):
    s = source(req["source"])                     # license re-checked from the item's own metadata
    total = s["duration"] or probe_duration(s["media"])
    if not s["creator"] and s["license"].startswith("CC BY"):
        raise SystemExit("REFUSED: CC BY needs a named creator to credit")
    who = s["creator"] or ("Internet Archive" if s["kind"] == "ia" else "Wikimedia Commons")
    label = f"{who} ({s['license']})"
    kind = req.get("kind", "talk"); cx = float(req.get("crop_x", 0.5))
    ms = sorted(req["moments"], key=lambda m: m["clip_start"]); feat = next(i for i, m in enumerate(ms) if m.get("feature"))
    name = re.sub(r"[^a-z0-9-]", "", req["name"].lower())
    out_dir = ROOT / {"videos/showcase": "videos/showcase"}.get(req.get("out", ""), "previews/ba")
    out_dir.mkdir(parents=True, exist_ok=True)
    length = length_words(total, kind)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        fm = ms[feat]
        clip, words, t0, t1 = prepare_clip(s, fm["clip_start"], fm["clip_end"], fm, tmp, "feature")
        fm["at"] = fm["clip_start"] + t0
        run(["ffmpeg", "-y", "-i", str(clip), "-frames:v", "1", str(tmp / "f0.png")])
        moments = []
        for k, m in enumerate(ms):
            at = m.get("at", m["clip_start"] + float(m.get("lead", 1.0)))
            wide = grab(s["media"], at + (0 if k == feat else 1.5), tmp / f"m{k}.png") if k != feat else Image.open(tmp / "f0.png").convert("RGB")
            moments.append({"at": at, "label": m["label"], "hook": m["hook"], "wide": wide, "vert": vcrop(wide, cx)})
        scrub = [grab(s["media"], total * (0.01 + 0.98 * i / 31), tmp / f"s{i}.png") for i in range(32)]
        bg = gradient(); brand(ImageDraw.Draw(bg))
        before_text = req.get("before_text") or f"From a {length}..."
        intro_s = SCRUB_S + MARK_S + FAN_S
        pi = subprocess.Popen(["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                               "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{intro_s:.2f}", *ENC, str(tmp / "intro.mp4")],
                              stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for fi in range(int(intro_s * FPS)):
            pi.stdin.write(intro_frame(fi / FPS, bg, scrub, moments, feat, total, before_text, label).convert("RGB").tobytes())
        pi.stdin.close(); pi.wait()
        if pi.returncode:
            raise RuntimeError("intro render failed")
        clip_layers(tmp, fm["hook"], feat + 1, len(ms), label, f"From a {length}")
        write_ass(words, tmp / "cap.ass")
        clip_len = t1 - t0
        ass = str(tmp / "cap.ass").replace(":", r"\:")
        run(["ffmpeg", "-y", "-i", str(clip), "-loop", "1", "-i", str(tmp / "clip_ov.png"), "-loop", "1", "-i", str(tmp / "clip_badge.png"),
             "-filter_complex",
             f"[0:v]crop=ih*9/16:ih:(iw-ih*9/16)*{cx}:0,scale={W}:{H},setsar=1,ass={ass}[c];[c][1:v]overlay=0:0[o];"
             f"[o][2:v]overlay=0:0:enable='lt(t,2.5)',format=yuv420p[vo];"
             f"[0:a]aresample=44100,afade=t=in:d=0.15,afade=t=out:st={max(0.0, clip_len - 0.35):.2f}:d=0.35[ao]",
             "-map", "[vo]", "-map", "[ao]", "-t", f"{clip_len:.2f}", *ENC, str(tmp / "clip_out.mp4")])
        end_card(tmp, label)
        run(["ffmpeg", "-y", "-loop", "1", "-i", str(tmp / "end.png"), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-vf", "format=yuv420p", "-t", str(END_SECONDS), *ENC, str(tmp / "end.mp4")])
        # clip first (on screen within the first second), then the quick "where it came from" recap, then the end card
        lst = tmp / "list.txt"; lst.write_text("".join(f"file '{tmp / p}'\n" for p in ("clip_out.mp4", "intro.mp4", "end.mp4")))
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), *ENC, "-movflags", "+faststart", str(out_dir / f"{name}.mp4")])
        cuts = cutaways(clip)
    secs = intro_s + clip_len + END_SECONDS
    caption = (f"One {length}, {len(ms)} moments worth posting, each turned into a vertical clip with captions.\n"
               f"{DISCLAIMER}\nSource: {who}, {caption_license(s['license'])}. {SITE}")
    rec = {"name": name, "style": "showcase", "file": str((out_dir / f"{name}.mp4").relative_to(ROOT)), "seconds": round(secs, 1), "caption": caption,
           "yt_title": f"One long {kind}, {len(ms)} ready-to-post clips #shorts",
           "captions_text": " ".join(w["w"] for w in words), "cutaways_in_clip": cuts,
           "moments": [{"at": round(m["at"], 1), "label": m["label"], "hook": m["hook"]} for m in moments],
           "source": {**{k: s.get(k) for k in ("spec", "page", "media", "title", "creator", "license", "license_url")},
                      "credited_as": who,
                      "license_checked_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "featured_clip_start": round(fm["clip_start"] + t0, 2), "featured_clip_end": round(fm["clip_start"] + t1, 2),
                      "crop_x": cx},
           "words": words}
    (out_dir / f"{name}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    print("built", name, rec["seconds"], "s | cutaways", cuts, "|", rec["captions_text"])


if __name__ == "__main__":
    req = json.loads(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / ".github" / "ba-request.json").read_text())
    try:
        {"find": find, "inspect": inspect, "build": build}[req["mode"]](req)
    except Refused as e:
        raise SystemExit(f"REFUSED: {e}")
