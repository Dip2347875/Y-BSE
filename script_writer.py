"""Rule-based script composer (fallback) + scene director. The main script is written by analyst.py (local AI);
this file chunks the narration into scenes and decides how every scene looks."""
import itertools, random, re
import config

LAYOUTS = ["kinetic", "serif", "hero", "broll", "quote", "stat"]
STOP = set("the a an and or but if of to in on at for with as is are was were be been it this that these those you your "
           "they their we our he she his her not no so than then there here from by about into over just very more most "
           "can could will would should have has had do does did what which who how why when".split())

BRIDGES = ["Hold on to that thought.", "Here is where it gets interesting.", "Now think about what that means for you.",
           "That is the surface. Underneath, there is more.", "Stay with me here.", "This part matters.",
           "Let that sink in for a moment.", "And that changes the picture.", "Keep this in mind as we go on.",
           "Now, let us go one level deeper."]
HOOKS = ["What if the way you think about {topic} is quietly holding you back?",
         "Some books are worth far more than the hours it takes to read them. Let us find out why {title} keeps getting recommended.",
         "Most people never question {topic}. This book does, and that is exactly why it is worth your time.",
         "There is a reason {title} refuses to disappear from reading lists. Let us unpack it."]
CONCEPT_INTRO = ["One idea that keeps surfacing around {title} is {c}.", "Let us talk about {c}, because it sits close to the heart of this book.",
                 "There is a concept worth slowing down for: {c}.", "Here is an idea you will keep running into when you study {title}: {c}.",
                 "Another important thread is {c}.", "If you remember only one more idea from {title}, make it {c}."]
APPLY = ["Now ask yourself: where does {c} show up in your own life without you noticing? Most of us only see it after the fact.",
         "The real test of {c} is not understanding it today. It is catching yourself in the middle of it tomorrow.",
         "Try this for seven days: notice one moment where {c} shapes a choice you make, and write it down. Patterns appear fast.",
         "Understanding {c} is easy. Living by it is the hard part, and that gap is where growth happens.",
         "Think of one decision you are facing right now. How would it look if you took {c} seriously?",
         "The people who benefit most from {c} are not the smartest. They are the ones who actually apply it.",
         "Next time you feel certain about something, pause and ask how {c} might be bending your view.",
         "You do not need to master {c}. You only need to notice it a little more often than you do today."]
SHORT_HOOKS = ["Most people get {c} completely wrong.", "Stop scrolling. This one idea, {c}, is worth thirty seconds of your life.",
               "You have been ignoring {c}, and it quietly shapes your choices.", "Here is the idea behind {c} that nobody explains properly.",
               "Thirty seconds on {c}. It might change how you decide."]
SHORT_TURN = ["This idea keeps coming up around {title} by {author}.", "It is a core theme people connect with {title}, by {author}.",
              "You will find this thread running through {title}, by {author}."]
SHORT_INSIGHT = ["The next time it matters, pause, name it, and choose on purpose.", "Notice it once today and you will see it everywhere.",
                 "Awareness is the first step, and it costs you nothing.", "You do not need to be perfect. You need to notice more often."]
SHORT_CLOSE = ["Follow for one big idea from a great book, every day.", "Follow for more big ideas from books worth your time.",
               "Save this, and come back when it counts."]
WIKI_TITLES = {"Background": "Where This Book Came From", "Writing": "How It Was Written", "Publication history": "How It Reached Readers",
               "Publication": "How It Reached Readers", "Development": "How It Took Shape", "Overview": "The Big Picture",
               "Synopsis": "The Story in Brief", "Summary": "The Story in Brief", "Plot": "The Story in Brief",
               "Plot summary": "The Story in Brief", "Contents": "What Is Inside", "Content": "What Is Inside",
               "Themes": "The Themes That Run Through It", "Structure": "How It Is Built", "Style": "The Style",
               "Main ideas": "The Main Ideas", "Thesis": "The Central Thesis", "Premise": "The Premise"}
