"""Deep analysis + original script writing with the LOCAL AI.
Stage 1  read the raw sources in chunks and write research notes (own words)
Stage 2  plan a chapter outline that covers the whole book
Stage 3  write every chapter from its notes; a similarity guard rewrites anything that is too close to the sources."""
import math, random, re
import config, local_ai

SYS = ("You are an award-winning narrator and writer of long-form audiobook explainers. You write warm, intelligent, vivid "
       "spoken prose that keeps listeners thinking.")
RULES = ("Write ONLY flowing spoken narration: no headings, no bullet points, no numbered lists, no stage directions, no chapter "
         "labels, no phrases like 'in this video' or 'in this chapter'. Speak to the listener as 'you' where natural. Use the "
         "research notes for every fact about the book. You may add plain-language explanation, analogies and clearly "
         "hypothetical everyday scenarios, but NEVER invent quotes, statistics, studies, names or events. Put every idea in your "
         "own fresh words and never reuse phrasing from the notes. Keep paragraphs under 70 words and vary sentence length.")
STOP = set("the a an and or but if of to in on at for with as is are was were be been it this that these those you your they "
           "their we our he she his her not no so than then there here from by about into over just very more most can could "
           "will would should have has had do does did what which who how why when also book author".split())

GENERIC_CHAPTERS = [
    ("Why This Book Matters", "the problem the book tackles and why it still matters today"),
    ("The Core Idea", "the central thesis explained in simple language"),
    ("How We Usually Get It Wrong", "common habits of thinking that the book challenges"),
    ("The Framework Behind It", "the structure or method the author proposes"),
    ("A Closer Look At The Evidence", "the reasoning, research and examples used to support the argument"),
    ("Stories That Make It Real", "memorable examples and cases from the book and its sources"),
    ("Putting It Into Practice", "practical steps a listener can start using this week"),
    ("Obstacles Along The Way", "what makes the ideas hard to apply and how to overcome that"),
    ("What Critics Say", "limits, objections and balanced criticism of the book"),
    ("Connecting The Dots", "how the individual ideas combine into one picture"),
    ("The Mindset Shift", "the deeper change in thinking the book invites"),
    ("Daily Habits That Help", "small repeatable routines that put the ideas to work"),
    ("Lessons For Work And Life", "how the ideas apply to career, money, relationships and growth"),
    ("The Bigger Picture", "where the book sits among other important ideas"),
    ("Questions Worth Asking Yourself", "reflective questions that make the lessons personal"),
    ("What To Remember", "the handful of ideas that matter most"),
    ("Common Mistakes", "ways readers misunderstand or misuse the ideas"),
]
EXTRA_TOPICS = [
    ("Misconceptions Worth Clearing Up", "popular misunderstandings about the book and its ideas"),
    ("A Thirty Day Practice Plan", "a simple week-by-week way to apply the lessons"),
    ("Imagined Scenarios", "clearly hypothetical everyday situations that show the ideas working"),
    ("When The Ideas Do Not Apply", "situations where the advice needs adjusting"),
    ("How To Teach These Ideas To Others", "explaining the key lessons simply to a friend or team"),
    ("Measuring Your Progress", "simple ways to notice whether the ideas are changing your results"),
    ("A Deeper Reflection", "the emotional and personal side of the book's message"),
    ("Long Term Thinking", "how the lessons compound over years"),
]


def wc(t):
    return len(t.split())


def tokens(t):
    return {w for w in re.findall(r"[a-z]{4,}", t.lower()) if w not in STOP}


def short_title(t):
    return " ".join(re.sub(r"[^\w\s'-]", "", t).split()[:6]).strip() or "Next Idea"


