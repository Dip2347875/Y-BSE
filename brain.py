"""The 'brain': permanent memory of every book ever seen, so no book is ever repeated."""
import difflib, json, os, re, tempfile, time
import config

FILE = config.STATE_FILE.parent / "brain.json"
CLAIM_TTL = 12 * 3600


def norm_title(t):
    t = (t or "").lower()
    t = re.split(r"[:\u2013\u2014(]| - ", t)[0]
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\b(the|a|an)\b", " ", t)
    return " ".join(t.split())


def surname(a):
    parts = re.sub(r"[^A-Za-z \-']", " ", a or "").split()
    return parts[-1].lower() if parts else ""


def make_key(title, author=""):
    return re.sub(r"[^a-z0-9]+", "-", f"{norm_title(title)}-{surname(author)}").strip("-")[:80]


class Brain:
    def __init__(self):
        self.data = {"version": 2, "books": {}, "rss_seen": [], "playlists": {}}
        if FILE.exists():
            # never start fresh on a damaged file - that would forget the books and repeat them
            self.data.update(json.loads(FILE.read_text()))
        now = time.time()
        for b in self.books.values():
            if b["status"] == "claimed" and now - b.get("claimed_at", 0) > CLAIM_TTL:
                b["status"] = "failed"
                b["attempts"] = b.get("attempts", 0) + 1

    @property
    def books(self):
        return self.data["books"]

    def save(self):
        self.data["rss_seen"] = self.data["rss_seen"][-3000:]
        fd, tmp = tempfile.mkstemp(dir=FILE.parent)
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, FILE)

    # ---- lookup
    def find(self, title, author=""):
        n, s = norm_title(title), surname(author)
        if not n:
            return None
        for k, b in self.books.items():
            bn = b["norm"]
            same = n == bn or difflib.SequenceMatcher(None, n, bn).ratio() >= 0.9
            contained = s and s == b.get("surname") and min(len(n), len(bn)) >= 4 and (n in bn or bn in n)
            if same or contained:
                return k
        return None

    def is_blocked(self, title, author=""):
        k = self.find(title, author)
        if not k:
            return False
        b = self.books[k]
        if b["status"] == "failed" and b.get("attempts", 0) < 2:
            return False
        if b["status"] == "skipped" and time.time() > b.get("retry_at", 0):
            return False
        return True

    def seen_rss(self, rid):
        return rid in self.data["rss_seen"]

    def add_rss(self, rid):
        self.data["rss_seen"].append(rid)

    # ---- life cycle
    def claim(self, title, author=""):
        k = self.find(title, author) or make_key(title, author)
        b = self.books.setdefault(k, dict(title=title, author=author, norm=norm_title(title), surname=surname(author),
                                          status="new", attempts=0, concepts=[], shorts=[], long={}, first_seen=time.time()))
        if b["status"] != "done":
            b["status"] = "claimed"
            b["claimed_at"] = time.time()
        return k

    def set_concepts(self, k, terms):
        if terms:
            self.books[k]["concepts"] = terms

    def set_ideas(self, k, ideas):
        """ideas = [{'term':..., 'text':...}] - saved so later Shorts can reuse the deep research."""
        if ideas:
            self.books[k]["ideas"] = ideas
            self.books[k]["concepts"] = [i["term"] for i in ideas]

    def short_count(self, k):
        return len(self.books[k]["shorts"])

    def add_long(self, k, vid, category):
        b = self.books[k]
        b.update(status="done", category=category)
        b["long"] = dict(done=True, video_id=vid, at=time.time())

    def add_short(self, k, idea, vid):
        b = self.books[k]
        b.update(status="done")
        b["shorts"].append(dict(idea=idea, video_id=vid, at=time.time()))

    def mark_failed(self, k, err):
        b = self.books[k]
        if b["status"] != "done":
            b.update(status="failed", attempts=b.get("attempts", 0) + 1)
        b["last_error"] = str(err)[:300]

    def mark_skipped(self, k, reason):
        b = self.books[k]
        if b["status"] != "done":
            b["status"] = "skipped"
            b["retry_at"] = time.time() + 14 * 86400   # sources may improve later; try again in 2 weeks
        b["skip_reason"] = reason

    # ---- planning
    def books_needing_long(self):
        return [b for b in self.books.values() if b["status"] == "done" and not b["long"].get("done") and not b.get("skip_reason")]

    def books_for_shorts(self):
        out = [b for b in self.books.values() if b["status"] == "done" and len(b["shorts"]) < min(max(len(b["concepts"]), 1), 8)]
        return sorted(out, key=lambda b: len(b["shorts"]))
