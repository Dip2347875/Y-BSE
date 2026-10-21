"""Central settings. Secrets come from environment variables / GitHub Secrets. No AI API key is needed:
the AI model runs locally on the machine (free, open-source)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK, OUT = ROOT / "work", ROOT / "output"
ASSETS = ROOT / "assets"
FONTS, MUSIC = ASSETS / "fonts", ASSETS / "music"
STATE_FILE = ROOT / "state" / "state.json"
for _p in (WORK, OUT, FONTS, MUSIC, STATE_FILE.parent):
    _p.mkdir(parents=True, exist_ok=True)


def env(name, default=""):
    return os.getenv(name, default).strip()


# ---- sources -------------------------------------------------------------
RSS_FEEDS = [u.strip() for u in env(
    "BOOK_RSS_FEEDS",
    "https://rss.nytimes.com/services/xml/rss/nyt/Books.xml,"
    "https://www.theguardian.com/books/rss,"
    "https://www.goodreads.com/blog/list_rss.xml").split(",") if u.strip()]
PEXELS_KEY, PIXABAY_KEY = env("PEXELS_API_KEY"), env("PIXABAY_API_KEY")
PEXELS_BUDGET = int(env("PEXELS_BUDGET", "150"))        # Pexels allows ~200 requests / hour

# ---- voice: MALE only (free Microsoft neural voices). Other clear male choices:
#      en-GB-RyanNeural, en-US-GuyNeural, en-US-EricNeural -------------------
VOICE = env("EDGE_VOICE", "en-US-ChristopherNeural")
RATE, PITCH = env("TTS_RATE", "-3%"), env("TTS_PITCH", "+0Hz")

# ---- video formats -------------------------------------------------------
LONG = dict(W=1920, H=1080, fps=24, chunk_words=34, max_words=48)
SHORT = dict(W=1080, H=1920, fps=30, target_seconds=55, chunk_words=12, max_words=18)
RENDER_WORKERS = int(env("RENDER_WORKERS", "2"))
FFMPEG_THREADS = env("FFMPEG_THREADS", "2")

# ---- long video length: narration runs ~143 words per minute -------------
LONG_MIN_WORDS = int(env("LONG_MIN_WORDS", "15200"))        # about 1h46m
LONG_TARGET_WORDS = int(env("LONG_TARGET_WORDS", "16200"))  # about 1h53m
LONG_MAX_WORDS = int(env("LONG_MAX_WORDS", "17000"))        # about 1h59m
MIN_WORDS_LONG = int(env("MIN_WORDS_LONG", "1200"))         # only for the no-AI template fallback

# ---- local AI (llama.cpp, free, runs on the CPU of the runner) -----------
AI_BUDGET_MIN = int(env("AI_BUDGET_MIN", "230"))            # minutes the AI stage may use
AI_CTX = int(env("AI_CTX", "8192"))
MAX_NOTE_CHUNKS = int(env("MAX_NOTE_CHUNKS", "40"))
MIN_SOURCE_WORDS = int(env("MIN_SOURCE_WORDS", "6000"))     # not enough research material -> pick another book
_custom = env("LOCAL_MODEL")                                # optional "repo::file.gguf"
AI_MODELS = ([tuple(_custom.split("::", 1))] if "::" in _custom else []) + [
    ("bartowski/Phi-3.5-mini-instruct-GGUF", "Phi-3.5-mini-instruct-Q4_K_M.gguf"),
    ("microsoft/Phi-3-mini-4k-instruct-gguf", "Phi-3-mini-4k-instruct-q4.gguf"),
]

# ---- schedule (local hour of your audience / yourself) -------------------
SLOT_TZ_OFFSET = float(env("SLOT_TZ_OFFSET", "6"))      # 6 = Bangladesh (UTC+6)
SHORT_SLOTS = (6, 18)                                    # 6 AM, 6 PM
LONG_SLOTS = (0, 12)                                     # 12 AM, 12 PM

CATEGORIES = ["Self-Improvement", "Business & Money", "Psychology & Mind", "Productivity & Habits",
              "Leadership & Management", "History & Politics", "Science & Technology",
              "Philosophy & Wisdom", "Health & Wellness", "Biography & Memoir",
              "Fiction & Literature", "Relationships & Communication", "Parenting & Education",
              "Spirituality"]
