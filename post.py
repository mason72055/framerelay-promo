"""Schedules the next unposted promo video through Buffer (TikTok, Instagram Reels, YouTube Shorts).
Videos are posted exactly as committed (showcase videos come from make_before_after.py); no AI voiceover.
Entries marked "hold": true in scripts.json are never posted, not even by a manual run.
Same Buffer API pattern as the streamrecapdaily repo. Safe by default:
  - no BUFFER_API_KEY  -> prints what it WOULD do and exits 0
  - posts on Mon/Tue/Thu/Fri only, one video per run, never repeats (posted.json)
Run:  python post.py [--dry-run] [--force]"""
import json, os, re, sys, pathlib, datetime as dt
from zoneinfo import ZoneInfo
ROOT = pathlib.Path(__file__).resolve().parent
CFG = json.loads((ROOT / "scripts.json").read_text())
STATE = ROOT / "posted.json"
REPO = os.environ.get("GITHUB_REPOSITORY", "mason72055/framerelay-promo")
DAYS = {0, 1, 3, 4}  # Mon Tue Thu Fri
def _secret(name):
    v = os.environ.get(name, "").strip()
    v = re.sub(r"^(secret|name)\s*:\s*", "", v, flags=re.I).strip()
    return v.split()[-1] if v else v
KEY = _secret("BUFFER_API_KEY")
def q(query, variables=None):
    import requests
    r = requests.post("https://api.buffer.com", json={"query": query, "variables": variables or {}},
                      headers={"Authorization": f"Bearer {KEY}"}, timeout=60)
    data = r.json()
    if "errors" in data: raise RuntimeError(json.dumps(data["errors"])[:500])
    return data["data"]
def channels():
    orgs = q("query { account { organizations { id name } } }")["account"]["organizations"]
    out = []
    for o in orgs:
        out += q("query($o: OrganizationId!) { channels(input: {organizationId: $o}) { id name service isQueuePaused } }", {"o": o["id"]})["channels"]
    return [c for c in out if c["service"] in ("tiktok", "youtube", "instagram") and not c.get("isQueuePaused")]
CREATE = """mutation($input: CreatePostInput!) { createPost(input: $input) {
  ... on PostActionSuccess { post { id dueAt } } ... on MutationError { message } } }"""
def video_path(v):
    return v.get("file") or f"videos/{v['id']}.mp4"


def main():
    if os.environ.get("CHECK_ONLY") == "yes":
        print("Buffer key present:", "yes" if KEY else "NO (secret missing or empty)", "| length:", len(KEY))
        try:
            chs = channels()
            print("Channels this key can post to:", [(c["service"], c["name"]) for c in chs])
        except Exception as e:
            print("CHECK FAILED:", type(e).__name__, str(e)[:400])
        return
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and os.environ.get("CONFIRM_POST") != "post":
        print("Manual run: nothing posted. To really post, type the word post in the 'confirm' box."); return
    dry = "--dry-run" in sys.argv
    now = dt.datetime.now(ZoneInfo("America/Chicago"))
    manual = "--force" in sys.argv or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if now.weekday() not in DAYS and not manual:
        print("Not a posting day (Mon/Tue/Thu/Fri). Nothing to do."); return
    posted = json.loads(STATE.read_text()) if STATE.exists() else {}
    todo = [v for v in CFG["videos"] if not v.get("hold") and v["id"] not in posted and (ROOT / video_path(v)).exists()]
    if not todo:
        print("All videos have been posted. Ask Claude for new scripts."); return
    pick = os.environ.get("VIDEO", "").strip()          # manual run of a chosen video: still never a held one
    if pick:
        todo = [x for x in todo if x["id"] == pick] or todo
    v = todo[0]
    rel = video_path(v)                                  # ready-made file; no AI voiceover is ever added
    url = f"https://raw.githubusercontent.com/{REPO}/main/{rel}"
    text = f"{v['caption']}\n\n{CFG['hashtags']}"
    if dry or not KEY:
        print(f"[{'dry run' if dry else 'no BUFFER_API_KEY'}] would schedule {v['id']} -> {url}\n{text}"); return
    due = now.replace(hour=12, minute=7, second=0, microsecond=0)
    if due < now + dt.timedelta(minutes=20): due = now + dt.timedelta(minutes=30)
    due_utc = due.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    results = []
    for ch in channels():
        svc = ch["service"]
        meta = {"youtube": {"youtube": {"title": v["yt_title"][:100], "privacy": "public", "categoryId": "27", "madeForKids": False, "notifySubscribers": False}},
                "instagram": {"instagram": {"type": "reel", "shouldShareToFeed": True}},
                "tiktok": {"tiktok": {"title": v["caption"][:90]}}}[svc]
        inp = {"channelId": ch["id"], "text": text, "schedulingType": "automatic", "mode": "customScheduled", "dueAt": due_utc,
               "assets": [{"video": {"url": url, "metadata": {"thumbnailOffset": 1000}}}], "metadata": meta}
        try:
            res = q(CREATE, {"input": inp})["createPost"]
            results.append(f"{svc}: {'scheduled ' + due_utc if 'post' in res else 'ERROR ' + res.get('message', '')}")
        except Exception as e:
            results.append(f"{svc}: ERROR {e}")
    print("\n".join(results))
    if any("scheduled" in r for r in results):
        posted[v["id"]] = {"date": str(now.date()), "results": results}
        STATE.write_text(json.dumps(posted, indent=1))
if __name__ == "__main__": main()