# ------------------------------------------------------------------ text hygiene
def clean_narration(t):
    t = re.sub(r"\*+|#+|_{2,}", "", t)
    t = re.sub(r"\b[Ii]n this (video|chapter|section|part|episode|talk),?\s*", "", t)
    lines = []
    for ln in t.splitlines():
        s = ln.strip()
        if not s:
            lines.append("")
            continue
        if re.match(r"^(chapter|section|part|narrator|host|voice ?over|title|note)\b[^.]{0,50}[:\-]", s, re.I):
            continue
        if re.match(r"^[\[\(].{0,80}[\]\)]$", s):
            continue
        s = re.sub(r"^([-\u2022]|\d+[.)])\s+", "", s)
        lines.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def dedupe_sentences(text):
    seen, out = set(), []
    for para in re.split(r"\n\s*\n", text):
        keep = []
        for s in re.split(r"(?<=[.!?])\s+", para.strip()):
            k = re.sub(r"\W+", " ", s.lower()).strip()
            if len(k) > 25 and k in seen:
                continue
            seen.add(k)
            keep.append(s)
        if keep:
            out.append(" ".join(keep))
    return "\n\n".join(out)


class Guard:
    """Measures how many 7-word sequences of a text also appear in the research sources."""
    def __init__(self, texts, n=7):
        self.n, self.grams = n, set()
        for t in texts:
            w = re.findall(r"[a-z0-9']+", t.lower())
            for i in range(len(w) - n + 1):
                self.grams.add(hash(" ".join(w[i:i + n])))

    def overlap(self, text):
        w = re.findall(r"[a-z0-9']+", text.lower())
        total = len(w) - self.n + 1
        if total <= 0:
            return 0.0
        return sum(1 for i in range(total) if hash(" ".join(w[i:i + self.n])) in self.grams) / total


# ------------------------------------------------------------------ stage 1: notes
def chunk_words(text, size=700):
    w = text.split()
    return [" ".join(w[i:i + size]) for i in range(0, len(w), size) if len(w[i:i + size]) > 120]


def pick_chunks(sources, limit):
    caps = {"wiki": 4, "video": 4, "web": 3, "book": 8, "pdf": 5}
    per = []
    for s in sources:
        ch = chunk_words(s["text"])
        cap = caps.get(s["kind"], 3)
        if len(ch) > cap:
            step = len(ch) / cap
            ch = [ch[int(i * step)] for i in range(cap)]
        per.append((s, ch))
    out, i = [], 0
    longest = max((len(ch) for _, ch in per), default=0)
    while len(out) < limit and i < longest:
        for s, ch in per:
            if i < len(ch) and len(out) < limit:
                out.append((s, ch[i]))
        i += 1
    return out


def extract_notes(d, chunk):
    prompt = (f"Book: '{d['title']}' by {d['author']}.\nBelow is an excerpt from a source about this book or its subject. "
              "List the distinct ideas, arguments, frameworks, stories, examples, facts and practical advice it contains. "
              "Write 5 to 9 short bullet notes in YOUR OWN WORDS (never copy phrases). Each note is one clear sentence. "
              "Only use information found in the excerpt. Start every note with '- '.\n\nEXCERPT:\n" + chunk)
    out = local_ai.chat(prompt, system="You are a careful research analyst.", max_tokens=450, temperature=0.3)
    notes = [re.sub(r"^[-\u2022*]\s*", "", ln).strip() for ln in out.splitlines() if ln.strip()[:1] in "-\u2022*"]
    return [n for n in notes if 25 <= len(n) <= 320]


def dedupe_notes(notes):
    kept, sets = [], []
    for n in notes:
        t = tokens(n["note"])
        if not t or any(len(t & s) / max(len(t | s), 1) > 0.6 for s in sets):
            continue
        kept.append(n)
        sets.append(t)
    return kept


def build_notes(d, sources, log):
    picks = pick_chunks(sources, config.MAX_NOTE_CHUNKS)
    notes = []
    for n, (s, chunk) in enumerate(picks, 1):
        if local_ai.time_left() < local_ai.budget_total() * 0.55:
            log("[notes] research time share used up - moving on")
            break
        for g in extract_notes(d, chunk):
            notes.append(dict(note=g, src=s["kind"]))
        if n % 5 == 0:
            log(f"[notes] {n}/{len(picks)} excerpts read, {len(notes)} notes")
    notes = dedupe_notes(notes)
    log(f"[notes] {len(notes)} unique notes")
    return notes


