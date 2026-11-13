"""Synthesizes each demo-script line (host=Aoede, guest=Charon) to previews/demo/NN.mp3. Posts nothing."""
import os, json, base64, urllib.request, pathlib
ROOT = pathlib.Path(__file__).resolve().parent
KEY = os.environ["GOOGLE_TTS_API_KEY"].strip()
V = {"H": "en-US-Chirp3-HD-Aoede", "G": "en-US-Chirp3-HD-Charon"}
out = ROOT / "previews" / "demo"; out.mkdir(parents=True, exist_ok=True)
for i, (who, text) in enumerate(json.loads((ROOT / "demo_script.json").read_text())):
    body = json.dumps({"input": {"text": text}, "voice": {"languageCode": "en-US", "name": V[who]},
                       "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.0}}).encode()
    req = urllib.request.Request("https://texttospeech.googleapis.com/v1/text:synthesize?key=" + KEY, body, {"Content-Type": "application/json"})
    (out / f"{i:02d}.mp3").write_bytes(base64.b64decode(json.loads(urllib.request.urlopen(req, timeout=60).read())["audioContent"]))
    print("ok", i)