RECEPTION = ["Reception", "Critical reception", "Reviews", "Criticism", "Legacy", "Influence", "Impact", "Adaptations", "Awards"]
AUTHOR_SECS = ["Early life", "Life", "Biography", "Career", "Early life and education", "Personal life", "Life and career"]


def wc(t):
    return len(t.split())


def sentences(text):
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", text or "")
    text = re.sub(r"\s+", " ", text).replace(" ,", ",").replace(" .", ".")
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\u201c\u2018'])", text)
    return [s.strip() for s in parts if 35 <= len(s) <= 330 and not re.search(r"https?://|==", s)]


def take(sents, max_words):
    out, n = [], 0
    for s in sents:
        if out and n + wc(s) > max_words:
            break
        out.append(s)
        n += wc(s)
    return out


def paragraphs(sents, bridges, per=3):
    paras = []
    for i in range(0, len(sents), per):
        paras.append(" ".join(sents[i:i + per]))
        if i + per < len(sents) and len(paras) % 2 == 0:
            paras.append(next(bridges))
    return paras


def compose_long(d):
    rnd = random.Random(d["title"])
    title, author, concepts = d["title"], d["author"], d["concepts"]
    pool = BRIDGES[:]
    rnd.shuffle(pool)
    bridges = itertools.cycle(pool)
    topic = concepts[0]["term"].lower() if concepts else d["category"].lower()
    bw, aw = d["book_wiki"], d["author_wiki"]
    secs = []

    base = sentences(bw["intro"]) or sentences(d["description"])
    intro = [rnd.choice(HOOKS).format(title=title, author=author, topic=topic), " ".join(take(base, 80)),
             f"In this video we will unpack the big ideas inside {title}, get to know {author}, and turn what matters into "
             f"things you can actually use."]
    secs.append(dict(title="Introduction", text="\n\n".join(intro)))

    asents = sentences(aw["intro"])
    for name in AUTHOR_SECS:
        asents += sentences(aw["sections"].get(name, ""))
    if len(asents) >= 3:
        secs.append(dict(title=f"Meet {author}", text="\n\n".join(paragraphs(take(asents, 320), bridges))))

    for name, text in bw["sections"].items():
        if name in WIKI_TITLES and len(sentences(text)) >= 2:
            secs.append(dict(title=WIKI_TITLES[name], text="\n\n".join(paragraphs(take(sentences(text), 380), bridges))))
    if len(secs) <= 2 and d["description"]:
        secs.append(dict(title="What The Book Is About", text="\n\n".join(paragraphs(take(sentences(d["description"]), 200), bridges))))

    apply_pool = APPLY[:]
    rnd.shuffle(apply_pool)
    intro_pool = CONCEPT_INTRO[:]
    rnd.shuffle(intro_pool)
    for i, c in enumerate(concepts[:10]):
        body = take(sentences(c["text"]), 130)
        if not body:
            continue
        t = [intro_pool[i % len(intro_pool)].format(title=title, c=c["term"].lower()),
             " ".join(body), apply_pool[i % len(apply_pool)].format(c=c["term"].lower())]
        secs.append(dict(title=c["term"], text="\n\n".join(t)))

    rec = []
    for name in RECEPTION:
        rec += sentences(bw["sections"].get(name, ""))
    if len(rec) >= 3:
        secs.append(dict(title="How The World Reacted", text="\n\n".join(paragraphs(take(rec, 360), bridges))))

    names = [c["term"].lower() for c in concepts[:6]]
    recap = "Let us bring it together. " + (f"Along the way we met {', '.join(names[:-1])} and {names[-1]}." if len(names) > 1 else "")
    close = [recap.strip(), f"The honest way to use {title} is not to remember it. It is to pick one idea, apply it this week, and "
             f"see what changes.", "If this helped you, a like and a subscribe means a lot, and sharing it with one friend who "
             "needs it means even more. Thank you for spending your time here."]
    secs.append(dict(title="Final Thoughts", text="\n\n".join(close)))
    total = sum(wc(s["text"]) for s in secs)
    print(f"[script] {len(secs)} sections, {total} words (~{total / 150:.0f} min)")
    return secs if total >= config.MIN_WORDS_LONG else None


