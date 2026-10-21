"""Merge two brain.json files without losing any book.   python merge_brain.py MINE.json REMOTE.json
Result is written into REMOTE.json (missing/empty remote is fine)."""
import json, sys, os

RANK = {"done": 4, "skipped": 3, "claimed": 2, "failed": 1, "new": 0}


def load(p):
    try:
        return json.load(open(p)) if os.path.exists(p) and os.path.getsize(p) else {}
    except Exception:
        return {}


def better(a, b):
    sa = (RANK.get(a.get("status"), 0), bool(a.get("long", {}).get("done")), len(a.get("shorts", [])))
    sb = (RANK.get(b.get("status"), 0), bool(b.get("long", {}).get("done")), len(b.get("shorts", [])))
    return a if sa >= sb else b


def merge(mine, theirs):
    out = {"version": 2, "books": {}, "rss_seen": [], "playlists": {}}
    out["playlists"] = {**theirs.get("playlists", {}), **mine.get("playlists", {})}
    seen = list(dict.fromkeys(theirs.get("rss_seen", []) + mine.get("rss_seen", [])))
    out["rss_seen"] = seen[-3000:]
    keys = set(mine.get("books", {})) | set(theirs.get("books", {}))
    for k in keys:
        a, b = mine.get("books", {}).get(k), theirs.get("books", {}).get(k)
        if a and b:
            win, lose = (a, b) if better(a, b) is a else (b, a)
            m = dict(win)
            shorts = {s.get("video_id") or s.get("idea"): s for s in lose.get("shorts", []) + win.get("shorts", [])}
            m["shorts"] = list(shorts.values())
            m["concepts"] = win.get("concepts") or lose.get("concepts", [])
            m["attempts"] = max(a.get("attempts", 0), b.get("attempts", 0))
            if lose.get("long", {}).get("done") and not m.get("long", {}).get("done"):
                m["long"] = lose["long"]
            out["books"][k] = m
        else:
            out["books"][k] = a or b
    return out


if __name__ == "__main__":
    mine, remote = load(sys.argv[1]), load(sys.argv[2])
    merged = merge(mine, remote)
    json.dump(merged, open(sys.argv[2], "w"), indent=2, ensure_ascii=False)
    print(f"[merge] books: mine={len(mine.get('books', {}))} remote={len(remote.get('books', {}))} merged={len(merged['books'])}")
