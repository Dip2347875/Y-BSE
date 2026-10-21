"""Collects raw research material: YouTube captions (other channels' book videos), web pages, Wikipedia,
public-domain full texts (Project Gutenberg / Internet Archive) and public PDFs from open-access sites.
The text is used ONLY as research input - the script itself is written from scratch by the local AI."""
import hashlib, io, re, tempfile, time
from pathlib import Path
import requests
import brain

UA = {"User-Agent": "Mozilla/5.0 (compatible; BookExplainerBot/3.0)"}
# Full-text PDFs are taken ONLY from open-access / institutional hosts. Piracy hosts are blocked on purpose.
ALLOW_PDF = (".edu", ".gov", ".ac.uk", ".edu.au", "archive.org", "gutenberg.org", "openstax.org", "arxiv.org",
             "who.int", "oecd.org", "unesco.org", "nih.gov", "europa.eu")
PIRACY = ("libgen", "z-lib", "zlibrary", "pdfdrive", "vdoc", "epdf", "dokumen", "scribd", "pdfcoffee", "ebin", "bookfi",
          "b-ok", "1lib", "annas-archive", "sci-hub", "pdfroom", "kupdf", "fliphtml5", "yumpu", "ebooksz", "freebookspot")
STOP = set("the a an and of to in on for with by how why what is are your you from".split())


def wc(t):
    return len(t.split())


def _get(url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=kw.pop("timeout", 30), **kw)
        return r if r.ok else None
    except Exception:
        return None


# ------------------------------------------------------------------ YouTube
def clean_caption(t):
    t = re.sub(r"WEBVTT.*?\n\n", " ", t, flags=re.S)
    t = re.sub(r"\d\d:\d\d:\d\d[.,]\d+\s*-->.*", " ", t)
    t = re.sub(r"<[^>]+>|\[[^\]]*\]|align:\w+|position:\d+%", " ", t)
    words, out, last = t.split(), [], ""
    for w in words:  # auto-captions repeat lines; drop immediate repeats
        if w != last:
            out.append(w)
        last = w
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def yt_search(query, n=8):
    out = []
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True, "skip_download": True, "noplaylist": True}) as y:
            info = y.extract_info(f"ytsearch{n}:{query}", download=False)
        for e in (info.get("entries") or []):
            if e and e.get("id"):
                out.append(dict(id=e["id"], title=e.get("title", ""), duration=e.get("duration") or 0,
                                channel=e.get("channel") or e.get("uploader") or ""))
    except Exception as ex:
        print("[yt] search via yt-dlp failed:", str(ex)[:90])
    if not out:
        try:
            from ddgs import DDGS
            for r in DDGS().videos(query, max_results=n):
                m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", r.get("content") or r.get("url") or "")
                if m:
                    out.append(dict(id=m.group(1), title=r.get("title", ""), duration=0, channel=r.get("uploader", "")))
        except Exception as ex:
            print("[yt] search via ddgs failed:", str(ex)[:90])
    return out


def yt_transcript(vid):
    langs = ["en", "en-US", "en-GB"]
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            parts = YouTubeTranscriptApi.get_transcript(vid, languages=langs)
            text = " ".join(p["text"] for p in parts)
        else:
            parts = YouTubeTranscriptApi().fetch(vid, languages=langs)
            text = " ".join(p.text for p in parts)
        return clean_caption(text)
    except Exception as ex:
        print(f"[yt] caption API blocked/unavailable for {vid}: {str(ex)[:70]}")
    try:
        import yt_dlp
        with tempfile.TemporaryDirectory() as tmp:
            opts = {"quiet": True, "skip_download": True, "writeautomaticsub": True, "writesubtitles": True,
                    "subtitleslangs": ["en.*"], "subtitlesformat": "vtt", "outtmpl": f"{tmp}/%(id)s"}
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([f"https://www.youtube.com/watch?v={vid}"])
            files = list(Path(tmp).glob("*.vtt"))
            if files:
                return clean_caption(files[0].read_text(errors="ignore"))
    except Exception as ex:
        print(f"[yt] yt-dlp captions failed for {vid}: {str(ex)[:70]}")
    return ""


def video_relevant(v, title, author):
    vt = (v["title"] + " " + v["channel"]).lower()
    toks = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOP]
    if not toks or not all(t in vt for t in toks):
        return False
    if v["duration"] and not (240 <= v["duration"] <= 14400):
        return False
    return brain.surname(author) in vt or any(k in vt for k in ("book", "audiobook", "summary"))


def youtube_sources(title, author, max_videos=8):
    seen, picked = set(), []
    for q in (f"{title} {author} book summary", f"{title} {author} audiobook", f"{title} book review explained",
              f"{title} {author} key lessons"):
        for v in yt_search(q, 8):
            if v["id"] not in seen and video_relevant(v, title, author):
                seen.add(v["id"])
                picked.append(v)
        time.sleep(1)
    out = []
    for v in picked[:max_videos * 2]:
        if len(out) >= max_videos:
            break
        t = yt_transcript(v["id"])
        if wc(t) >= 400:
            out.append(dict(kind="video", name=v["title"], text=t))
        time.sleep(1)
    print(f"[yt] {len(picked)} relevant videos found, {len(out)} transcripts extracted")
    return out