def compose_short(d, idx):
    rnd = random.Random(f"{d['title']}{idx}")
    title, author = d["title"], d["author"]
    cs = d["concepts"]
    if idx < len(cs):
        term, body = cs[idx]["term"], take(sentences(cs[idx]["text"]), 52)
    elif not cs and idx == 0 and d["description"]:
        term, body = title, take(sentences(d["description"]), 52)
    else:
        return None
    if not body:
        return None
    c = term.lower() if term != title else "this book"
    parts = [rnd.choice(SHORT_HOOKS).format(c=c), " ".join(body), rnd.choice(SHORT_TURN).format(title=title, author=author),
             rnd.choice(SHORT_INSIGHT), rnd.choice(SHORT_CLOSE)]
    return term, "\n\n".join(parts)


# ------------------------------------------------------------------ chunking
def chunk(text, target, maxw):
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        sents = re.split(r'(?<=[.!?])\s+(?=[A-Z"\u201c\u2018\'(\d])', re.sub(r"\s+", " ", para).strip())
        cur, n = [], 0
        for s in sents:
            w = wc(s)
            if cur and n + w > maxw:
                out.append([" ".join(cur), 0.25]); cur, n = [], 0
            cur.append(s); n += w
            if n >= target:
                out.append([" ".join(cur), 0.25]); cur, n = [], 0
        if cur:
            out.append([" ".join(cur), 0.25])
        if out:
            out[-1][1] = 0.55
    return out


# ------------------------------------------------------------------ rule-based art direction
VIS = {"decision": "crossroads path", "choice": "crossroads path", "risk": "poker chips table", "bet": "poker chips table",
       "money": "coins stack", "wealth": "coins stack", "invest": "stock market screen", "market": "stock market screen",
       "business": "office meeting", "success": "mountain summit", "fail": "broken glass", "mistake": "eraser pencil",
       "habit": "morning routine", "time": "hourglass clock", "mind": "human brain", "brain": "human brain",
       "think": "chess board", "learn": "student studying", "memory": "old photographs", "fear": "dark forest",
       "love": "couple sunset", "friend": "friends laughing", "family": "family dinner", "war": "soldiers silhouette",
       "history": "ancient ruins", "future": "city skyline night", "goal": "archery target", "focus": "lens focus macro",
       "write": "typewriter paper", "read": "open book library", "nature": "forest sunlight", "health": "running sunrise",
       "sleep": "bedroom night", "power": "chess king", "leader": "team meeting", "freedom": "open road",
       "death": "autumn leaves", "life": "sunrise mountains", "dream": "starry sky", "work": "desk laptop",
       "truth": "magnifying glass", "story": "campfire night", "change": "butterfly", "habits": "morning routine"}
CATQ = {"Self-Improvement": ["sunrise mountain", "person walking road", "journal pen coffee", "climbing rock"],
        "Business & Money": ["city skyline", "office desk", "coins stack", "handshake meeting"],
        "Psychology & Mind": ["human brain", "silhouette window", "fog forest", "chess pieces"],
        "Productivity & Habits": ["morning routine", "desk planner", "alarm clock", "running shoes"],
        "Leadership & Management": ["team meeting", "chess king", "mountain climbers", "conference room"],
        "History & Politics": ["ancient ruins", "old map", "parliament building", "old library"],
        "Science & Technology": ["laboratory", "stars galaxy", "circuit board", "telescope"],
        "Philosophy & Wisdom": ["marble statue", "old books", "misty mountain", "candle dark"],
        "Health & Wellness": ["yoga sunrise", "healthy food", "running trail", "meditation"],
        "Biography & Memoir": ["old photographs", "vintage typewriter", "road trip", "letters desk"],
        "Fiction & Literature": ["open book", "library shelves", "rainy window", "old bookstore"],
        "Relationships & Communication": ["friends talking", "couple walking", "coffee conversation", "hands holding"],
        "Parenting & Education": ["classroom", "child reading", "school desk", "family park"],
        "Spirituality": ["temple sunrise", "meditation", "candle light", "calm lake"]}