# ------------------------------------------------------------------ stage 2: outline
def make_outline(d, notes, n, log):
    sample = "\n".join(f"- {x['note']}" for x in notes[:70])
    prompt = (f"Plan a long audiobook-style explainer about '{d['title']}' by {d['author']}.\nUsing the research notes, write exactly {n} "
              "chapter plans that cover the whole book in a logical order: the core thesis, each major idea or framework, key "
              "stories and examples, practical application, objections and limits. Give each chapter a short evocative title "
              "(2 to 6 words) and a one-sentence focus.\nFormat strictly: one chapter per line as `Title | focus`. No numbering, "
              "no extra text.\n\nNOTES:\n" + sample)
    out = local_ai.chat(prompt, system="You are a thoughtful book editor.", max_tokens=1000, temperature=0.5)
    plan = []
    for ln in out.splitlines():
        if "|" in ln:
            t, f = ln.split("|", 1)
            t = re.sub(r"^[\s\d.)\-*]+|[`*\"]", "", t).strip()
            if 2 <= len(t) <= 70 and len(f.strip()) > 8:
                plan.append(dict(title=short_title(t), focus=f.strip().strip("`")))
    seen = {p["title"].lower() for p in plan}
    for t, f in GENERIC_CHAPTERS:
        if len(plan) >= n:
            break
        if t.lower() not in seen:
            plan.append(dict(title=t, focus=f))
    log(f"[outline] {len(plan[:n])} chapters: {[p['title'] for p in plan[:n]]}")
    return plan[:n]


def assign_notes(plan, notes, per=11):
    use = {i: 0 for i in range(len(notes))}
    nt = [tokens(n["note"]) for n in notes]
    out = []
    for ch in plan:
        want = tokens(ch["title"] + " " + ch["focus"])
        scored = sorted(range(len(notes)), key=lambda i: -(len(want & nt[i]) * 2 - use[i] * 3 + random.random()))
        pick = scored[:per]
        for i in pick:
            use[i] += 1
        out.append([notes[i]["note"] for i in pick])
    return out


# ------------------------------------------------------------------ stage 3: writing
def generate(d, brief, notes, prev_tail, target, guard, log):
    block = "\n".join("- " + n for n in notes)
    base = (f"{RULES}\n\nBOOK: '{d['title']}' by {d['author']}\nTHIS PART: {brief}\n\n"
            f"RESEARCH NOTES (use these for facts about the book):\n{block}\n")
    if prev_tail:
        base += f"\nThe narration so far ended with: \"{prev_tail}\"\nContinue smoothly from there without recapping.\n"
    text = clean_narration(local_ai.chat(base + f"\nWrite about {target} words of narration for this part now. Begin directly "
                                         "with the narration.", system=SYS, max_tokens=min(int(target * 1.9) + 200, 1900)))
    tries = 0
    while wc(text) < target * 0.85 and tries < 3 and local_ai.time_left() > 600:
        tail = " ".join(text.split()[-200:])
        more = local_ai.chat(f"{RULES}\n\nBOOK: '{d['title']}' by {d['author']}\nTHIS PART: {brief}\n\nHere is the narration so far:\n"
                             f"\"{tail}\"\n\nContinue it smoothly for about 400 more words with NEW explanation, a concrete everyday "
                             f"example and a practical takeaway. Do not repeat earlier sentences and do not wrap up the whole talk.",
                             system=SYS, max_tokens=800)
        text = text + "\n\n" + clean_narration(more)
        tries += 1
    text = dedupe_sentences(text)
    if wc(text) > target * 1.35:  # a chatty model must not blow the 2-hour limit: keep whole paragraphs only
        kept, n = [], 0
        for p in text.split("\n\n"):
            if kept and n + wc(p) > target * 1.25:
                break
            kept.append(p)
            n += wc(p)
        text = "\n\n".join(kept)
    if guard.overlap(text) > 0.05 and local_ai.time_left() > 400:
        log("[guard] text too close to the sources - rewriting in fresh words")
        again = clean_narration(local_ai.chat(
            "Rewrite the narration below completely in new words and a new sentence structure. Keep the meaning, keep the length, "
            "keep it spoken and flowing, and add nothing that is not already in it.\n\n" + text, system=SYS,
            max_tokens=min(int(wc(text) * 1.7) + 100, 2000), temperature=0.85))
        if wc(again) > wc(text) * 0.6:
            text = dedupe_sentences(again)
    return text


