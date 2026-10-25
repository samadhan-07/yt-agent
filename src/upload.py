import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _service():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _insert(yt, path, snippet, status):
    media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body={"snippet": snippet, "status": status},
                             media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


def upload(path, title, description, tags, privacy="private", category_id="27"):
    snippet = {
        "title": title[:100],
        "description": description[:4900],
        "tags": tags[:15],
        "categoryId": category_id,
    }
    status = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True,   # YouTube's "altered or synthetic content" disclosure
    }
    yt = _service()
    try:
        return _insert(yt, path, snippet, status)
    except HttpError as e:
        # If the API rejects the disclosure field, upload without it rather than lose the video.
        if e.resp.status == 400 and "containsSyntheticMedia" in str(e):
            print("WARN: API rejected containsSyntheticMedia; set the AI label manually in Studio.", flush=True)
            status.pop("containsSyntheticMedia")
            return _insert(yt, path, snippet, status)
        raise
