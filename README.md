# yt-agent: free faceless YouTube Shorts pipeline

Gemini (script + image prompts) → Pollinations/FLUX (AI images) → Edge-TTS neural voice (with word timings) → FFmpeg (Ken Burns motion + burned-in captions) → YouTube Data API (upload). Runs on GitHub Actions, all free tiers.

## Setup
1. Push this folder to a new GitHub repo.
2. Get keys:
   - `GEMINI_API_KEY`: https://aistudio.google.com/apikey
   - `POLLINATIONS_API_KEY` (optional, free): sign up at https://auth.pollinations.ai. Without it the anonymous tier is rate-limited to about 1 image per 15 s and may add a watermark.
3. YouTube OAuth:
   - Google Cloud Console → new project → enable **YouTube Data API v3**
   - OAuth consent screen (External), add yourself as a test user, then publish the app to "In production" so the refresh token does not expire after 7 days
   - Create credentials → OAuth client ID → **Desktop app** → download as `scripts/client_secret.json`
   - `pip install google-auth-oauthlib && cd scripts && python get_refresh_token.py`
   - Copy the three printed values
4. Repo → Settings → Secrets → Actions: add `GEMINI_API_KEY`, `POLLINATIONS_API_KEY` (optional), `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
5. Actions → daily-video → Run workflow (dry run on) → download the `preview` artifact and check it.
6. Run once with dry run off, with `privacy: private` in `config.yaml`. When happy, set `privacy: public`.

## Important YouTube limits
- Videos uploaded via the API from an unaudited Cloud project are **locked to private**. Submit the YouTube API Services audit/compliance form to lift this.
- An upload costs 1,600 quota units; the default 10,000/day allows about 6 uploads/day.
- YouTube demotes mass-produced, repetitive content. Keep scripts original and add real value.

## Local test
```
pip install -r requirements.txt   # plus ffmpeg installed
export GEMINI_API_KEY=... DRY_RUN=1
python -m src.main                # writes out/preview.mp4
```
