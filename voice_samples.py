"""Builds ONE mp3 reading the same line in several Google voices, so they can be compared. Posts nothing."""
import os, json, base64, urllib.request, subprocess, pathlib, tempfile
ROOT = pathlib.Path(__file__).resolve().parent
KEY = os.environ["GOOGLE_TTS_API_KEY"].strip()
LINE = "You're hiding your best thirty seconds. Frame relay turns one long video into short clips, ready to post."
VOICES = ["en-US-Chirp3-HD-Charon", "en-US-Chirp3-HD-Puck", "en-US-Chirp3-HD-Aoede", "en-US-Chirp3-HD-Kore",
          "en-US-Studio-Q", "en-US-Journey-D"]
def synth(name, text):
    body = json.dumps({"input": {"text": text}, "voice": {"languageCode": "en-US", "name": name},
                       "audioConfig": {"audioEncoding": "MP3"}}).encode()
    req = urllib.request.Request("https://texttospeech.googleapis.com/v1/text:synthesize?key=" + KEY, body, {"Content-Type": "application/json"})
    return base64.b64decode(json.loads(urllib.request.urlopen(req, timeout=60).read())["audioContent"])
tmp = pathlib.Path(tempfile.mkdtemp()); parts = []; ok = []
words = ["One", "Two", "Three", "Four", "Five", "Six"]
for i, v in enumerate(VOICES):
    try:
        f = tmp / f"{i}.mp3"; f.write_bytes(synth(v, f"Voice {words[i]}. {LINE}")); parts.append(f); ok.append((i + 1, v))
    except Exception as e:
        print("SKIPPED", v, str(e)[:200])
lst = tmp / "l.txt"
sil = tmp / "s.mp3"; subprocess.run(["ffmpeg","-y","-loglevel","error","-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t","1.2","-c:a","libmp3lame",str(sil)], check=True)
lst.write_text("".join(f"file '{p}'\nfile '{sil}'\n" for p in parts))
(ROOT / "previews").mkdir(exist_ok=True)
subprocess.run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",str(lst),"-ar","24000","-c:a","libmp3lame",str(ROOT/"previews"/"voices.mp3")], check=True)
print("Included:", ok)
