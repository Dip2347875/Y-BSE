"""Rule-based SEO: title, description (NO links), tags, hashtags, thumbnail headline. No AI, no API."""
import hashlib, re
import config

URL_RE = re.compile(r"(https?://\S+|www\.\S+|\b[\w-]+\.(?:com|net|org|io|co|me|ly|tv|app|info|biz)(?:/\S*)?\b)", re.I)
GENERIC_TAGS = ["book summary", "book review", "book explained", "audiobook summary", "full book summary", "key takeaways",
                "book lessons", "best books", "books to read", "reading list", "self improvement books", "personal growth",
                "book recommendations", "learn from books", "nonfiction books", "bookish", "bookworm", "book club",
                "life lessons", "animated book summary"]
HEADLINES = [("THIS BOOK", "CHANGES EVERYTHING"), ("STOP", "IGNORING THIS"), ("READ THIS", "FIRST"), ("THE TRUTH", "ABOUT THIS"),
             ("WHY EVERYONE", "READS THIS"), ("YOU NEED", "THIS BOOK"), ("THE BIG", "IDEA"), ("THIS IS", "DANGEROUS")]


def strip_links(t):
    return re.sub(r"[ \t]{2,}", " ", URL_RE.sub("", t)).replace("<", "").replace(">", "")


def fmt_ts(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def camel(t):
    return re.sub(r"[^A-Za-z0-9]", "", t.title())


def _tags(tags, limit=480):
    out, n = [], 0
    for t in tags:
        t = re.sub(r"[<>]", "", str(t)).strip()
        cost = len(t) + (3 if " " in t else 1)
        if t and t.lower() not in [o.lower() for o in out] and n + cost <= limit:
            out.append(t)
            n += cost
    return out


def build(d, mode, chapters=None, idea=None):
    title, author, cat = d["title"], d["author"], d["category"]
    terms = [c["term"] for c in d["concepts"]]
    h = int(hashlib.md5(title.encode()).hexdigest(), 16)
    if mode == "long":
        options = [f"{title} by {author}: Full Book Summary & Key Lessons", f"{title} ({author}) - Book Summary, Big Ideas & Takeaways",
                   f"The Big Ideas in {title} by {author} (Full Explanation)"]
        if len(terms) >= 2:
            options.append(f"{title} Explained: {terms[0]}, {terms[1]} & More")
        title_out = next((o for o in options[h % len(options):] + options if len(o) <= 95), options[0][:95])
    else:
        title_out = f"{idea}: One Big Idea From {title} #Shorts"
        if len(title_out) > 95:
            title_out = f"{idea}: Big Idea From {title} #Shorts"[:95]
    ideas = ", ".join(terms[:4])
    parts = [f"{title} by {author}, explained."
             + (f" This video unpacks the book's major ideas, including {ideas}, and shows how to apply them in real life." if ideas
                else " This video unpacks the book's major ideas and shows how to apply them in real life."), ""]
    if mode == "long":
        parts += ["In this video you will learn:", f"\u2022 Who {author} is and why {title} matters"]
        parts += [f"\u2022 The idea of {t.lower()}" for t in terms[:6]]
        parts += [f"\u2022 How to put the lessons of {title} into practice", ""]
        if chapters:
            parts += ["Chapters:"] + [f"{fmt_ts(t)} {strip_links(n)}" for t, n in chapters] + [""]
        parts += ["This is an original educational commentary on the book. If the ideas resonate, read the full book, it goes "
                  "far deeper than any video can. Background information adapted from Wikipedia (CC BY-SA), Open Library and "
                  "Google Books.", ""]
    else:
        parts += [f"One big idea from {title}: {idea}.", ""]
    base_tags = ["Shorts"] if mode == "short" else []
    tags = _tags(base_tags + [title, f"{title} summary", f"{title} book summary", f"{title} {author}", author, f"{author} books",
                              f"{title} review", f"{title} explained", f"{title} key lessons", cat.lower()]
                 + terms + [f"{t.lower()} explained" for t in terms] + GENERIC_TAGS)
    hashtags = ["#" + x for x in ["BookSummary", "BookReview", camel(title)[:30], camel(author)[:30], camel(cat)]
                + [camel(t)[:24] for t in terms[:6]] + ["Books", "SelfImprovement", "Reading", "BookTube", "Learning"] if x]
    hashtags = list(dict.fromkeys(hashtags))[:15]
    if mode == "short":
        hashtags = ["#Shorts"] + [x for x in hashtags if x.lower() != "#shorts"][:11]
    parts.append(" ".join(hashtags))
    l1, l2 = HEADLINES[(h >> 8) % len(HEADLINES)]
    return dict(title=strip_links(title_out), description=strip_links("\n".join(parts))[:4900], tags=tags, category=cat, thumb=(l1, l2))


def chapter_marks(scenes):
    marks = [(0, "Introduction")]
    for s in scenes:
        if s.get("kind") == "chapter" and s["start"] - marks[-1][0] >= 10:
            marks.append((s["start"], s["display_text"]))
    return marks
