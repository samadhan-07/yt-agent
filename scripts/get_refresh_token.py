"""Run ONCE on your own computer to get a YouTube refresh token.
Needs client_secret.json (OAuth client of type 'Desktop app') in this folder.
The token gets two permissions: upload videos, and read your channel's video statistics
(used by the weekly analytics job). Put the three values into GitHub Secrets."""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nYT_CLIENT_ID     =", creds.client_id)
print("YT_CLIENT_SECRET =", creds.client_secret)
print("YT_REFRESH_TOKEN =", creds.refresh_token)
