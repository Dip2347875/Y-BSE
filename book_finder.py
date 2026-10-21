"""Finds REAL books from RSS (verified against Google Books / Open Library), never repeats a book (brain),
and researches it using only free, key-less sources (Wikipedia, Open Library, Google Books, open web)."""
import difflib, html, random, re, time
from collections import Counter
from urllib.parse import unquote
import feedparser, requests
from PIL import Image, ImageDraw
import config, brain

UA = {"User-Agent": "Mozilla/5.0 (compatible; BookExplainerBot/2.1)"}
WIKI = "https://en.wikipedia.org/w/api.php"

SUBJECTS = ["self-help", "personal development", "psychology", "business", "entrepreneurship", "economics", "philosophy",
            "history", "science", "biography", "leadership", "productivity", "health", "communication", "finance",
            "investing", "creativity", "neuroscience", "sociology", "education", "mindfulness", "negotiation"]

# third-party summaries / workbooks / special editions are NOT the original book
EDITION_BAD = re.compile(r"\b(summary|summaries|workbook|study guide|sparknotes|cliffsnotes|companion|graphic novel|"
                         r"illustrated|abridged|audio|box set|boxed|collection|journal|notebook|analysis|trivia|"
                         r"conversation starters|team assessment|participant)\b", re.I)


def _clean(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(t or ""))).strip()


def _get(url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=25, **kw)
        return r if r.ok else None
    except Exception:
        return None


