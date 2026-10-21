"""Download free fonts (Anton, Playfair Display, Montserrat). Best-effort; system fonts are the fallback."""
import requests, config
BASE = "https://github.com/google/fonts/raw/main/ofl/"
FILES = {"Anton-Regular.ttf": "anton/Anton-Regular.ttf",
         "PlayfairDisplay-Bold.ttf": "playfairdisplay/static/PlayfairDisplay-Bold.ttf",
         "PlayfairDisplay-Italic.ttf": "playfairdisplay/static/PlayfairDisplay-Italic.ttf",
         "Montserrat-Bold.ttf": "montserrat/static/Montserrat-Bold.ttf"}
for name, path in FILES.items():
    dest = config.FONTS / name
    if dest.exists():
        continue
    try:
        r = requests.get(BASE + path, timeout=60)
        if r.ok and len(r.content) > 20000:
            dest.write_bytes(r.content)
            print("font ok:", name)
        else:
            print("font skipped:", name, r.status_code)
    except Exception as e:
        print("font failed:", name, e)