PATTERN = ["kinetic", "hero", "serif", "hero", "broll", "kinetic", "serif", "hero"]
THEMES = ["cream", "white", "grey", "cream"]


def _kw(text):
    ws = [re.sub(r"[^a-z]", "", w.lower()) for w in text.split()]
    return [w for w in ws if len(w) > 3 and w not in STOP]


def direct(chunks, d, mode="long"):
    out, prev, i_pat = [], "", 0
    cats = CATQ.get(d["category"], CATQ["Self-Improvement"])
    for i, c in enumerate(chunks):
        text, kws = c["text"], _kw(c["text"])
        quote = re.search(r"[\u201c\"]([^\u201d\"]{25,})[\u201d\"]", text)
        num = re.search(r"\b\d[\d,.]*%?", text)
        if quote and prev != "quote":
            lay = "quote"
        elif num and len(num.group(0)) <= 7 and prev != "stat" and i % 3 == 0:
            lay = "stat"
        else:
            lay = PATTERN[i_pat % len(PATTERN)]
            i_pat += 1
            if lay == prev:
                lay = "kinetic" if prev != "kinetic" else "serif"
        q = next((v for w in kws for k, v in VIS.items() if w.startswith(k)), cats[i % len(cats)])
        emph = sorted(set(kws), key=len, reverse=True)[:2]
        x = dict(layout=lay, theme=THEMES[i % 4], emphasis=emph, query=q, alt_query=cats[(i + 1) % len(cats)],
                 media="none", motion=["zoom_in", "zoom_out", "pan_left", "pan_right"][i % 4],
                 big_text=num.group(0) if lay == "stat" and num else "")
        if lay in ("hero", "broll"):
            x["media"] = "video" if (lay == "broll" and i % 3 == 0) else "photo"
        if lay == "broll":
            x["theme"] = "ink"
        if lay == "quote" or (lay == "stat" and i % 2):
            x["theme"] = "ink" if i % 2 else "cream"
        prev = lay
        out.append(x)
    return out


def build_scenes(sections, d, mode="long", log=print):
    cfg = config.LONG if mode == "long" else config.SHORT
    chunks = []
    for si, s in enumerate(sections):
        for text, pause in chunk(s["text"], cfg["chunk_words"], cfg["max_words"]):
            chunks.append(dict(text=text, pause=pause, chapter=s["title"], section=si))
    dirs = direct(chunks, d, mode)
    scenes, sid, last_sec = [], 0, -1
    for c, x in zip(chunks, dirs):
        if mode == "long" and c["section"] != last_sec and 0 < c["section"] < len(sections):
            scenes.append(dict(id=sid, kind="chapter", narration="", number=f"{c['section']:02d}", display_text=c["chapter"],
                               layout="chapter", theme="ink" if c["section"] % 2 else "cream", chapter=c["chapter"], pause=3.2,
                               emphasis=[], query="", media="none", motion="zoom_in"))
            sid += 1
        last_sec = c["section"]
        scenes.append(dict(id=sid, kind="narr", narration=c["text"], pause=c["pause"], chapter=c["chapter"], **x))
        sid += 1
    first = next(s for s in scenes if s["kind"] == "narr")
    first.update(layout="cover", media="none", theme="ink")
    scenes[-1].update(layout="cover", media="none", theme="cream")
    return scenes
