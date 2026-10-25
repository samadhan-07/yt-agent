"""Weekly job: pull views/likes/comments for every video in state/history.json and write
state/metrics.json. script_gen then feeds the best titles back into the prompt.

Needs a refresh token that also has the youtube.readonly scope (run scripts/get_refresh_token.py again)."""
import datetime, json, os, pathlib
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from . import state

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def main():
    st = state.load()
    titles = {v["id"]: v["title"] for v in st.get("videos", []) if v.get("id")}
    if not titles:
        print("No videos in history yet.")
        return
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    rows = []
    ids = list(titles)
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="statistics,status", id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            s = it.get("statistics", {})
            rows.append({"id": it["id"], "title": titles[it["id"]],
                         "privacy": it.get("status", {}).get("privacyStatus"),
                         "views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                         "comments": int(s.get("commentCount", 0))})
    rows.sort(key=lambda r: r["views"], reverse=True)
    out = {"updated": datetime.datetime.utcnow().isoformat() + "Z", "videos": rows}
    p = pathlib.Path("state/metrics.json")
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["| views | likes | privacy | title |", "|---|---|---|---|"]
    lines += [f"| {r['views']} | {r['likes']} | {r['privacy']} | {r['title']} |" for r in rows[:30]]
    report = "\n".join(lines)
    print(report)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(report + "\n")
    private = [r for r in rows if r["privacy"] == "private"]
    if private:
        print(f"\nWARNING: {len(private)} video(s) are PRIVATE, so nobody can watch them.")


if __name__ == "__main__":
    main()
