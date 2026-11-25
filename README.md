# FrameRelay promo videos
Short vertical promo videos for framerelay.app, scheduled through Buffer. No secrets in this repo; the Buffer key lives in GitHub Actions secrets.

## Current format: "showcase" (no AI voiceover)
`make_before_after.py` (run by `.github/workflows/before-after.yml`, driven by `.github/ba-request.json`) builds each video:
1. a real clip plays first (vertical crop, captions, the speaker's own audio, hook title, "From a 63-minute interview" badge);
2. a quick recap: the long video scrubs past, markers show where the moments were found, 3 clip cards;
3. end card: FrameRelay / Long videos into ready-to-post clips / framerelay.app.

Every video shows "Example clip. Not a FrameRelay customer or endorsement." and the source credit, on screen and in the caption.

## Source rules
Internet Archive and Wikimedia Commons only. License read from the item's own metadata at build time: CC BY, CC0 or
Public Domain only; CC BY-SA, NC, ND and unclear licenses are refused, as are re-uploads of YouTube/Twitch/TV material.
No well-known brands/logos or famous people as the main subject (checked by a person). Source link + license saved per video.

## Posting
`post.py` + `.github/workflows/post.yml` post one video on Mon/Tue/Thu/Fri, exactly as committed (no voiceover).
Entries in `scripts.json` with `"hold": true` are never posted, not even by a manual run. Finished videos live in `videos/showcase/`.
Older text-card videos (`make_videos.py`) are kept for history only.