# ------------------------------------------------------------------ public-domain libraries
def _strip_gutenberg(t):
    a = re.search(r"\*\*\* ?START OF.*?\*\*\*", t)
    b = re.search(r"\*\*\* ?END OF", t)
    return t[a.end():b.start()] if a and b else t


def gutenberg_text(title, author):
    r = _get("https://gutendex.com/books", params={"search": f"{title} {brain.surname(author)}"})
    for b in (r.json().get("results", []) if r else []):
        names = " ".join(a.get("name", "") for a in b.get("authors", [])).lower()
        if brain.norm_title(b.get("title", "")) == brain.norm_title(title) and brain.surname(author) in names:
            f = b.get("formats", {})
            url = f.get("text/plain; charset=utf-8") or f.get("text/plain; charset=us-ascii") or f.get("text/plain")
            t = _get(url, timeout=60) if url else None
            if t:
                return _strip_gutenberg(t.text)
    return ""


def archive_text(title, author):
    """Internet Archive items that are explicitly marked public-domain / openly licensed (never lending-library scans)."""
    q = f'title:("{title}") AND creator:({brain.surname(author)}) AND mediatype:texts'
    r = _get("https://archive.org/advancedsearch.php", params={"q": q, "fl[]": ["identifier"], "rows": 5, "output": "json"})
    for doc in (r.json().get("response", {}).get("docs", []) if r else []):
        ident = doc["identifier"]
        m = _get(f"https://archive.org/metadata/{ident}")
        meta = (m.json().get("metadata", {}) if m else {})
        flag = str(meta.get("possible-copyright-status", "")) + str(meta.get("licenseurl", ""))
        if "NOT_IN_COPYRIGHT" in flag or "publicdomain" in flag or "creativecommons" in flag:
            t = _get(f"https://archive.org/download/{ident}/{ident}_djvu.txt", timeout=90)
            if t and wc(t.text) > 8000:
                return t.text
    return ""


def public_pdfs(title, author, max_pdfs=3):
    urls = []
    try:
        from ddgs import DDGS
        for q in (f'"{title}" {author} filetype:pdf', f"{title} {author} study guide analysis filetype:pdf"):
            for h in DDGS().text(q, max_results=8):
                u = h.get("href") or h.get("url") or ""
                host = u.lower().split("/")[2] if u.count("/") >= 2 else ""
                if ".pdf" in u.lower() and any(host.endswith(x) or x in host for x in ALLOW_PDF) and not any(p in u.lower() for p in PIRACY):
                    urls.append(u)
            time.sleep(1)
    except Exception as ex:
        print("[pdf] search failed:", str(ex)[:80])
    out = []
    from pypdf import PdfReader
    for u in list(dict.fromkeys(urls))[:max_pdfs * 2]:
        if len(out) >= max_pdfs:
            break
        r = _get(u, timeout=60)
        if not r or len(r.content) > 25_000_000:
            continue
        try:
            reader = PdfReader(io.BytesIO(r.content))
            text = " ".join((p.extract_text() or "") for p in reader.pages[:150])
        except Exception:
            continue
        if wc(text) > 1500 and text.lower().count(title.lower()) >= 2:
            out.append(dict(kind="pdf", name=u.split("/")[-1][:60], text=re.sub(r"\s+", " ", text)))
    print(f"[pdf] {len(out)} open-access PDFs extracted")
    return out


# ------------------------------------------------------------------ everything together
def gather(d, log=print):
    title, author = d["title"], d["author"]
    src, seen = [], set()

    def add(kind, name, text, minimum=200):
        text = re.sub(r"\s+", " ", text or "").strip()
        key = hashlib.md5(text[:300].lower().encode()).hexdigest()
        if wc(text) >= minimum and key not in seen:
            seen.add(key)
            src.append(dict(kind=kind, name=name, text=text, words=wc(text)))

    bw, aw = d.get("book_wiki", {}), d.get("author_wiki", {})
    add("wiki", "book article", (bw.get("intro", "") + " " + " ".join(bw.get("sections", {}).values())))
    add("wiki", "author article", (aw.get("intro", "") + " " + " ".join(aw.get("sections", {}).values())))
    add("wiki", "publisher description", d.get("description", ""), minimum=60)
    for v in youtube_sources(title, author):
        add("video", v["name"], v["text"], minimum=400)
    for i, t in enumerate(d.get("web_texts", [])):
        add("web", f"web page {i + 1}", t, minimum=400)
    for kind, fn in (("book", gutenberg_text), ("book", archive_text)):
        try:
            t = fn(title, author)
            if t:
                add(kind, f"public-domain full text ({fn.__name__})", t, minimum=3000)
        except Exception as ex:
            log(f"[sources] {fn.__name__} failed: {str(ex)[:80]}")
    for p in public_pdfs(title, author):
        add("pdf", p["name"], p["text"], minimum=1500)
    by_kind = {}
    for s in src:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + s["words"]
    log(f"[sources] words by kind: {by_kind}")
    return src
