# youtube-post

This folder contains two scripts:

- `youtube/post_one_video.py` — uploads **1** video per run (reads `manifests/*.json`, writes `youtube/state/youtube_post_state.json`).
- `youtube/comment_worker.py` — posts **1** top-level comment under the latest successful upload (reads post-state, writes `youtube/state/youtube_comment_state.json`).

## Important
`YOUTUBE_API_KEY` is fine for public data, but **YouTube uploads and comments require OAuth 2.0 user credentials**.

## Required secrets (OAuth)
Set **one** of the following options in your repo secrets:

### Option A (recommended)
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

### Option B
- `YOUTUBE_OAUTH_JSON` (JSON with `client_id`, `client_secret`, `refresh_token`; optional `token_uri`)

## Optional env
- `YOUTUBE_MANIFEST_DIR` (default: `<repo>/manifests`)
- `YOUTUBE_POST_STATE_PATH` (default: `<repo>/youtube/state/youtube_post_state.json`)
- `YOUTUBE_COMMENT_STATE_PATH` (default: `<repo>/youtube/state/youtube_comment_state.json`)
- `YOUTUBE_PRIVACY_STATUS` = public|unlisted|private (default: public)
- `YOUTUBE_CATEGORY_ID` (default: 26)
- `YOUTUBE_MADE_FOR_KIDS` = true|false (default: false)
- `YOUTUBE_TAGS` = comma-separated tags
- `YOUTUBE_COMMENT_JITTER_MAX_SEC` (default: 3600)
- `YOUTUBE_POST_DRY_RUN` / `YOUTUBE_COMMENT_DRY_RUN` = 1
