"""YouTube upload (resumable), scheduled publishing, custom thumbnail, category playlists."""
import datetime as dt, time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import config


def service():
    # IMPORTANT: no `scopes=` here. A refresh token can only be used with the scopes it was created with;
    # asking for other scopes gives "invalid_scope". Without it Google uses the token's own scopes.
    c = Credentials(None, refresh_token=config.env("YT_REFRESH_TOKEN"), token_uri="https://oauth2.googleapis.com/token",
                    client_id=config.env("YT_CLIENT_ID"), client_secret=config.env("YT_CLIENT_SECRET"))
    c.refresh(Request())
    return build("youtube", "v3", credentials=c, cache_discovery=False)


def next_slot(mode, lead_min=20):
    hours = config.SHORT_SLOTS if mode == "short" else config.LONG_SLOTS
    tz = dt.timedelta(hours=config.SLOT_TZ_OFFSET)
    now_local = dt.datetime.utcnow() + tz
    cands = []
    for day in (0, 1):
        for h in hours:
            t = (now_local + dt.timedelta(days=day)).replace(hour=h, minute=0, second=0, microsecond=0)
            if t > now_local + dt.timedelta(minutes=lead_min):
                cands.append(t)
    return min(cands) - tz


def ensure_playlist(yt, title, desc, st):
    if title in st["playlists"]:
        return st["playlists"][title]
    token = None
    while True:
        r = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
        for p in r.get("items", []):
            if p["snippet"]["title"] == title:
                st["playlists"][title] = p["id"]
                return p["id"]
        token = r.get("nextPageToken")
        if not token:
            break
    r = yt.playlists().insert(part="snippet,status", body={
        "snippet": {"title": title, "description": desc, "defaultLanguage": "en"},
        "status": {"privacyStatus": "public"}}).execute()
    st["playlists"][title] = r["id"]
    return r["id"]


def upload(video, meta, thumb, playlist_title, playlist_desc, st, mode, publish_now=False, log=print):
    yt = service()
    status = {"selfDeclaredMadeForKids": False, "embeddable": True, "publicStatsViewable": True}
    if publish_now:
        status["privacyStatus"] = "public"
    else:
        slot = next_slot(mode)
        status.update(privacyStatus="private", publishAt=slot.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
        log("[upload] scheduled for", slot, "UTC")
    body = {"snippet": {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
                        "categoryId": "27", "defaultLanguage": "en", "defaultAudioLanguage": "en"}, "status": status}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=32 * 1024 * 1024, resumable=True, mimetype="video/mp4"))
    resp, tries = None, 0
    while resp is None:
        try:
            s, resp = req.next_chunk()
            if s:
                log(f"[upload] {int(s.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and tries < 8:
                tries += 1
                time.sleep(2 ** tries)
            else:
                raise
    vid = resp["id"]
    log("[upload] video uploaded:", vid)
    if thumb:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
        except Exception as e:
            log("[upload] thumbnail not set:", str(e)[:200])
    try:  # the video is already live; a playlist problem must never fail the whole run
        pl = ensure_playlist(yt, playlist_title, playlist_desc, st)
        yt.playlistItems().insert(part="snippet", body={"snippet": {
            "playlistId": pl, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
        log("[upload] added to playlist:", playlist_title)
    except Exception as e:
        log("[upload] playlist step skipped (token may lack the 'youtube' scope):", str(e)[:200])
    return vid