def tail_of(text, n=45):
    return " ".join(text.split()[-n:])


def write_long(d, sources, log=print):
    guard = Guard([s["text"] for s in sources])
    notes = build_notes(d, sources, log)
    if len(notes) < 25:
        log("[ai] too few notes to write a long script")
        return None
    n = max(10, math.ceil((config.LONG_TARGET_WORDS - 850) / 950))
    plan = make_outline(d, notes, n, log)
    assigned = assign_notes(plan, notes)
    per = max(700, min(int((config.LONG_TARGET_WORDS - 850) / len(plan)), 1100))

    secs = [dict(title="Introduction", text=generate(
        d, "COLD OPEN. Begin with a gripping question or scene that creates curiosity about the book's central problem, then "
           "say what makes the book worth the listener's time and what they will walk away with. Do not greet the audience and "
           "do not announce a video.", [x["note"] for x in notes[:10]], "", 380, guard, log))]
    total = wc(secs[0]["text"])
    for i, (ch, nts) in enumerate(zip(plan, assigned), 1):
        if local_ai.time_left() < 900:
            log("[write] AI time budget almost used - stopping chapters here")
            break
        if total + per + 450 > config.LONG_MAX_WORDS:
            log("[write] reached the 2-hour length limit - stopping chapters here")
            break
        log(f"[write] chapter {i}/{len(plan)}: {ch['title']}  (total so far {total} words, {local_ai.time_left() / 60:.0f} min left)")
        txt = generate(d, f"{ch['title']} - {ch['focus']}", nts, tail_of(secs[-1]["text"]), per, guard, log)
        secs.append(dict(title=ch["title"], text=txt))
        total += wc(txt)
    extras = EXTRA_TOPICS[:]
    while total < config.LONG_MIN_WORDS and extras and local_ai.time_left() > 900 and total + per + 450 < config.LONG_MAX_WORDS:
        t, f = extras.pop(0)
        log(f"[write] extra chapter: {t}  (total {total} words)")
        idx = random.sample(range(len(notes)), min(10, len(notes)))
        txt = generate(d, f"{t} - {f}", [notes[i]["note"] for i in idx], tail_of(secs[-1]["text"]), per, guard, log)
        secs.append(dict(title=t, text=txt))
        total += wc(txt)
    secs.append(dict(title="Final Thoughts", text=generate(
        d, "FINAL SECTION. Bring the big ideas together, leave the listener with one challenge or question to act on this week, "
           "and finish with a memorable last line. Include one warm sentence inviting them to like, subscribe and share this "
           "with a friend who needs it.", [x["note"] for x in notes[:12]], tail_of(secs[-1]["text"]), 420, guard, log)))
    total += wc(secs[-1]["text"])
    log(f"[write] DONE: {len(secs)} sections, {total} words (~{total / 143:.0f} min of narration)")
    d["concepts"] = [dict(term=s["title"], text=" ".join(s["text"].split()[:230])) for s in secs[1:-1] if wc(s["text"]) > 150]
    return secs


def write_short(d, term, excerpt):
    prompt = (f"Write a YouTube Shorts narration of about 125 words (roughly 50 seconds) about ONE idea: {term}. It comes from the "
              f"book '{d['title']}' by {d['author']}. Base it on this material:\n{excerpt}\n\nStructure: a gripping first line, the "
              "idea explained simply with an everyday example, one surprising insight, and a last line that makes people want to "
              "replay it. Short punchy sentences. Mention the book once. " + RULES)
    text = clean_narration(local_ai.chat(prompt, system=SYS, max_tokens=420, temperature=0.8))
    return text if 70 <= wc(text) <= 200 else None
