# FrameRelay promo videos
Text-card short videos for framerelay.app, scheduled through Buffer. No secrets in this repo; the Buffer key lives in GitHub Actions secrets.
- `scripts.json`: the video scripts. `python make_videos.py` builds `videos/`.
- `post.py` + `.github/workflows/post.yml`: schedule one new video on Mon/Tue/Thu/Fri. Does nothing until `BUFFER_API_KEY` is set.
