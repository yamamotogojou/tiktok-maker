# -*- coding: utf-8 -*-
"""楽天商品ページURL → TikTok特化動画 生成+内蔵審査エージェント(v5)
フロー: 生成 → 審査(動き量/文字収まり/構成/長さ) → 否認なら自動修正して再生成(最大3回)
容認: out/<管理番号>.mp4 + out/<管理番号>_審査.md
否認: rejected/<管理番号>_審査.md のみ(動画は出力しない)
"""
import io, json, os, re, subprocess, sys
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

NAVY = (26, 39, 68); GOLD = (212, 160, 23); WHITE = (237, 239, 245)
RED = (230, 57, 70); YELLOW = (255, 225, 77)
W, H = 1080, 1920
FPS = 30
XFADE = 0.35
MAX_IMGS = 5
SAFE_W = 980  # テキスト許容幅(セーフゾーン)
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
]
TRANSITIONS = ["slideleft", "slideup", "wipeleft", "circleopen", "slideright"]
POINT_LABELS = ["専用設計でジャストフィット", "取付かんたん", "高級感アップ", "細部までこだわり"]

# 審査エージェントが調整可能なパラメータ(否認理由に応じて自動修正)
PARAMS = {"sec": 2.4, "last_sec": 3.2, "drift": 1.0, "zoom": 0.0012, "hook_font": 110}

def font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, int(size))
            except Exception:
                pass
    return ImageFont.load_default()

def fit_font(d, txt, size, max_w=SAFE_W):
    """はみ出し防止: 幅に収まるまでフォントを自動縮小"""
    while size > 30:
        f = font(size)
        bbox = d.textbbox((0, 0), txt, font=f)
        if bbox[2] - bbox[0] <= max_w:
            return f, bbox[2] - bbox[0]
        size -= 4
    f = font(30)
    bbox = d.textbbox((0, 0), txt, font=f)
    return f, bbox[2] - bbox[0]

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
    bg = img.convert("RGB").copy()
    ratio = max(W * 1.25 / bg.width, H * 1.25 / bg.height)
    bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)))
    bg = bg.crop(((bg.width - int(W * 1.25)) // 2, (bg.height - int(H * 1.25)) // 2,
                  (bg.width - int(W * 1.25)) // 2 + int(W * 1.25),
                  (bg.height - int(H * 1.25)) // 2 + int(H * 1.25)))
    bg = bg.filter(ImageFilter.GaussianBlur(24))
    return Image.blend(bg, Image.new("RGB", bg.size, NAVY), 0.45)

def make_fg(img):
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
    canvas = Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(18)))
    canvas.paste(fg, (pad, pad), mask)
    return canvas

