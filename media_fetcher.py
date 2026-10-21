"""Stock photo / video fetcher: Pixabay + Pexels (+ Wikimedia Commons fallback). Rate-limit aware, de-duplicating."""
import hashlib, random, threading, time
from pathlib import Path
import requests
from PIL import Image
import config

UA = {"User-Agent": "BookExplainerBot/1.0"}


class Media:
    def __init__(self, cache: Path):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.used, self.lock = set(), threading.Lock()
        self.last, self.pexels_left = {}, config.PEXELS_BUDGET

    def _throttle(self, prov, gap):
        with self.lock:
            wait = self.last.get(prov, 0) + gap - time.time()
            self.last[prov] = time.time() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def _json(self, prov, url, gap, **kw):
        for _ in range(3):
            self._throttle(prov, gap)
            try:
                r = requests.get(url, timeout=25, headers=kw.pop("headers", {}) or UA, **kw)
                if r.status_code == 429:
                    time.sleep(20)
                    continue
                return r.json() if r.ok else {}
            except Exception:
                time.sleep(2)
        return {}

    def _pick(self, cands):
        with self.lock:
            fresh = [c for c in cands if c[0] not in self.used] or []
            if not fresh:
                return None
            c = random.choice(fresh[:6])
            self.used.add(c[0])
            return c

    def _download(self, url, ext):
        p = self.cache / (hashlib.md5(url.encode()).hexdigest() + ext)
        if p.exists() and p.stat().st_size > 2000:
            return p
        try:
            r = requests.get(url, headers=UA, timeout=60, stream=True)
            if not r.ok:
                return None
            with open(p, "wb") as f:
                for ch in r.iter_content(1 << 16):
                    f.write(ch)
            if ext == ".jpg":
                Image.open(p).verify()
            return p
        except Exception:
            p.unlink(missing_ok=True)
            return None

    def _pixabay_photos(self, q):
        if not config.PIXABAY_KEY:
            return []
        d = self._json("pixabay", "https://pixabay.com/api/", 0.7, params={
            "key": config.PIXABAY_KEY, "q": q, "image_type": "photo", "per_page": 20, "safesearch": "true",
            "min_width": 1200, "order": "popular"})
        return [(f"pb{h['id']}", h["largeImageURL"]) for h in d.get("hits", [])]

    def _pexels_photos(self, q, orient):
        if not config.PEXELS_KEY or self.pexels_left <= 0:
            return []
        self.pexels_left -= 1
        d = self._json("pexels", "https://api.pexels.com/v1/search", 1.0, headers={"Authorization": config.PEXELS_KEY},
                       params={"query": q, "per_page": 15, "orientation": orient})
        return [(f"px{p['id']}", p["src"].get("large2x") or p["src"]["large"]) for p in d.get("photos", [])]

    def _commons(self, q):
        d = self._json("commons", "https://commons.wikimedia.org/w/api.php", 1.0, params={
            "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {q}", "gsrnamespace": 6,
            "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": 1600, "format": "json"})
        out = []
        for p in d.get("query", {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            if ii.get("mime", "").startswith("image/") and ii.get("thumburl"):
                out.append((f"wc{p['pageid']}", ii["thumburl"]))
        return out

    def _pexels_videos(self, q, orient):
        if not config.PEXELS_KEY or self.pexels_left <= 0:
            return []
        self.pexels_left -= 1
        d = self._json("pexels", "https://api.pexels.com/videos/search", 1.0, headers={"Authorization": config.PEXELS_KEY},
                       params={"query": q, "per_page": 10, "orientation": orient})
        out = []
        for v in d.get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and (f.get("width") or 0) <= 1920]
            if files:
                best = max(files, key=lambda f: f.get("width") or 0)
                out.append((f"pxv{v['id']}", best["link"]))
        return out

    def _pixabay_videos(self, q):
        if not config.PIXABAY_KEY:
            return []
        d = self._json("pixabay", "https://pixabay.com/api/videos/", 0.7, params={
            "key": config.PIXABAY_KEY, "q": q, "per_page": 15, "safesearch": "true"})
        out = []
        for h in d.get("hits", []):
            vv = h.get("videos", {})
            u = (vv.get("large") or vv.get("medium") or {}).get("url")
            if u:
                out.append((f"pbv{h['id']}", u))
        return out

    def photo(self, queries, portrait=False):
        orient = "portrait" if portrait else "landscape"
        for q in queries:
            for fn in (lambda: self._pixabay_photos(q), lambda: self._pexels_photos(q, orient), lambda: self._commons(q)):
                c = self._pick(fn())
                if c and (p := self._download(c[1], ".jpg")):
                    return p
        return None

    def video(self, queries, portrait=False):
        orient = "portrait" if portrait else "landscape"
        for q in queries:
            for fn in (lambda: self._pexels_videos(q, orient), lambda: self._pixabay_videos(q)):
                c = self._pick(fn())
                if c and (p := self._download(c[1], ".mp4")):
                    return p
        return None
