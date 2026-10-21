"""The 'human editor' engine: kinetic-typography scenes (animated ASS captions, floating photo cards,
Ken-Burns b-roll, stat/quote/chapter cards), rendered in parallel with FFmpeg, then audio mastered + muxed."""
import colorsys, functools, hashlib, math, random, subprocess, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
import config
from media_fetcher import Media

FONT_WANTS = {
    "display": ["Anton-Regular.ttf", "Montserrat-ExtraBold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "sans_bold": ["Montserrat-Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "serif_bold": ["PlayfairDisplay-Bold.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"],
    "serif_italic": ["PlayfairDisplay-Italic.ttf", "LiberationSerif-Italic.ttf", "DejaVuSerif-Italic.ttf"],
}


@functools.lru_cache(None)
def _all_fonts():
    found = {}
    for root in (config.FONTS, Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"):
        if root.exists():
            for p in root.rglob("*.ttf"):
                found.setdefault(p.name, p)
    return found


@functools.lru_cache(None)
def find_font(kind):
    fonts = _all_fonts()
    for name in FONT_WANTS[kind]:
        if name in fonts:
            fam, style = ImageFont.truetype(str(fonts[name]), 20).getname()
            return str(fonts[name]), fam, int("Bold" in style), int("Italic" in style or "Oblique" in style)
    if fonts:
        p = next(iter(fonts.values()))
        fam, style = ImageFont.truetype(str(p), 20).getname()
        return str(p), fam, 0, 0
    raise RuntimeError("No TTF fonts found - run setup_assets.py or install fonts-liberation")


THEMES = {"cream": dict(bg=(246, 241, 234), ink=(21, 21, 21), mute=(120, 115, 108), light=True),
          "white": dict(bg=(244, 244, 242), ink=(20, 20, 22), mute=(130, 130, 130), light=True),
          "grey": dict(bg=(226, 226, 224), ink=(24, 24, 26), mute=(110, 110, 110), light=True),
          "ink": dict(bg=(10, 10, 12), ink=(245, 245, 245), mute=(150, 150, 150), light=False)}


def accent_from_cover(path):
    im = Image.open(path).convert("RGB").resize((80, 80)).quantize(10, method=Image.Quantize.MEDIANCUT).convert("RGB")
    best, score = None, -1
    for cnt, rgb in im.getcolors(10000):
        h, s, v = colorsys.rgb_to_hsv(*[c / 255 for c in rgb])
        sc = s * (0.4 + v) * math.sqrt(cnt) * (0 if v < 0.25 else 1)
        if sc > score:
            best, score = (h, s, v), sc
    if not best or best[1] < 0.25:
        return (0, 196, 168)
    h, s, v = best
    r, g, b = colorsys.hsv_to_rgb(h, max(s, 0.65), max(v, 0.78))
    return int(r * 255), int(g * 255), int(b * 255)


def lum(c):
    f = lambda x: (x / 255 / 12.92) if x / 255 <= 0.03928 else (((x / 255) + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable(accent, bg):
    c = accent
    for _ in range(12):
        if contrast(c, bg) >= 3.2:
            break
        k = 0.88 if lum(bg) > 0.4 else 1.0
        c = tuple(int(x * k) if lum(bg) > 0.4 else int(x + (255 - x) * 0.15) for x in c)
    return c


def ass_col(c):
    return f"&H{c[2]:02X}{c[1]:02X}{c[0]:02X}&"


def ass_time(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def make_bg(ctx, theme, variant):
    p = ctx.dir / f"bg_{theme}_{variant}.png"
    if p.exists():
        return p
    W, H, th = ctx.W, ctx.H, THEMES[theme]
    rnd = random.Random(variant * 7 + len(theme))
    img = Image.new("RGB", (W, H), th["bg"])
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx, cy, r = rnd.randint(int(W * .2), int(W * .8)), rnd.randint(int(H * .2), int(H * .8)), int(min(W, H) * .6)
    ImageDraw.Draw(glow).ellipse([cx - r, cy - r, cx + r, cy + r],
                                 fill=(255, 255, 255, 90) if th["light"] else (*ctx.accent, 60))
    glow = glow.filter(ImageFilter.GaussianBlur(r // 2))
    img.paste(glow, (0, 0), glow)
    d = ImageDraw.Draw(img, "RGBA")
    step = int(min(W, H) / 13)
    x0, y0 = rnd.randint(0, step), rnd.randint(0, step)
    for gx in range(x0, W, step):
        for gy in range(y0, H, step):
            if (gx / W - .5) ** 2 + (gy / H - .5) ** 2 > .05:
                d.ellipse([gx - 2, gy - 2, gx + 2, gy + 2], fill=(*th["mute"], 70))
    ar = int(min(W, H) * rnd.uniform(.7, 1.1))
    ax, ay = rnd.choice([(-ar // 3, -ar // 3), (W - ar // 1.5, H - ar // 1.5), (W - ar // 1.5, -ar // 3)])
    d.arc([ax, ay, ax + ar, ay + ar], 0, 360, fill=(*th["mute"], 70), width=3)
    img.save(p)
    return p


def make_card(ctx, src, bw, bh, tag, contain=False, angle=0.0):
    p = ctx.dir / f"card_{tag}.png"
    im = Image.open(src).convert("RGB")
    if contain:
        im = ImageOps.contain(im, (bw, bh), Image.LANCZOS)
    else:
        im = ImageOps.fit(im, (bw, bh), Image.LANCZOS)
    im = ImageEnhance.Contrast(im).enhance(1.06)
    rad = max(10, min(im.size) // 22)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], rad, fill=255)
    pad = 70
    canvas = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 22, pad + im.width, pad + 22 + im.height], rad, fill=(0, 0, 0, 120))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)))
    canvas.paste(im, (pad, pad), mask)
    if angle:
        canvas = canvas.rotate(angle, resample=Image.BICUBIC, expand=True)
    canvas.save(p)
    return p, canvas.size


def fit_photo(ctx, src, scale=1.25):
    p = ctx.dir / f"fit_{hashlib.md5(str(src).encode()).hexdigest()[:10]}.jpg"
    if not p.exists():
        ImageOps.fit(Image.open(src).convert("RGB"), (int(ctx.W * scale), int(ctx.H * scale)), Image.LANCZOS).save(p, quality=92)
    return p


def make_gradient(ctx):
    p = ctx.dir / "grad.png"
    if not p.exists():
        g = Image.new("RGBA", (1, 256))
        for y in range(256):
            a = int(max(0, (y / 255 - .35) / .65) ** 1.4 * 200)
            g.putpixel((0, y), (0, 0, 0, a))
        g.resize((ctx.W, ctx.H)).save(p)
    return p


STOP = set("the a an and or but if of to in on at for with as is are was were be been it this that these those you your "
           "they their we our he she his her not no so than then there here from by about into just very more can will".split())


def norm(w):
    return "".join(ch for ch in w.lower() if ch.isalnum())


def make_phrases(words, max_chars, max_words=7):
    out, cur, n = [], [], 0
    for w in words:
        cur.append(w)
        n += len(w["w"]) + 1
        last = w["w"][-1:]
        if (last in ".!?" and len(cur) >= 2) or (last in ",;:" and n >= max_chars * .55) or n >= max_chars or len(cur) >= max_words:
            out.append(cur)
            cur, n = [], 0
    if cur:
        if out and len(cur) == 1:
            out[-1] += cur
        else:
            out.append(cur)
    return out


def wrap(words, font_path, size, max_w, max_lines=3):
    for _ in range(8):
        f = ImageFont.truetype(font_path, int(size))
        lines, cur = [], []
        for i, w in enumerate(words):
            trial = " ".join(x for _, x in cur + [(i, w)])
            if cur and f.getlength(trial) > max_w:
                lines.append(cur)
                cur = []
            cur.append((i, w))
        lines.append(cur)
        if len(lines) <= max_lines:
            break
        size *= .9
    return lines, int(size)


def build_ass(sc, ctx, th, accent, zone):
    W, H = ctx.W, ctx.H
    sans, serif, serif_it = find_font("sans_bold"), find_font("serif_bold"), find_font("serif_italic")
    disp = find_font("display")
    rows = [f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n",
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
            "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding"]
    for name, f in (("Sans", sans), ("Serif", serif), ("SerifIt", serif_it), ("Disp", disp)):
        rows.append(f"Style: {name},{f[1]},60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,{f[2]},{f[3]},0,0,100,100,0,0,1,0,0,5,0,0,0,1")
    rows.append("\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text")
    ev = lambda s, e, st, txt, layer=0: rows.append(f"Dialogue: {layer},{ass_time(s)},{ass_time(e)},{st},,0,0,0,,{txt}")
    dur = sc["dur"]
    lay = sc["layout"]
    ink = ass_col(zone["color"])
    acc = ass_col(zone["accent"])
    outline = f"\\bord{zone['outline']}\\3c&H000000&\\shad2" if zone["outline"] else "\\bord0\\shad0"

    if lay == "chapter":
        ev(0.1, dur, "Disp", f"{{\\an5\\pos({W // 2},{int(H * .42)})\\fs{int(H * .5)}\\1c{ink}\\alpha&HE8&\\fad(400,300)}}{sc['number']}")
        ev(0.35, dur, "Serif", f"{{\\an5\\pos({W // 2},{int(H * .50)})\\fs{int(H * .085)}\\1c{ink}\\fscx70\\fscy70\\alpha&HFF&"
                               f"\\t(0,350,\\fscx100\\fscy100\\alpha&H00&)\\fad(0,300)}}{sc['display_text']}")
        ev(0.6, dur, "Sans", f"{{\\an7\\pos({W // 2 - 150},{int(H * .60)})\\1c{acc}\\fscx0\\t(0,500,\\fscx100)\\fad(0,300)\\p1}}"
                             f"m 0 0 l 300 0 300 8 0 8{{\\p0}}")
        return "\n".join(rows)

    if lay == "stat" and sc.get("big_text"):
        ev(0.05, dur, "Disp", f"{{\\an5\\pos({W // 2},{int(H * (.36 if W > H else .32))})\\fs{int(H * (.24 if W > H else .15))}"
                              f"\\1c{acc}\\fscx60\\fscy60\\alpha&HFF&\\t(0,260,0.5,\\fscx100\\fscy100\\alpha&H00&)}}{sc['big_text']}")
    if lay == "quote":
        ev(0.0, dur, "Serif", f"{{\\an5\\pos({W // 2},{int(H * .22)})\\fs{int(H * .26)}\\1c{acc}\\alpha&H60&\\fad(300,0)}}\u201c")

    words = sc["words"]
    if not words:
        return "\n".join(rows)
    style = "Serif" if zone["serif"] else "Sans"
    phrases = make_phrases(words, zone["chars"])
    fpath = (serif if zone["serif"] else sans)[0]
    emph = {norm(e) for e in sc.get("emphasis", []) if e}
    for pi, ph in enumerate(phrases):
        texts = [w["w"] for w in ph]
        lines, size = wrap(texts, fpath, zone["size"], zone["max_w"])
        hi = {i for i, t in enumerate(texts) if norm(t) in emph}
        if not hi and sc["layout"] in ("kinetic", "serif", "hero", "quote", "stat"):
            cand = [(len(norm(t)), i) for i, t in enumerate(texts) if norm(t) not in STOP and len(norm(t)) > 3]
            if cand:
                hi = {max(cand)[1]}
        line_of = {i: li for li, ln in enumerate(lines) for i, _ in ln}
        p_start = max(ph[0]["t"] - 0.03, 0)
        p_end = (max(phrases[pi + 1][0]["t"] - 0.03, p_start + .2) if pi + 1 < len(phrases) else dur)
        for k in range(len(ph)):
            s = p_start if k == 0 else max(ph[k]["t"] - 0.03, p_start)
            e = (max(ph[k + 1]["t"] - 0.03, s + .05) if k + 1 < len(ph) else p_end)
            parts = []
            for j, t in enumerate(texts):
                is_h = j in hi
                if zone["serif"] and sc["layout"] == "quote":
                    it = "\\rSerifIt"
                elif zone["serif"] and not is_h:
                    it = "\\rSerifIt"
                elif zone["serif"] and is_h:
                    it = "\\rSerif"
                else:
                    it = "\\r" + style
                col = acc if is_h else ink
                fs = 108 if is_h else 100
                shown = t.upper() if (is_h and zone["serif"] and sc["layout"] == "serif") else t
                tag = f"{it}\\fs{size}\\1c{col}{outline}\\fscx{fs}\\fscy{fs}"
                if j > k:
                    tag += "\\alpha&HFF&"
                elif j == k:
                    tag += f"\\alpha&HFF&\\fscx60\\fscy60\\t(0,150,0.6,\\alpha&H00&\\fscx{fs}\\fscy{fs})"
                sep = ("\\N" if (j > 0 and line_of[j] != line_of[j - 1]) else (" " if j else ""))
                parts.append(f"{sep}{{{tag}}}{shown}")
            fade = "\\fad(90,0)" if k == 0 else ""
            ev(s, e, style, f"{{\\an{zone['an']}\\pos({zone['x']},{zone['y']}){fade}\\q2}}" + "".join(parts))
    return "\n".join(rows)


class Ctx:
    def __init__(self, cfg, d, wd, accent):
        self.W, self.H, self.fps = cfg["W"], cfg["H"], cfg["fps"]
        self.portrait = self.H > self.W
        self.dir = Path(wd)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.accent, self.cover = accent, d["cover"]
        self.media = Media(self.dir / "media")


def prepare_media(scenes, ctx, log=print):
    def work(sc):
        if sc["layout"] not in ("hero", "broll") or sc.get("media") == "none" or sc.get("asset"):
            return
        qs = [q for q in (sc.get("query"), sc.get("alt_query")) if q]
        if sc["layout"] == "broll" and sc.get("media") == "video":
            v = ctx.media.video(qs, ctx.portrait)
            if v:
                sc["asset"], sc["asset_kind"] = str(v), "video"
                return
        p = ctx.media.photo(qs, ctx.portrait)
        if p:
            sc["asset"], sc["asset_kind"] = str(p), "photo"
        else:
            log(f"[media] nothing for scene {sc['id']} ({qs}) -> typography")
            sc.update(layout="kinetic", media="none", theme="cream")
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(work, scenes))


def _zone(sc, ctx, th, accent_ok, side):
    W, H = ctx.W, ctx.H
    lay = sc["layout"]
    base = dict(color=th["ink"], accent=accent_ok, serif=lay in ("serif", "quote"), outline=0, an=5)
    if ctx.portrait:
        base.update(x=W // 2, max_w=int(W * .84), size=int(W * .098), chars=20)
        if lay in ("hero", "cover"):
            base.update(y=int(H * .76))
        elif lay == "broll":
            base.update(y=int(H * .80), color=(255, 255, 255), accent=(255, 214, 90), outline=4, size=int(W * .09))
        elif lay == "stat":
            base.update(y=int(H * .62), size=int(W * .08))
        else:
            base.update(y=int(H * .5))
    else:
        base.update(x=W // 2, y=H // 2, max_w=int(W * .72), size=int(H * .108), chars=28)
        if lay in ("hero", "cover"):
            base.update(an=4, size=int(H * .088), chars=18, max_w=int(W * .44),
                        x=int(W * .07) if side == "right" else int(W * .52), y=H // 2)
        elif lay == "broll":
            base.update(y=int(H * .84), color=(255, 255, 255), accent=(255, 214, 90), outline=4, size=int(H * .075),
                        max_w=int(W * .8), chars=38)
        elif lay == "stat":
            base.update(y=int(H * .70), size=int(H * .07))
    if lay == "broll":
        base.update(accent=(255, 214, 90))
    return base


def ease_x(x, dist, dur=.7):
    return f"{x}+({dist})*pow(max(0,1-t/{dur}),3)"


def render_scene(sc, ctx):
    out = ctx.dir / f"scene_{sc['id']:04d}.mp4"
    if out.exists() and out.stat().st_size > 1500:
        return out
    W, H, fps, N = ctx.W, ctx.H, ctx.fps, sc["frames"]
    th = THEMES[sc["theme"]]
    acc = readable(ctx.accent, th["bg"] if sc["layout"] != "broll" else (20, 20, 20))
    lay = sc["layout"]
    side = "right" if sc["id"] % 2 == 0 else "left"
    zone = _zone(sc, ctx, th, acc, side)
    ass = ctx.dir / f"scene_{sc['id']:04d}.ass"
    ass.write_text(build_ass(sc, ctx, th, acc, zone), encoding="utf-8")
    fonts = str(config.FONTS.resolve())
    asf = f"ass='{ass.name}':fontsdir='{fonts}'"
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    enc = ["-frames:v", str(N), "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-pix_fmt", "yuv420p", "-threads", config.FFMPEG_THREADS, "-an", str(out.name + ".part.mp4")]
    bg = make_bg(ctx, sc["theme"], sc["id"] % 5)

    if lay in ("hero", "cover"):
        if lay == "cover":
            if ctx.portrait:
                card, (cw, ch) = make_card(ctx, ctx.cover, int(W * .5), int(H * .42), f"cov{sc['id']}", True, -4)
                X, Y, dist = (W - cw) // 2, int(H * .08), 0
            else:
                card, (cw, ch) = make_card(ctx, ctx.cover, int(W * .30), int(H * .80), f"cov{sc['id']}", True, -4)
                X = int(W * .60) if side == "right" else int(W * .06)
                Y, dist = (H - ch) // 2, (W * .3 if side == "right" else -W * .3)
        elif ctx.portrait:
            card, (cw, ch) = make_card(ctx, sc["asset"], int(W * .82), int(H * .40), f"h{sc['id']}", False, 2 if sc["id"] % 2 else -2)
            X, Y, dist = (W - cw) // 2, int(H * .07), 0
        else:
            tall = sc["id"] % 3 != 0
            bw, bh = (int(W * .34), int(H * .76)) if tall else (int(W * .40), int(H * .56))
            card, (cw, ch) = make_card(ctx, sc["asset"], bw, bh, f"h{sc['id']}", False, (3 if sc["id"] % 2 else -3))
            X = int(W * .58) if side == "right" else int(W * .04)
            Y, dist = (H - ch) // 2, (W * .3 if side == "right" else -W * .3)
        xe = ease_x(X, dist) if dist else str(X)
        ye = f"{Y}+{6 if not ctx.portrait else 10}*sin(2*PI*t/3.6)" + ("" if dist else f"+{-int(H * .15)}*pow(max(0,1-t/0.7),3)")
        fc = f"[0:v][1:v]overlay=x='{xe}':y='{ye}':format=auto[o];[o]{asf}[v]"
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(bg), "-loop", "1", "-framerate", str(fps), "-i", str(card)]
    elif lay == "broll":
        grad = make_gradient(ctx)
        if sc.get("asset_kind") == "video":
            inputs = ["-stream_loop", "-1", "-ss", str(random.randint(0, 3)), "-i", sc["asset"], "-loop", "1", "-i", str(grad)]
            src = f"[0:v]fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        else:
            photo = fit_photo(ctx, sc["asset"])
            inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(photo), "-loop", "1", "-i", str(grad)]
            m = sc.get("motion", "zoom_in")
            z, x, y = {"zoom_in": (f"1+0.14*on/{N}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
                       "zoom_out": (f"1.14-0.14*on/{N}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
                       "pan_left": ("1.15", f"(iw-iw/zoom)*(1-on/{N})", "ih/2-(ih/zoom/2)"),
                       "pan_right": ("1.15", f"(iw-iw/zoom)*on/{N}", "ih/2-(ih/zoom/2)")}.get(m, ("1.1", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"))
            src = f"[0:v]zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={fps}"
        fc = f"{src},eq=brightness=-0.08:saturation=0.95,vignette=PI/5[z];[z][1:v]overlay=0:0:shortest=1[g];[g]{asf}[v]"
    else:
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(bg)]
        fc = f"[0:v]{asf}[v]"

    cmd = base + inputs + ["-filter_complex", fc, "-map", "[v]"] + enc
    r = subprocess.run(cmd, cwd=ctx.dir, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"scene {sc['id']} ({lay}) failed:\n{r.stderr[-1500:]}")
    (ctx.dir / (out.name + ".part.mp4")).rename(out)
    return out


def assign_frames(scenes, fps):
    t, prev = 0.0, 0
    for s in scenes:
        t += s["dur"]
        cur = round(t * fps)
        s["frames"] = max(cur - prev, 2)
        prev += s["frames"]


# Voice clarity chain: cut rumble, soften the boxy low-mids, lift the "presence" band that makes words crisp,
# then even out the loudness so quiet words are never lost.
VOICE_CHAIN = ("highpass=f=70,equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3200:t=q:w=1.1:g=2.5,"
               "acompressor=threshold=0.125:ratio=3:attack=8:release=120:makeup=2")


def master_audio(voice, out):
    tracks = sorted(config.MUSIC.glob("*.mp3")) + sorted(config.MUSIC.glob("*.wav")) + sorted(config.MUSIC.glob("*.m4a"))
    loud = "loudnorm=I=-16:TP=-1.5:LRA=9"
    if tracks:
        m = random.choice(tracks)
        fc = (f"[0:a]{VOICE_CHAIN},asplit=2[v1][v2];[1:a]volume=0.16[m];"
              f"[m][v1]sidechaincompress=threshold=0.035:ratio=10:attack=15:release=400[duck];"
              f"[v2][duck]amix=inputs=2:duration=first:normalize=0,{loud}[a]")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(voice), "-stream_loop", "-1", "-i", str(m),
               "-filter_complex", fc, "-map", "[a]", "-c:a", "aac", "-b:a", "192k", str(out)]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(voice), "-af", f"{VOICE_CHAIN},{loud}",
               "-c:a", "aac", "-b:a", "192k", str(out)]
    subprocess.run(cmd, check=True)


def render_video(scenes, d, wd, out_path, cfg, log=print):
    accent = accent_from_cover(d["cover"])
    ctx = Ctx(cfg, d, wd, accent)
    assign_frames(scenes, ctx.fps)
    log("[editor] fetching stock media ...")
    prepare_media(scenes, ctx, log)
    done, lock = [0], threading.Lock()

    def job(sc):
        render_scene(sc, ctx)
        with lock:
            done[0] += 1
            if done[0] % 25 == 0:
                log(f"[editor] rendered {done[0]}/{len(scenes)} scenes")

    log(f"[editor] rendering {len(scenes)} scenes with {config.RENDER_WORKERS} workers ...")
    with ThreadPoolExecutor(config.RENDER_WORKERS) as ex:
        list(ex.map(job, scenes))

    wd = Path(wd)
    (wd / "v.txt").write_text("".join(f"file 'scene_{s['id']:04d}.mp4'\n" for s in scenes))
    (wd / "a.txt").write_text("".join(f"file '{Path(s['audio']).resolve()}'\n" for s in scenes))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "v.txt",
                    "-c", "copy", "video_only.mp4"], cwd=wd, check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "a.txt",
                    "-c", "copy", "voice.wav"], cwd=wd, check=True)
    master_audio(wd / "voice.wav", wd / "master.m4a")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wd / "video_only.mp4"), "-i", str(wd / "master.m4a"),
                    "-c:v", "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
    log("[editor] final video:", out_path)
    return out_path