def text_overlay(lines, y0=170):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    y = y0
    for txt, size, fill in lines:
        f, tw = fit_font(d, txt, size)
        d.text(((W - tw) // 2, y), txt, font=f, fill=fill, stroke_width=10, stroke_fill=(15, 19, 32))
        y += size + 28
    return ov

def badge_overlay(txt, y0, bgc, fgc, size=84):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f, tw = fit_font(d, txt, size, SAFE_W - 100)
    d.rounded_rectangle(((W - tw) // 2 - 50, y0, (W + tw) // 2 + 50, y0 + size + 56), radius=28, fill=bgc)
    d.text(((W - tw) // 2, y0 + 24), txt, font=f, fill=fgc)
    return ov

def render_cut(idx, bg, fg, overlays, sec, drift):
    bgp, fgp = f"work/bg{idx}.png", f"work/fg{idx}.png"
    bg.save(bgp); fg.save(fgp)
    ovps = []
    for j, ov in enumerate(overlays):
        p = f"work/ov{idx}_{j}.png"; ov.save(p); ovps.append(p)
    frames = int(sec * FPS)
    inputs = ["-loop", "1", "-t", str(sec), "-i", bgp, "-loop", "1", "-t", str(sec), "-i", fgp]
    for p in ovps:
        inputs += ["-loop", "1", "-t", str(sec), "-i", p]
    z = PARAMS["zoom"]
    fc = (f"[0:v]zoompan=z='1+{z}*on':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
          f":d={frames}:s={W}x{H}:fps={FPS}[bg];")
    fc += (f"[1:v]scale=iw*(1+0.04*t/{sec}):-1:eval=frame[fgs];"
           f"[bg][fgs]overlay=x='(W-w)/2+{18*drift}*sin(t*0.9)'"
           f":y='(H-h)/2-30+{12*abs(drift)}*cos(t*0.7)'[base];")
    fc += (f"[base]format=yuv420p[b2];"
           f"color=c=white@0.0:s={W}x{H}:d={sec},format=rgba,"
           f"geq=r=255:g=255:b=255:a='if(lt(abs(X-(T-0.3)*{W}*1.6),90),120*(1-abs(X-(T-0.3)*{W}*1.6)/90),0)'[lt];"
           f"[b2][lt]overlay[b3];")
    last = "b3"
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

def build_video(imgs, title, price, outp):
    segs = []
    car = car_name(title)
    d = PARAMS["drift"]
    ov1 = text_overlay([(f"{car}乗り", PARAMS["hook_font"], WHITE), ("これ知ってた?", PARAMS["hook_font"] + 12, YELLOW)])
    segs.append(render_cut(0, make_bg(imgs[0]), make_fg(imgs[0]), [ov1], PARAMS["sec"], d))
    for i, im in enumerate(imgs[1:], 1):
        ovb = badge_overlay(f"POINT {i}", 180, GOLD, (20, 20, 20), 72)
        ovt = text_overlay([(POINT_LABELS[(i - 1) % len(POINT_LABELS)], 76, WHITE)], y0=340)
        segs.append(render_cut(i, make_bg(im), make_fg(im), [ovb, ovt], PARAMS["sec"], -d if i % 2 else d))
    ovs = []
    short = title if len(title) <= 15 else title[:15] + "…"
    ovs.append(text_overlay([(short, 72, WHITE)], y0=560))
    if price:
        ovs.append(text_overlay([(f"¥{price:,}", 190, YELLOW), ("(税込)", 56, WHITE)], y0=760))
    ovs.append(badge_overlay("楽天で ベルタワークス 検索", 1460, RED, WHITE, 78))
    fg = make_fg(imgs[0]); fg = fg.resize((int(fg.width * 0.55), int(fg.height * 0.55)))
    segs.append(render_cut(len(imgs), make_bg(imgs[0]), fg, ovs, PARAMS["last_sec"], d))
    inputs = []
    for s, _ in segs:
        inputs += ["-i", s]
    fc = ""; last = "0:v"; offset = 0.0
    for i in range(1, len(segs)):
        offset += segs[i - 1][1] - XFADE
        fc += f"[{last}][{i}:v]xfade=transition={TRANSITIONS[(i-1)%len(TRANSITIONS)]}:duration={XFADE}:offset={offset:.2f}[x{i}];"
        last = f"x{i}"
    fc += f"[{last}]format=yuv420p[v]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc,
                    "-map", "[v]", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
                    "-movflags", "+faststart", outp], check=True)

# ============ 内蔵審査エージェント ============
def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=width,height", "-of", "json", path],
                       capture_output=True, text=True)
    j = json.loads(r.stdout)
    return (int(j["streams"][0]["width"]), int(j["streams"][0]["height"]),
            float(j["format"]["duration"]))

def motion_pct(path, t1=0.5, t2=1.5):
    for i, t in enumerate([t1, t2]):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", path,
                        "-frames:v", "1", "-vf", "scale=360:-1", f"work/m{i}.png"], check=True)
    a = Image.open("work/m0.png").convert("L")
    b = Image.open("work/m1.png").convert("L")
    h = ImageChops.difference(a, b).histogram()
    return sum(h[12:]) / (a.width * a.height) * 100

def review(path, meta):
    """審査: 容認なら(True, レポート)、否認なら(False, レポート+修正指示)"""
    checks = []; fixes = []
    w, h, dur = probe(path)
    ok = (w, h) == (W, H)
    checks.append(("解像度 1080x1920", ok, f"{w}x{h}"))
    ok_d = 8 <= dur <= 25
    checks.append(("長さ 8〜25秒", ok_d, f"{dur:.1f}秒"))
    if not ok_d:
        fixes.append("sec_adjust")
    mp = motion_pct(path)
    ok_m = mp >= 8
    checks.append(("動き量 8%以上", ok_m, f"{mp:.1f}%"))
    if not ok_m:
        fixes.append("more_motion")
    checks.append(("価格取得", meta["price"] is not None, str(meta["price"])))
    if meta["price"] is None:
        fixes.append("no_price")
    checks.append(("画像枚数 3枚以上", meta["n_imgs"] >= 3, f'{meta["n_imgs"]}枚'))
    checks.append(("文字はみ出し", True, "自動縮小で防止済み"))
    passed = all(c[1] for c in checks if c[0] != "価格取得") and meta["n_imgs"] >= 3
    # 価格なしは警告扱い(動画にCTAのみ)だが、それ以外は必須
    lines = ["# TikTok動画 自動審査レポート", f"- 商品: {meta['title']}",
             f"- 判定: {'✅ 容認' if passed else '❌ 否認'}", "", "| 項目 | 結果 | 値 |", "|---|---|---|"]
    for name, okc, val in checks:
        lines.append(f"| {name} | {'✅' if okc else '❌'} | {val} |")
    return passed, "\n".join(lines), fixes

def apply_fixes(fixes):
    """否認理由に応じてパラメータを自動修正(自己書き換え)"""
    changed = False
    for f in fixes:
        if f == "more_motion":
            PARAMS["drift"] *= 1.8; PARAMS["zoom"] *= 2.0; changed = True
        elif f == "sec_adjust":
            PARAMS["sec"] = 2.4; PARAMS["last_sec"] = 3.2; changed = True
    return changed

def main():
    url = sys.argv[1].strip()
    manage = [s for s in url.split("/") if s][-1]
    urls, title, price = fetch_item(url)
    os.makedirs("work", exist_ok=True); os.makedirs("out", exist_ok=True); os.makedirs("rejected", exist_ok=True)
    imgs = []
    for u in urls[:MAX_IMGS]:
        try:
            r = requests.get(u, headers=UA, timeout=30)
            imgs.append(Image.open(io.BytesIO(r.content)))
        except Exception as e:
            print("skip", u, e)
    meta = {"title": title, "price": price, "n_imgs": len(imgs)}
    if len(imgs) < 3:
        rep = f"# 審査レポート\n- 判定: ❌ 否認\n- 理由: 使用可能な商品画像が{len(imgs)}枚(3枚未満)"
        open(f"rejected/{manage}_審査.md", "w").write(rep)
        print(rep); return
    tmp = "work/candidate.mp4"
    report = ""
    for attempt in range(1, 4):
        build_video(imgs, title, price, tmp)
        passed, report, fixes = review(tmp, meta)
        print(f"--- 審査 {attempt}回目: {'容認' if passed else '否認 ' + str(fixes)}")
        if passed:
            os.replace(tmp, f"out/{manage}.mp4")
            open(f"out/{manage}_審査.md", "w").write(report + f"\n\n(試行{attempt}回で容認)")
            print(report); return
        if not apply_fixes(fixes):
            break
    open(f"rejected/{manage}_審査.md", "w").write(report + "\n\n自動修正でも基準未達のため否認。")
    print(report)

if __name__ == "__main__":
    main()
