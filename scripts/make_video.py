# -*- coding: utf-8 -*-
"""楽天商品ページURLから TikTok用 9:16 動画を生成する。"""
import io, os, re, subprocess, sys
import requests
from PIL import Image, ImageDraw, ImageFont

NAVY = (26, 39, 68)
GOLD = (212, 160, 23)
WHITE = (237, 239, 245)
W, H = 1080, 1920
SLIDE_SEC = 2.4
MAX_IMGS = 6
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
]

def font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def fetch_item(url):
    html = requests.get(url, headers=UA, timeout=30).text
    imgs = re.findall(r"https://image\.rakuten\.co\.jp/[^\s\"'<>\\)]+?\.(?:jpe?g|png)", html)
    seen, urls = set(), []
    for u in imgs:
        u = re.sub(r"\?.*$", "", u)
        if re.search(r"banner|logo|header|footer|common", u, re.I):
            continue
        if u not in seen:
            seen.add(u)
            urls.append(u)
    m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    title = m.group(1) if m else ""
    title = re.sub(r"【[^】]*】", "", title).split("|")[0].strip()
    price = None
    for pat in [r'"price"\s*:\s*"?(\d{3,7})', r'itemprop="price"[^>]*content="(\d+)"',
                r'税込\s*([\d,]{3,9})\s*円', r'([\d,]{3,9})円\s*\(?税込']:
        m = re.search(pat, html)
        if m:
            price = int(m.group(1).replace(",", ""))
            break
    return urls, title, price

def wrap(text, per_line, max_lines):
    lines = [text[i:i + per_line] for i in range(0, len(text), per_line)]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines

def make_slide(img, title, price, idx, total):
    slide = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(slide)
    im = img.convert("RGB")
    im.thumbnail((1000, 1200))
    slide.paste(im, ((W - im.width) // 2, (H - im.height) // 2 - 40))
    f_t = font(58)
    y = 120
    for ln in wrap(title, 15, 2):
        bbox = d.textbbox((0, 0), ln, font=f_t)
        d.text(((W - (bbox[2] - bbox[0])) // 2, y), ln, font=f_t, fill=WHITE)
        y += 78
    if price:
        f_p = font(88)
        txt = f"¥{price:,}(税込)"
        bbox = d.textbbox((0, 0), txt, font=f_p)
        tw = bbox[2] - bbox[0]
        y0 = H - 320
        d.rounded_rectangle(((W - tw) // 2 - 40, y0, (W + tw) // 2 + 40, y0 + 140),
                            radius=24, fill=GOLD)
        d.text(((W - tw) // 2, y0 + 20), txt, font=f_p, fill=(20, 20, 20))
    f_s = font(40)
    foot = f"楽天市場 ベルタワークス  {idx}/{total}"
    bbox = d.textbbox((0, 0), foot, font=f_s)
    d.text(((W - (bbox[2] - bbox[0])) // 2, H - 110), foot, font=f_s, fill=(140, 147, 168))
    return slide

def main():
    url = sys.argv[1].strip()
    manage = [s for s in url.split("/") if s][-1]
    urls, title, price = fetch_item(url)
    if not urls:
        print("画像が見つかりませんでした"); sys.exit(1)
    os.makedirs("work", exist_ok=True)
    os.makedirs("out", exist_ok=True)
    paths = []
    for u in urls[:MAX_IMGS]:
        try:
            r = requests.get(u, headers=UA, timeout=30)
            img = Image.open(io.BytesIO(r.content))
        except Exception as e:
            print("skip", u, e); continue
        slide = make_slide(img, title, price, len(paths) + 1, min(len(urls), MAX_IMGS))
        p = f"work/slide{len(paths):02d}.png"
        slide.save(p)
        paths.append(p)
    if not paths:
        print("有効な画像がありません"); sys.exit(1)
    with open("work/list.txt", "w") as f:
        for p in paths:
            f.write(f"file '{os.path.abspath(p)}'\nduration {SLIDE_SEC}\n")
        f.write(f"file '{os.path.abspath(paths[-1])}'\n")
    outp = f"out/{manage}.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "work/list.txt",
                    "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
                    "-movflags", "+faststart", outp], check=True)
    print("生成完了:", outp, len(paths), title, price)

if __name__ == "__main__":
    main()
