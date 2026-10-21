"""High-CTR thumbnail: blurred cover backdrop, tilted glowing book cover, bold headline with highlighted keyword,
arrow pointing to the book, 'BOOK SUMMARY' tag."""
import math
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from editor import find_font, accent_from_cover

W, H = 1280, 720


def _font(kind, size):
    return ImageFont.truetype(find_font(kind)[0], size)


def _fit_font(text, kind, max_w, start):
    s = start
    while s > 40 and _font(kind, s).getlength(text) > max_w:
        s -= 4
    return _font(kind, s), s


def make_thumbnail(cover_path, line1, line2, author, out, tag="BOOK SUMMARY"):
    accent = accent_from_cover(cover_path)
    cover = Image.open(cover_path).convert("RGB")
    bg = ImageOps.fit(cover, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(30))
    bg = ImageEnhance.Brightness(bg).enhance(.38)
    bg = ImageEnhance.Color(bg).enhance(1.3)
    shade = Image.new("RGBA", (W, H))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        sd.line([(x, 0), (x, H)], fill=(0, 0, 0, int(190 * max(0, 1 - x / (W * .75)))))
    bg = Image.alpha_composite(bg.convert("RGBA"), shade)

    bh = 600
    book = ImageOps.contain(cover, (int(bh * .8), bh), Image.LANCZOS)
    pad = 90
    layer = Image.new("RGBA", (book.width + pad * 2, book.height + pad * 2), (0, 0, 0, 0))
    glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle([pad - 25, pad - 25, pad + book.width + 25, pad + book.height + 25], 24, fill=(*accent, 210))
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(38)))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([pad + 14, pad + 22, pad + book.width + 14, pad + book.height + 22], fill=(0, 0, 0, 190))
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(16)))
    layer.paste(book, (pad, pad))
    ImageDraw.Draw(layer).rectangle([pad, pad, pad + 9, pad + book.height], fill=(255, 255, 255, 55))
    layer = layer.rotate(-6, resample=Image.BICUBIC, expand=True)
    bx, by = W - layer.width + 30, (H - layer.height) // 2
    bg.alpha_composite(layer, (max(bx, 560), by))
    book_left = max(bx, 560) + pad

    d = ImageDraw.Draw(bg)
    tf = _font("sans_bold", 30)
    tw = int(tf.getlength(tag)) + 40
    d.rounded_rectangle([50, 46, 50 + tw, 100], 10, fill=(255, 255, 255, 235))
    d.text((70, 73), tag, font=tf, fill=(15, 15, 15), anchor="lm")

    max_w = 640
    f1, s1 = _fit_font(line1.upper(), "display", max_w, 150)
    f2, s2 = _fit_font(line2.upper(), "display", max_w, 170)
    y = 150
    d.text((54, y), line1.upper(), font=f1, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    y += s1 + 20
    w2 = int(f2.getlength(line2.upper()))
    d.rectangle([40, y - 6, 60 + w2 + 22, y + s2 + 22], fill=accent)
    lum = .299 * accent[0] + .587 * accent[1] + .114 * accent[2]
    d.text((56, y + 6), line2.upper(), font=f2, fill=(10, 10, 10) if lum > 140 else (255, 255, 255))
    y += s2 + 50
    d.text((56, y), f"BY {author.upper()}", font=_font("sans_bold", 34), fill=(235, 235, 235), stroke_width=2, stroke_fill=(0, 0, 0))

    sx, sy = 70, 640
    ex, ey = book_left - 10, 560
    path = [(sx + (ex - sx) * (i / 20), sy + (ey - sy) * (i / 20) - 110 * math.sin(i / 20 * math.pi)) for i in range(21)]
    d.line(path, fill=(255, 255, 255), width=9, joint="curve")
    a = math.atan2(path[-1][1] - path[-3][1], path[-1][0] - path[-3][0])
    tip = path[-1]
    d.polygon([tip, (tip[0] - 38 * math.cos(a - .5), tip[1] - 38 * math.sin(a - .5)),
               (tip[0] - 38 * math.cos(a + .5), tip[1] - 38 * math.sin(a + .5))], fill=(255, 255, 255))

    img = ImageEnhance.Contrast(bg.convert("RGB")).enhance(1.12)
    img = ImageEnhance.Sharpness(img).enhance(1.4)
    q = 92
    while True:
        img.save(out, "JPEG", quality=q, optimize=True)
        if out.stat().st_size < 1_900_000 or q < 60:
            break
        q -= 8
    return out