def _ratio(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def short_title(t):
    """'Quiet: The Power of Introverts' -> 'Quiet' ; 'X - Team Assessment' -> 'X'"""
    return re.split(r"\s[-\u2013\u2014]\s|:", t or "")[0].strip() or (t or "")


def _edition_ok(v):
    return not EDITION_BAD.search(f"{v.get('title', '')} {v.get('subtitle', '')}")


# ------------------------------------------------------------------ is it really a book?
def _google_volumes(title, author, n=8):
    q = f'intitle:"{title}"' + (f" inauthor:{brain.surname(author)}" if author else "")
    r = _get("https://www.googleapis.com/books/v1/volumes",
             params={"q": q, "maxResults": n, "printType": "books", "langRestrict": "en"})
    return [it.get("volumeInfo", {}) for it in (r.json().get("items", []) if r else [])]


def _openlibrary_docs(title, author, n=5):
    r = _get("https://openlibrary.org/search.json",
             params={"title": title, "author": author, "limit": n,
                     "fields": "key,title,author_name,first_publish_year,cover_i,subject,number_of_pages_median,language"})
    return r.json().get("docs", []) if r else []


def verify_book(title, author=""):
    """Return {'title','author'} only if the thing is a genuine published English book, else None."""
    nt, sn = brain.norm_title(title), brain.surname(author)
    best, score = None, 0.0
    for v in _google_volumes(title, author):
        authors = v.get("authors") or []
        vt = v.get("title", "")
        if not _edition_ok(v) or not authors or (sn and sn not in " ".join(authors).lower()):
            continue
        s = _ratio(nt, brain.norm_title(vt))
        if s >= 0.88 and len(v.get("description", "")) >= 150 and (v.get("pageCount") or 120) >= 80:
            s -= len(vt) / 10000  # tie-break: prefer the shortest (original) edition title
            if s > score:
                best, score = dict(title=short_title(vt), author=authors[0]), s
    if best:
        return best
    time.sleep(0.4)
    for d in _openlibrary_docs(title, author):
        authors = d.get("author_name") or []
        s = _ratio(nt, brain.norm_title(d.get("title", "")))
        if authors and not EDITION_BAD.search(d.get("title", "")) and (not sn or sn in " ".join(authors).lower()) \
                and s >= 0.9 and (d.get("number_of_pages_median") or 120) >= 80:
            return dict(title=short_title(d["title"]), author=authors[0])
    return None


# ------------------------------------------------------------------ RSS -> candidate titles
QUOTED = re.compile(r"[\u201c\"\u2018']([^\u201d\"\u2019']{3,90})[\u201d\"\u2019'](?:,?\s+(?:by|from)\s+([A-Z][\w.\-' ]{3,40}))?")
BYLINE = re.compile(r"^(.{3,90}?)\s+by\s+([A-Z][A-Za-z.\-' ]{3,40}?)(?:\s+review|\s*[:|\u2013\u2014-]|$)")


def entry_candidates(title, summary):
    out = []
    t = re.sub(r"^(book\s+)?review[:\s\-\u2013]+", "", title, flags=re.I).strip()
    m = BYLINE.match(t)
    if m:
        out.append((m.group(1).strip(" '\"\u201c\u201d\u2018\u2019"), m.group(2).strip()))
    for text in (title, summary[:400]):
        for m in QUOTED.finditer(text):
            out.append((m.group(1).strip(), (m.group(2) or "").strip()))
    if 3 <= len(t) <= 70:
        out.append((t, ""))
    seen, res = set(), []
    for c in out:
        k = brain.norm_title(c[0])
        if k and k not in seen:
            seen.add(k)
            res.append(c)
    return res


def openlibrary_discover():
    """Books that are trending right now on Open Library (no names stored in this program)."""
    for period in ("weekly", "monthly", "yearly"):
        r = _get(f"https://openlibrary.org/trending/{period}.json", params={"limit": 60})
        for w in (r.json().get("works", []) if r else []):
            if w.get("title") and w.get("author_name"):
                yield w["title"], w["author_name"][0]


def google_discover():
    """Popular books found through Google Books subject searches, in random order."""
    subjects = SUBJECTS[:]
    random.shuffle(subjects)
    for sub in subjects:
        r = _get("https://www.googleapis.com/books/v1/volumes",
                 params={"q": f"subject:{sub}", "orderBy": "relevance", "maxResults": 20, "printType": "books",
                         "langRestrict": "en", "startIndex": random.choice([0, 10, 20, 30])})
        for it in (r.json().get("items", []) if r else []):
            v = it.get("volumeInfo", {})
            if v.get("authors") and _edition_ok(v) and (v.get("ratingsCount", 0) >= 20 or v.get("averageRating", 0) >= 4) \
                    and (v.get("pageCount") or 0) >= 120 and len(v.get("description", "")) >= 200:
                yield short_title(v.get("title", "")), v["authors"][0]
        time.sleep(0.5)


def next_books(br, mode, forced=None):
    """Generator of books to work on. Sources: brain backlog, RSS, Open Library trending, Google Books.
    Every candidate is verified to be a real book, and anything already in the brain is skipped."""
    if forced:
        t, _, a = forced.partition("|")
        yield dict(title=t.strip(), author=a.strip())
        return
    if mode == "short":
        for b in br.books_for_shorts():
            yield dict(title=b["title"], author=b["author"])
    else:
        for b in br.books_needing_long():
            yield dict(title=b["title"], author=b["author"])
    checked = [0]

    def vet(t, a):
        if br.is_blocked(t, a) or checked[0] >= 60:
            return None
        checked[0] += 1
        v = verify_book(t, a)
        time.sleep(0.5)
        return v if v and not br.is_blocked(v["title"], v["author"]) else None

    for url in config.RSS_FEEDS:
        try:
            feed = feedparser.parse(url, agent=UA["User-Agent"])
        except Exception as e:
            print("[rss] failed", url, e)
            continue
        for e in feed.entries[:40]:
            rid = e.get("id") or e.get("link") or e.get("title", "")
            if br.seen_rss(rid):
                continue
            br.add_rss(rid)
            for t, a in entry_candidates(_clean(e.get("title")), _clean(e.get("summary"))):
                v = vet(t, a)
                if v:
                    print(f"[rss] real book found: {v['title']} - {v['author']}")
                    yield v
                    break
    for source in (openlibrary_discover, google_discover):
        for t, a in source():
            v = vet(t, a)
            if v:
                print(f"[discover] {source.__name__}: {v['title']} - {v['author']}")
                yield v


# ------------------------------------------------------------------ Wikipedia helpers
def _wiki_intros(titles):
    out = {}
    for i in range(0, len(titles), 20):
        r = _get(WIKI, params={"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "exlimit": 20,
                               "redirects": 1, "titles": "|".join(titles[i:i + 20]), "format": "json"})
        if r:
            for p in r.json().get("query", {}).get("pages", {}).values():
                if p.get("extract"):
                    out[p["title"]] = p["extract"]
    return out


def _wiki_search(q, n=5):
    r = _get(WIKI, params={"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": n})
    return [h["title"] for h in r.json().get("query", {}).get("search", [])] if r else []


def _wiki_full(title):
    r = _get(WIKI, params={"action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "wiki",
                           "titles": title, "redirects": 1, "format": "json"})
    if not r:
        return {"intro": "", "sections": {}}
    page = next(iter(r.json().get("query", {}).get("pages", {}).values()), {})
    parts = re.split(r"\n== ([^=\n]+?) ==\n", "\n" + page.get("extract", ""))
    sections = {}
    for i in range(1, len(parts) - 1, 2):
        sections[parts[i].strip()] = re.sub(r"\n=+ [^=\n]+ =+\n", "\n", parts[i + 1]).strip()
    return {"intro": parts[0].strip(), "sections": sections, "title": page.get("title", title)}


def _wiki_links(title):
    r = _get(WIKI, params={"action": "query", "prop": "links", "pllimit": 500, "plnamespace": 0,
                           "titles": title, "redirects": 1, "format": "json"})
    if not r:
        return []
    page = next(iter(r.json().get("query", {}).get("pages", {}).values()), {})
    return [l["title"] for l in page.get("links", [])]


def _find_book_page(title, author):
    cands = _wiki_search(f"{title} {author} book")
    intros = _wiki_intros(cands) if cands else {}
    sn = brain.surname(author)
    for c in cands:
        head = intros.get(c, "")[:600].lower()
        if (not sn or sn in head) and re.search(r"\b(book|novel|memoir|treatise|work|published|nonfiction|non-fiction|essay)\b", head):
            return c
    return None


def _find_author_page(author):
    for c in _wiki_search(author, 4):
        if brain.surname(author) in c.lower():
            return c
    return None


# ------------------------------------------------------------------ concept mining
CUE = re.compile(r"\b(concept|theory|bias|effect|principle|phenomenon|technique|method|strategy|approach|tendency|"
                 r"framework|model|process|practice|skill|habit|heuristic|fallacy|philosophy|idea|ability|trait|emotion|"
                 r"behavio[u]?r|decision|learning|thinking|psychology|economics|management|mindset|cognitive|virtue)\b", re.I)
BAD = re.compile(r"\b(born|is a (city|town|village|company|county|district|film|album|band|song|television|novel|book)|"
                 r"may refer to|surname|given name|politician|actor|footballer|municipality)\b", re.I)
GSTOP = set("the a an and or but if of to in on at for with as is are was were be been it this that these those you your "
            "they their we our he she his her not no so than then there here from by about into over just very more most "
            "can could will would should have has had do does did what which who how why when also one two new like make "
            "get people time way many much even still such some any other only first book author reading read".split())
GENERIC = set("lesson career potential attention learning understanding knowledge science human culture business research "
              "school individual information meeting health strategy create become turning reason process principle purpose "
              "wisdom philosophy discipline determination teamwork matter thought planning intelligence failure suggestion "
              "wealth finance behavior behaviour performance leadership debate harmony argument conversation poverty virtue "
              "destiny feeling rights cognition progress effectiveness consumption patience rationality psychology "
              "creativity collaboration personality success life love time money power work mind world".split())


def _ngrams(text, exclude):
    words = re.findall(r"[a-z]+", text.lower())
    grams = set()
    for n in (1, 2, 3):
        for i in range(len(words) - n + 1):
            g = words[i:i + n]
            if g[0] in GSTOP or g[-1] in GSTOP or any(len(w) < 3 for w in g) or (n == 1 and len(g[0]) < 6):
                continue
            s = " ".join(g)
            if not any(x in s for x in exclude):
                grams.add(s)
    return grams


def mine_concepts(book_page, texts, exclude, limit=12):
    """Concept = a Wikipedia article that (a) is linked from the book's article or (b) is a 2-3 word phrase named in
    >=2 independent web pages about the book, AND whose first lines define a concept/technique (not a person, place,
    company or a generic everyday word)."""
    cands, linked = {}, set()
    for l in (_wiki_links(book_page) if book_page else []):
        if not re.search(r"\d{3,4}|\bList of\b|disambiguation", l):
            cands[l] = cands.get(l, 0) + 3
            linked.add(l)
    df = Counter()
    for t in texts:
        for g in _ngrams(t[:12000], exclude):
            if " " in g:                      # single words from free text are almost always generic
                df[g] += 1
    for g, c in df.most_common(150):
        if c >= 2:
            cands[g.capitalize()] = cands.get(g.capitalize(), 0) + c
    ranked = sorted(cands, key=lambda k: -cands[k])[:70]
    intros = _wiki_intros(ranked)
    alltext = " ".join(texts).lower()
    out = []
    for term, intro in intros.items():
        head = intro[:350]
        clean = re.sub(r"\s*\(.*?\)", "", term).strip()
        low = clean.lower()
        if len(intro) < 120 or BAD.search(head[:160]) or not CUE.search(head) or "disambiguation" in term.lower():
            continue
        if any(x in low for x in exclude) or low.startswith("list of"):
            continue
        if " " not in low and (low in GENERIC or term not in linked):
            continue
        out.append((alltext.count(low) + cands.get(term, 0) * 2, clean, intro))
    out.sort(reverse=True)
    res, used = [], []
    for _, term, intro in out:
        low = term.lower()
        if any(low in u or u in low for u in used):
            continue
        used.append(low)
        res.append(dict(term=term, text=intro))
        if len(res) >= limit:
            break
    return res


# ------------------------------------------------------------------ web pages (research input only)
def _search_urls(queries):
    urls = []
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
    except Exception:
        DDGS = None
    for q in queries:
        got = 0
        if DDGS:
            try:
                for h in DDGS().text(q, max_results=6):
                    u = h.get("href") or h.get("url")
                    if u:
                        urls.append(u)
                        got += 1
            except Exception as e:
                print("[web] ddgs failed for one query:", str(e)[:60])
        if got == 0:
            r = _get("https://html.duckduckgo.com/html/", params={"q": q})
            if r:
                for m in re.finditer(r'class="result__a" href="([^"]+)"', r.text):
                    u = m.group(1)
                    if "uddg=" in u:
                        u = unquote(u.split("uddg=")[1].split("&")[0])
                    urls.append(u)
        time.sleep(1.0)
    out = []
    for u in urls:
        if u.startswith("http") and u not in out and not any(x in u for x in ("youtube.com", "amazon.", "pinterest", "facebook", "wikipedia.org", "reddit.com")):
            out.append(u)
    return out


def _web_texts(title, author, max_pages=14):
    import trafilatura
    urls = _search_urls([f'"{title}" {author} book summary key ideas', f"{title} {author} chapter by chapter summary",
                         f"{title} {author} lessons takeaways", f"{title} {author} review"])
    texts = []
    for u in urls[:max_pages * 2]:
        if len(texts) >= max_pages:
            break
        try:
            raw = trafilatura.fetch_url(u)
            txt = trafilatura.extract(raw) if raw else None
            if txt and len(txt) > 800:
                texts.append(txt)
        except Exception:
            pass
    return texts


# ------------------------------------------------------------------ cover
def _download_cover(urls, dest):
    best = None
    for u in urls:
        r = _get(u.replace("http://", "https://"))
        if not r:
            continue
        try:
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(r.content)
            im = Image.open(tmp)
            if im.height >= 300 and im.height / im.width > 1.15 and (not best or im.height > best[0]):
                best = (im.height, r.content)
        except Exception:
            continue
    if best:
        dest.write_bytes(best[1])
        return dest
    return None


def _fallback_cover(title, author, dest):
    from editor import find_font
    from PIL import ImageFont
    im = Image.new("RGB", (800, 1200), (28, 32, 48))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(find_font("serif_bold")[0], 84)
    y = 380
    for line in re.findall(r".{1,16}(?:\s|$)", title) or [title]:
        d.text((400, y), line.strip(), font=f, fill=(240, 235, 225), anchor="mm")
        y += 100
    d.text((400, 1050), author.upper(), font=ImageFont.truetype(find_font("sans_bold")[0], 44), fill=(200, 170, 90), anchor="mm")
    im.save(dest)
    return dest


# ------------------------------------------------------------------ category
CAT_RULES = [
    ("Business & Money", "business econom financ invest money entrepreneur marketing startup wealth sales negotiat"),
    ("Psychology & Mind", "psycholog cognit mind behavio neuro bias emotion"),
    ("Productivity & Habits", "habit productiv focus procrastinat routine discipline"),
    ("Leadership & Management", "leader manage team organiz strategy"),
    ("History & Politics", "histor politic war empire civiliz govern"),
    ("Science & Technology", "science technolog physics biolog evolution comput universe"),
    ("Philosophy & Wisdom", "philosoph stoic ethic wisdom virtue"),
    ("Health & Wellness", "health sleep fitness nutrition wellness medic"),
    ("Biography & Memoir", "biograph memoir autobiograph"),
    ("Fiction & Literature", "fiction novel literary poetry dystopia"),
    ("Relationships & Communication", "relationship communicat love friend social"),
    ("Parenting & Education", "parent education child teach learn"),
    ("Spirituality", "spiritual religio meditat mindful soul"),
]


def map_category(hay):
    hay = hay.lower()
    scores = {cat: sum(hay.count(k) for k in kws.split()) for cat, kws in CAT_RULES}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Self-Improvement"


# ------------------------------------------------------------------ main research
def research_light(book, workdir):
    """Metadata + cover only (fast). Used for Shorts when the deep research is already stored in the brain."""
    title, author = short_title(book["title"]), book.get("author", "")
    nt = brain.norm_title(title)
    gv = [v for v in _google_volumes(title, author, 8) if _edition_ok(v) and _ratio(nt, brain.norm_title(v.get("title", ""))) >= 0.88]
    gb = max(gv, key=lambda v: (bool(v.get("imageLinks")), bool(v.get("description")), -len(v.get("title", "")))) if gv else {}
    ol = (_openlibrary_docs(title, author, 3) or [{}])[0]
    author = author or (gb.get("authors") or ol.get("author_name") or [""])[0]
    desc = _clean(gb.get("description", ""))
    if len(desc) < 150 and ol.get("key"):
        r = _get(f"https://openlibrary.org{ol['key']}.json")
        if r:
            dd = r.json().get("description", "")
            desc = _clean(dd.get("value", "") if isinstance(dd, dict) else dd)
    cover_urls = []
    il = gb.get("imageLinks", {})
    for k in ("extraLarge", "large", "medium", "thumbnail"):
        if il.get(k):
            cover_urls.append(il[k].replace("&edge=curl", "").replace("zoom=1", "zoom=0"))
    if ol.get("cover_i"):
        cover_urls.append(f"https://covers.openlibrary.org/b/id/{ol['cover_i']}-L.jpg")
    cover = _download_cover(cover_urls, workdir / "cover.jpg") or _fallback_cover(title, author, workdir / "cover.jpg")
    categories = list(gb.get("categories") or []) + list(ol.get("subject", [])[:8])
    return dict(title=title, subtitle=gb.get("subtitle", ""), author=author, description=desc, pages=gb.get("pageCount"),
                published=gb.get("publishedDate", ""), cover=str(cover), categories=categories,
                book_wiki={"intro": "", "sections": {}}, author_wiki={"intro": "", "sections": {}}, concepts=[], web_pages=0,
                category=map_category(" ".join(categories) + " " + desc))


def research(book, workdir):
    d = research_light(book, workdir)
    title, author = d["title"], d["author"]
    bp = _find_book_page(title, author)
    d["book_wiki"] = _wiki_full(bp) if bp else {"intro": "", "sections": {}}
    ap = _find_author_page(author)
    d["author_wiki"] = _wiki_full(ap) if ap else {"intro": "", "sections": {}}
    texts = _web_texts(title, author)
    pool = texts + [d["book_wiki"]["intro"] + " " + " ".join(d["book_wiki"]["sections"].values()), d["description"]]
    exclude = [w for w in re.findall(r"[a-z]{4,}", f"{title} {author}".lower())] + ["book", "author", "chapter"]
    d["concepts"] = mine_concepts(bp, pool, exclude)
    d["web_pages"] = len(texts)
    d["web_texts"] = texts
    d["category"] = map_category(" ".join(d["categories"]) + " " + d["description"] + " " + " ".join(c["term"] for c in d["concepts"]))
    print(f"[research] {title} / {author}: wiki={'yes' if bp else 'no'} web_pages={len(texts)} "
          f"concepts={[c['term'] for c in d['concepts']]} category={d['category']}")
    return d
