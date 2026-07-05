# -*- coding: utf-8 -*-
"""楽天商品ページURLから TikTok特化 9:16 動画を生成する。(v4)
v4: パララックス(背景ボケ+前景別動作)、光スイープ、テロップポップイン、スライド転換
完全無料(ffmpeg/PIL合成のみ、外部API不使用)
"""
import io, os, re, subprocess, sys
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

NAVY = (26, 39, 68)
GOLD = (212, 160, 23)
WHITE = (237, 239, 245)
RED = (230, 57, 70)
YELLOW = (255, 225, 77)
W, H = 1080, 1920
FPS = 30
SEC = 2.4
LAST_SEC = 3.2
XFADE = 0.35
MAX_IMGS = 5
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
]
TRANSITIONS = ["slideleft", "slideup", "wipeleft", "circleopen", "slideright"]
POINT_LABELS = ["専用設計でジャストフィット", "取付かんたん", "高級感アップ", "細部までこだわり"]

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
            seen.add(u); urls.append(u)
    m = re.search(r'<meta property="og:image" content="(https://image\.rakuten\.co\.jp/[^"]+)"', html)
    if m:
        og = re.sub(r"\?.*$", "", m.group(1))
        folder = og.rsplit("/", 1)[0] + "/"
        same = [u for u in urls if u.startswith(folder)]
        if og not in same and og.endswith((".jpg", ".jpeg", ".png")):
            same.insert(0, og)
        if len(same) >= 2:
            urls = same
    m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    title = m.group(1) if m else ""
    title = re.sub(r"【[^】]*】", "", title).split("|")[0].strip()
    price = None
    for pat in [r'"@type"\s*:\s*"Offer"[\s\S]{0,300}?"price"\s*:\s*"?(\d{3,7})',
                r'"price"\s*:\s*"?(\d{3,7})',
                r'itemprop="price"[^>]*content="(\d+)"',
                r'税込\s*([\d,]{3,9})\s*円', r'([\d,]{3,9})円\s*\(?税込']:
        m = re.search(pat, html)
        if m:
            price = int(m.group(1).replace(",", "")); break
    return urls, title, price

def car_name(title):
    m = re.match(r"([^\s]+(?:\s+[A-Z0-9]{2,8}[WVS]?)?)", title)
    return m.group(1) if m else ""

def make_bg(img):
    """背景: ぼかし+暗めで全面を埋める"""
    bg = img.convert("RGB").copy()
    ratio = max(W * 1.25 / bg.width, H * 1.25 / bg.height)
    bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)))
    bg = bg.crop(((bg.width - int(W * 1.25)) // 2, (bg.height - int(H * 1.25)) // 2,
                  (bg.width - int(W * 1.25)) // 2 + int(W * 1.25),
                  (bg.height - int(H * 1.25)) // 2 + int(H * 1.25)))
    bg = bg.filter(ImageFilter.GaussianBlur(24))
    dark = Image.new("RGB", bg.size, NAVY)
    return Image.blend(bg, dark, 0.45)

def make_fg(img):
    """前景: シャープな商品画像に角丸+影(RGBA)"""
    fg = img.convert("RGB").copy()
    fg.thumbnail((940, 1150))
    r = 36
    mask = Image.new("L", fg.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fg.width, fg.height), radius=r, fill=255)
    pad = 60
    canvas = Image.new("RGBA", (fg.width + pad * 2, fg.height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad + 14, pad + 20, pad + fg.width + 14, pad + fg.height + 20),
                                         radius=r, fill=(0, 0, 0, 140))
    sh = sh.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.alpha_composite(canvas, sh)
    canvas.paste(fg, (pad, pad), mask)
    return canvas

def text_overlay(lines, y0=170):
    """テロップ(RGBA・透明背景)"""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    y = y0
    for txt, size, fill in lines:
        f = font(size)
        bbox = d.textbbox((0, 0), txt, font=f)
        x = (W - (bbox[2] - bbox[0])) // 2
        d.text((x, y), txt, font=f, fill=fill, stroke_width=10, stroke_fill=(15, 19, 32))
        y += size + 28
    return ov

def badge_overlay(txt, y0, bgc, fgc, size=84):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f = font(size)
    bbox = d.textbbox((0, 0), txt, font=f)
    tw = bbox[2] - bbox[0]
    d.rounded_rectangle(((W - tw) // 2 - 50, y0, (W + tw) // 2 + 50, y0 + size + 56),
                        radius=28, fill=bgc)
    d.text(((W - tw) // 2, y0 + 24), txt, font=f, fill=fgc)
    return ov

def render_cut(idx, bg, fg, overlays, sec, drift=1):
    """パララックス+光スイープ+テロップポップインで1カット生成"""
    bgp, fgp = f"work/bg{idx}.png", f"work/fg{idx}.png"
    bg.save(bgp); fg.save(fgp)
    ovps = []
    for j, ov in enumerate(overlays):
        p = f"work/ov{idx}_{j}.png"
        ov.save(p); ovps.append(p)
    frames = int(sec * FPS)
    inputs = ["-loop", "1", "-t", str(sec), "-i", bgp,
              "-loop", "1", "-t", str(sec), "-i", fgp]
    for p in ovps:
        inputs += ["-loop", "1", "-t", str(sec), "-i", p]
    # 背景: ゆっくりズーム(パララックス奥)
    fc = (f"[0:v]zoompan=z='1+0.0012*on':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
          f":d={frames}:s={W}x{H}:fps={FPS}[bg];")
    # 前景: 逆方向にゆっくり漂う(パララックス手前)+わずかに拡大
    fc += (f"[1:v]scale=iw*(1+0.04*t/{sec}):-1:eval=frame[fgs];"
           f"[bg][fgs]overlay=x='(W-w)/2+{18*drift}*sin(t*0.9)'"
           f":y='(H-h)/2-30+{12*drift}*cos(t*0.7)'[base];")
    # 光スイープ(1回だけ横切る)
    fc += (f"[base]drawbox=x=0:y=0:w=iw:h=ih:color=black@0:t=fill,"
           f"format=yuv420p[b2];"
           f"color=c=white@0.0:s={W}x{H}:d={sec},format=rgba,"
           f"geq=r=255:g=255:b=255:a='if(lt(abs(X-(T-0.3)*{W}*1.6),90),120*(1-abs(X-(T-0.3)*{W}*1.6)/90),0)'[lt];"
           f"[b2][lt]overlay[b3];")
    last = "b3"
    # テロップ: 0.35秒でスライド+フェードイン
    for j in range(len(ovps)):
        st = 0.15 + j * 0.25
        fc += (f"[{2+j}:v]format=rgba,fade=t=in:st={st}:d=0.35:alpha=1[t{j}];"
               f"[{last}][t{j}]overlay=x=0:y='if(lt(t,{st}+0.35),40*(1-min((t-{st})/0.35,1)),0)'[o{j}];")
        last = f"o{j}"
    fc += f"[{last}]format=yuv420p[v]"
    seg = f"work/seg{idx:02d}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc,
                    "-map", "[v]", "-t", str(sec), "-r", str(FPS),
                    "-c:v", "libx264", "-preset", "medium", seg], check=True)
    return seg, sec

def concat_xfade(segs):
    """カット間をスライド/ワイプ転換でつなぐ"""
    inputs = []
    for s, _ in segs:
        inputs += ["-i", s]
    fc = ""
    last = "0:v"
    offset = 0.0
    for i in range(1, len(segs)):
        offset += segs[i - 1][1] - XFADE
        tr = TRANSITIONS[(i - 1) % len(TRANSITIONS)]
        out = f"x{i}"
        fc += f"[{last}][{i}:v]xfade=transition={tr}:duration={XFADE}:offset={offset:.2f}[{out}];"
        last = out
    fc += f"[{last}]format=yuv420p[v]"
    return inputs, fc

def main():
    url = sys.argv[1].strip()
    manage = [s for s in url.split("/") if s][-1]
    urls, title, price = fetch_item(url)
    if not urls:
        print("画像が見つかりませんでした"); sys.exit(1)
    os.makedirs("work", exist_ok=True)
    os.makedirs("out", exist_ok=True)
    imgs = []
    for u in urls[:MAX_IMGS]:
        try:
            r = requests.get(u, headers=UA, timeout=30)
            imgs.append(Image.open(io.BytesIO(r.content)))
        except Exception as e:
            print("skip", u, e)
    if not imgs:
        print("有効な画像がありません"); sys.exit(1)

    segs = []
    car = car_name(title)
    # カット1: フック
    ov1 = text_overlay([(f"{car}乗り", 110, WHITE), ("これ知ってた?", 122, YELLOW)])
    segs.append(render_cut(0, make_bg(imgs[0]), make_fg(imgs[0]), [ov1], SEC, drift=1))
    # 中盤: POINT
    for i, im in enumerate(imgs[1:], 1):
        ovb = badge_overlay(f"POINT {i}", 180, GOLD, (20, 20, 20), 72)
        ovt = text_overlay([(POINT_LABELS[(i - 1) % len(POINT_LABELS)], 76, WHITE)], y0=340)
        segs.append(render_cut(i, make_bg(im), make_fg(im), [ovb, ovt], SEC, drift=-1 if i % 2 else 1))
    # 最終: 価格CTA
    n = len(imgs)
    ovs = []
    short = title if len(title) <= 15 else title[:15] + "…"
    ovs.append(text_overlay([(short, 72, WHITE)], y0=560))
    if price:
        ovs.append(text_overlay([(f"¥{price:,}", 190, YELLOW), ("(税込)", 56, WHITE)], y0=760))
    ovs.append(badge_overlay("楽天で ベルタワークス 検索", 1460, RED, WHITE, 78))
    cta_bg = make_bg(imgs[0])
    cta_fg = make_fg(imgs[0])
    cta_fg = cta_fg.resize((int(cta_fg.width * 0.55), int(cta_fg.height * 0.55)))
    segs.append(render_cut(n, cta_bg, cta_fg, ovs, LAST_SEC, drift=1))

    inputs, fc = concat_xfade(segs)
    outp = f"out/{manage}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc,
                    "-map", "[v]", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
                    "-movflags", "+faststart", outp], check=True)
    print("生成完了:", outp, "カット数:", len(segs), title, price)

if __name__ == "__main__":
    main()
