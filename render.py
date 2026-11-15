"""Рендер вертикальных Shorts «Факты, которые видно» (1080x1920, 30 fps).

Использование:  python3 render.py scenario.json out.mp4
Сценарий — JSON со списком сцен (типы: hook, text, count, compare, dots, scale, outro).
"""
import json, math, os, random, subprocess, sys, tempfile, wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
F_BLACK = os.path.join(HERE, "fonts", "Inter-Black.otf")
F_SEMI = os.path.join(HERE, "fonts", "Inter-SemiBold.otf")
BRAND = "ФАКТЫ, КОТОРЫЕ ВИДНО"

BG_TOP = (10, 14, 32)
BG_BOT = (24, 16, 48)
WHITE = (245, 246, 250)
MUTED = (150, 158, 190)

DUR = {"hook": 3.6, "text": 4.2, "count": 5.0, "compare": 7.0, "dots": 6.5,
       "scale": 6.5, "outro": 3.4}

_font_cache = {}


def font(path, size):
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def fmt_num(v, decimals=0):
    if decimals:
        s = f"{v:,.{decimals}f}"
    else:
        s = f"{int(round(v)):,}"
    return s.replace(",", " ").replace(".", ",")


# ---------- текст ----------

def parse_marked(text):
    """'Обычный *выделенный* текст' -> [(слово, выделено?)]"""
    import re as _re
    text = _re.sub(r"(\d) (%|°C)", "\\1\u00a0\\2", text)  # «2 %» не разрывать по строкам
    words, hl = [], False
    for part in text.replace("\n", " \n ").split(" "):
        if not part:
            continue
        w = part
        start = w.startswith("*")
        end = w.endswith("*") and len(w) > 1
        if start:
            hl = True
            w = w[1:]
        words.append((w.rstrip("*") if end else w, hl))
        if end:
            hl = False
    return words


def layout(words, fnt, max_w):
    """Перенос строк. Возвращает список строк [(слово, выделено, x, ширина)] и высоту строки."""
    space = fnt.getlength(" ")
    lines, cur, cur_w = [], [], 0
    for w, hl in words:
        if w == "\n":
            lines.append(cur); cur, cur_w = [], 0
            continue
        ww = fnt.getlength(w)
        if cur and cur_w + space + ww > max_w:
            lines.append(cur); cur, cur_w = [], 0
        cur.append((w, hl, ww))
        cur_w += (space if cur_w else 0) + ww
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        x, row = 0, []
        for w, hl, ww in ln:
            row.append((w, hl, x, ww))
            x += ww + space
        out.append((row, x - space))
    return out


def fit_font(text, path, max_size, max_w, max_lines):
    words = parse_marked(text)
    size = max_size
    while size > 30:
        f = font(path, size)
        ls = layout(words, f, max_w)
        longest = max((max(f.getlength(w) for w, _ in words if w != "\n"),), default=0)
        if len(ls) <= max_lines and longest <= max_w:
            return f, ls
        size -= 4
    f = font(path, size)
    return f, layout(words, f, max_w)


def draw_text_block(d, text, cy, accent, max_size=110, max_w=900, max_lines=5,
                    path=F_BLACK, color=WHITE, t=1.0, per_word=0.06, align="center"):
    """Рисует абзац с появлением по словам. t — время с начала появления (сек)."""
    f, lines = fit_font(text, path, max_size, max_w, max_lines)
    lh = int(f.size * 1.18)
    total_h = lh * len(lines)
    y0 = cy - total_h // 2
    idx = 0
    for li, (row, lw) in enumerate(lines):
        x0 = (W - lw) / 2 if align == "center" else (W - max_w) / 2
        for w, hl, x, ww in row:
            p = ease_out((t - idx * per_word) / 0.35)
            idx += 1
            if p <= 0:
                continue
            dy = int((1 - p) * 40)
            col = accent if hl else color
            col = mix(BG_TOP, col, p)
            if hl:
                pad = 6
                d.rounded_rectangle([x0 + x - pad, y0 + li * lh + dy + 4,
                                     x0 + x + ww + pad, y0 + li * lh + dy + lh - 4],
                                    radius=14, fill=mix(BG_TOP, tuple(c // 4 for c in accent), p))
            d.text((x0 + x, y0 + li * lh + dy), w, font=f, fill=col)
    return y0, y0 + total_h


# ---------- фон ----------

def make_bg(accent, seed):
    grad = np.zeros((H, W, 3), np.float32)
    ys = np.linspace(0, 1, H)[:, None]
    for c in range(3):
        grad[:, :, c] = BG_TOP[c] + (BG_BOT[c] - BG_TOP[c]) * ys
    # мягкое цветное пятно
    yy, xx = np.mgrid[0:H, 0:W]
    rnd = random.Random(seed)
    cx, cy = rnd.choice([(200, 400), (880, 500), (540, 1500)])
    glow = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 520.0 ** 2)))
    for c in range(3):
        grad[:, :, c] += glow * accent[c] * 0.18
    return Image.fromarray(np.clip(grad, 0, 255).astype(np.uint8))


class Stars:
    def __init__(self, seed):
        r = random.Random(seed)
        self.p = [(r.uniform(0, W), r.uniform(0, H), r.uniform(1.5, 4), r.uniform(8, 30),
                   r.uniform(0, 6.28)) for _ in range(60)]

    def draw(self, d, gt):
        for x, y, s, sp, ph in self.p:
            yy = (y - gt * sp) % H
            a = 0.35 + 0.35 * math.sin(gt * 1.5 + ph)
            c = mix(BG_TOP, (200, 210, 255), a * 0.6)
            d.ellipse([x - s, yy - s, x + s, yy + s], fill=c)


def draw_chrome(d, accent, gt, total, scene_i, n_scenes):
    # плашка бренда
    f = font(F_SEMI, 34)
    tw = f.getlength(BRAND)
    x0 = (W - tw) / 2 - 28
    d.rounded_rectangle([x0, 150, x0 + tw + 56, 214], radius=32, outline=accent, width=3)
    d.text(((W - tw) / 2, 163), BRAND, font=f, fill=accent)
    # прогресс видео внизу
    d.rounded_rectangle([90, 1760, W - 90, 1772], radius=6, fill=(45, 50, 80))
    d.rounded_rectangle([90, 1760, 90 + (W - 180) * min(1, gt / total), 1772], radius=6, fill=accent)


# ---------- сцены ----------

def sc_hook(d, s, t, A):
    draw_text_block(d, s["text"], 860, A, max_size=124, max_lines=5, t=t, per_word=0.09)
    if s.get("sub"):
        draw_text_block(d, s["sub"], 1380, A, max_size=52, path=F_SEMI, color=MUTED,
                        max_lines=2, t=t - 0.9)


def sc_text(d, s, t, A):
    draw_text_block(d, s["text"], 900, A, max_size=96, max_lines=7, t=t, per_word=0.07)


def sc_count(d, s, t, A):
    val = float(s["value"])
    dec = int(s.get("decimals", 0))
    p = ease_out((t - 0.2) / 2.2)
    num = fmt_num(val * p, dec)
    if s.get("prefix"):
        num = s["prefix"] + num
    f, _ = fit_font(num + " ", F_BLACK, 210, 960, 1)
    tw = f.getlength(num)
    sc = 0.85 + 0.15 * ease_back((t - 0.2) / 0.5)
    fb = font(F_BLACK, max(30, int(f.size * sc)))
    tw = fb.getlength(num)
    d.text(((W - tw) / 2, 800 - fb.size / 2), num, font=fb, fill=A)
    if s.get("unit"):
        draw_text_block(d, s["unit"], 1000, A, max_size=70, path=F_SEMI, max_lines=2, t=t - 0.5)
    if s.get("caption"):
        draw_text_block(d, s["caption"], 1260, A, max_size=72, max_lines=5, t=t - 1.6,
                        color=WHITE)


def sc_compare(d, s, t, A):
    draw_text_block(d, s["title"], 420, A, max_size=84, max_lines=3, t=t)
    items = s["items"]
    vmax = max(i["value"] for i in items)
    n = len(items)
    top, gap = 700, min(260, 900 // n)
    left, right = 90, W - 90
    flab = font(F_SEMI, 50)
    fval = font(F_BLACK, 56)
    for k, it in enumerate(items):
        y = top + k * gap
        start = 0.7 + k * 0.6
        p = ease_out((t - start) / 1.3)
        a = ease_out((t - start + 0.3) / 0.4)
        if a <= 0:
            continue
        col = A if it.get("hl") else (120, 132, 175)
        d.text((left, y), it["label"], font=flab, fill=mix(BG_TOP, WHITE, a))
        bw = (right - left) * max(0.012, it["value"] / vmax) * p
        d.rounded_rectangle([left, y + 70, right, y + 140], radius=35, fill=(32, 38, 66))
        if bw > 10:
            d.rounded_rectangle([left, y + 70, left + max(bw, 70), y + 140], radius=35, fill=col)
        txt = it.get("text") or fmt_num(it["value"] * p, it.get("decimals", 0)) + (" " + it.get("unit", "") if it.get("unit") else "")
        if it.get("text") and p < 0.9:
            continue
        tw = fval.getlength(txt)
        tx = min(left + max(bw, 70) + 20, right - tw - 34)
        inside = tx < left + bw
        d.text((tx, y + 76), txt, font=fval, fill=BG_TOP if inside else mix(BG_TOP, WHITE, a))
    if s.get("caption"):
        draw_text_block(d, s["caption"], 1560, A, max_size=58, path=F_SEMI, max_lines=3,
                        t=t - (0.9 + n * 0.6 + 0.8))


def sc_dots(d, s, t, A):
    draw_text_block(d, s["title"], 430, A, max_size=80, max_lines=3, t=t)
    total, k = int(s.get("total", 100)), int(s["highlight"])
    cols = 10
    rows = math.ceil(total / cols)
    cell = 68
    gx = (W - cols * cell) / 2
    gy = 700
    p_in = (t - 0.5) / 1.0
    hl_n = int(k * ease_out((t - 1.7) / 1.8))
    for i in range(total):
        r_, c_ = divmod(i, cols)
        a = ease_out(p_in - i * 0.004)
        if a <= 0:
            continue
        cx, cy = gx + c_ * cell + cell / 2, gy + r_ * cell + cell / 2
        rad = 25 * a
        col = A if i < hl_n else (58, 66, 104)
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=col)
    big = f"{hl_n} из {total}"
    fb = font(F_BLACK, 96)
    end_y = gy + rows * cell
    if t > 1.7:
        d.text(((W - fb.getlength(big)) / 2, end_y + 40), big, font=fb, fill=A)
    if s.get("caption"):
        draw_text_block(d, s["caption"], min(end_y + 240, 1640), A, max_size=56, path=F_SEMI,
                        max_lines=3, t=t - 3.6)


def sc_scale(d, s, t, A):
    draw_text_block(d, s["title"], 400, A, max_size=80, max_lines=3, t=t)
    items = s["items"]  # [{label, value}] — диаметры/высоты
    vmax = max(i["value"] for i in items)
    base_y = 1350
    if s.get("shape") == "circle":
        return _scale_circles(d, s, t, A, items, vmax, base_y)
    maxh = 700
    n = len(items)
    slot = (W - 160) / n
    flab = font(F_SEMI, 46)
    for k, it in enumerate(items):
        p = ease_back((t - 0.8 - k * 0.5) / 0.9)
        if p <= 0:
            continue
        hgt = max(10, maxh * it["value"] / vmax) * p
        cx = 80 + slot * k + slot / 2
        wdt = min(slot * 0.8, hgt) if s.get("shape") == "circle" else slot * 0.62
        col = A if it.get("hl") else (120, 132, 175)
        if s.get("shape") == "circle":
            rr = hgt / 2
            d.ellipse([cx - rr, base_y - 2 * rr, cx + rr, base_y], fill=col)
        else:
            d.rounded_rectangle([cx - wdt / 2, base_y - hgt, cx + wdt / 2, base_y], radius=16, fill=col)
        lab = it["label"]
        for j, line in enumerate(lab.split("\n")):
            lw = flab.getlength(line)
            d.text((cx - lw / 2, base_y + 24 + j * 56), line, font=flab, fill=WHITE)
        if it.get("text") and p > 0.9:
            fv = font(F_BLACK, 44)
            vw = fv.getlength(it["text"])
            d.text((cx - vw / 2, base_y - hgt - 62), it["text"], font=fv, fill=WHITE)
    if s.get("caption"):
        draw_text_block(d, s["caption"], 1600, A, max_size=56, path=F_SEMI, max_lines=3,
                        t=t - (1.2 + n * 0.5 + 0.6))


def _scale_circles(d, s, t, A, items, vmax, base_y):
    maxd = 600
    gap = 120
    ds = [maxd * it["value"] / vmax for it in items]
    total_w = sum(max(dd, 8) for dd in ds) + gap * (len(ds) - 1)
    x = (W - total_w) / 2
    flab = font(F_SEMI, 40)
    fv = font(F_BLACK, 40)
    n = len(items)
    for k, (it, dd) in enumerate(zip(items, ds)):
        dd = max(dd, 8)
        cx = x + dd / 2
        x += dd + gap
        p = ease_back((t - 0.8 - k * 0.6) / 0.9)
        if p <= 0:
            continue
        rr = dd / 2 * max(0, p)
        col = A if it.get("hl") else (120, 132, 175)
        d.ellipse([cx - rr, base_y - dd / 2 - rr, cx + rr, base_y - dd / 2 + rr], fill=col)
        # подпись: у маленьких — сверху со стрелкой
        lines = it["label"].split("\n") + ([it["text"]] if it.get("text") else [])
        if dd < 200:
            ly = base_y - dd - 70 - 50 * len(lines) - 130 * (k % 2)
            d.line([cx, ly + 50 * len(lines) + 6, cx, base_y - dd - 8], fill=MUTED, width=3)
        else:
            ly = base_y + 30
        for j, line in enumerate(lines):
            f = fv if (it.get("text") and j == len(lines) - 1) else flab
            lw = f.getlength(line)
            lx = min(max(cx - lw / 2, 30), W - 30 - lw)
            d.text((lx, ly + j * 50), line, font=f, fill=WHITE)
    if s.get("caption"):
        draw_text_block(d, s["caption"], 1620, A, max_size=56, path=F_SEMI, max_lines=3,
                        t=t - (1.2 + n * 0.6 + 0.6))


def sc_outro(d, s, t, A):
    draw_text_block(d, s.get("text", "А ты *знал* об этом?"), 820, A, max_size=110,
                    max_lines=4, t=t)
    sub = s.get("sub", "Подпишись — каждый день новые факты")
    p = ease_back((t - 0.9) / 0.6)
    if p > 0:
        fs = 52
        while font(F_BLACK, fs).getlength(sub) > W - 220 and fs > 28:
            fs -= 2
        f = font(F_BLACK, fs)
        tw = f.getlength(sub)
        bw = tw + 90
        x0 = (W - bw) / 2
        y0 = 1240 + (1 - p) * 60
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + 120], radius=60, fill=A)
        d.text((x0 + 45, y0 + 60 - fs * 0.6), sub, font=f, fill=BG_TOP)


SCENES = {"hook": sc_hook, "text": sc_text, "count": sc_count, "compare": sc_compare,
          "dots": sc_dots, "scale": sc_scale, "outro": sc_outro}


# ---------- звук ----------

def make_audio(path, total, cue_times, seed):
    sr = 44100
    n = int(total * sr) + sr
    t = np.arange(n) / sr
    rnd = random.Random(seed)
    roots = rnd.choice([[220.0, 174.61, 196.0, 164.81], [196.0, 155.56, 174.61, 233.08],
                        [233.08, 196.0, 174.61, 207.65]])
    bar = 2.4
    out = np.zeros(n)
    for i in range(int(total / bar) + 2):
        f0 = roots[i % len(roots)]
        s0 = int(i * bar * sr)
        L = int(bar * 1.3 * sr)
        if s0 >= n:
            break
        seg = t[:min(L, n - s0)]
        env = np.minimum(1, seg / 0.4) * np.exp(-seg / 2.2)
        chord = sum(np.sin(2 * np.pi * f * seg) * w for f, w in
                    [(f0, 0.5), (f0 * 1.26, 0.3), (f0 * 1.5, 0.3), (f0 * 2, 0.15)])
        out[s0:s0 + len(seg)] += chord * env * 0.18
    # пульс
    beat = 60 / 96
    for i in range(int(total / beat)):
        s0 = int(i * beat * sr)
        seg = t[:int(0.18 * sr)]
        if s0 + len(seg) > n:
            break
        kick = np.sin(2 * np.pi * (55 + 90 * np.exp(-seg * 30)) * seg) * np.exp(-seg * 18)
        out[s0:s0 + len(seg)] += kick * 0.35
    # «поп» на появлениях
    for ct in cue_times:
        s0 = int(ct * sr)
        seg = t[:int(0.12 * sr)]
        if s0 + len(seg) > n:
            continue
        out[s0:s0 + len(seg)] += np.sin(2 * np.pi * 880 * seg) * np.exp(-seg * 40) * 0.25
    fade = int(1.0 * sr)
    out[int(total * sr) - fade:int(total * sr)] *= np.linspace(1, 0, fade)
    out = out[:int(total * sr)]
    out = out / (np.max(np.abs(out)) + 1e-9) * 0.7
    data = (out * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(data.tobytes())


# ---------- сборка ----------

def scene_duration(s):
    return float(s.get("dur", DUR[s["type"]]))


def render_frame(sc, scene_t, gt, total, i, n, bg, stars, A):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    stars.draw(d, gt)
    draw_chrome(d, A, gt, total, i, n)
    SCENES[sc["type"]](d, sc, scene_t, A)
    return img


def render(scn, out_path, preview_dir=None):
    A = hex2rgb(scn.get("accent", "#FFC93C"))
    seed = scn.get("id", "x")
    bg = make_bg(A, seed)
    stars = Stars(seed)
    scenes = scn["scenes"]
    durs = [scene_duration(s) for s in scenes]
    total = sum(durs)
    tmp = tempfile.mkdtemp(prefix="short_")
    parts, gt0 = [], 0.0
    for i, (sc, dur) in enumerate(zip(scenes, durs)):
        part = os.path.join(tmp, f"p{i:02d}.mp4")
        part_tmp = part[:-4] + ".tmp.mp4"
        frames = int(round(dur * FPS))
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset",
               "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", part_tmp]
        pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for fi in range(frames):
            st = fi / FPS
            img = render_frame(sc, st, gt0 + st, total, i, len(scenes), bg, stars, A)
            # короткий переход: затемнение в конце сцены
            fade = 0.25
            if st > dur - fade and i < len(scenes) - 1:
                k = (st - (dur - fade)) / fade
                img = Image.blend(img, bg, k * 0.85)
            pr.stdin.write(img.tobytes())
        pr.stdin.close()
        if pr.wait() != 0:
            raise RuntimeError("ffmpeg failed on scene %d" % i)
        os.replace(part_tmp, part)
        parts.append(part)
        gt0 += dur
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    cues, acc = [], 0.0
    for sc, dur in zip(scenes, durs):
        cues.append(acc + 0.05)
        if sc["type"] in ("compare", "scale"):
            cues += [acc + 0.8 + k * 0.6 for k in range(len(sc["items"]))]
        acc += dur
    wav = os.path.join(tmp, "a.wav")
    make_audio(wav, total, cues, seed)
    out_tmp = out_path[:-4] + ".tmp.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "128k", "-shortest", "-movflags", "+faststart", out_tmp], check=True)
    os.replace(out_tmp, out_path)
    for p in parts + [lst, wav]:
        os.remove(p)
    os.rmdir(tmp)
    return total


def preview(scn, times, out_dir):
    """Отдельные кадры для проверки: times — список (индекс_сцены, секунда)."""
    A = hex2rgb(scn.get("accent", "#FFC93C"))
    bg, stars = make_bg(A, scn.get("id", "x")), Stars(scn.get("id", "x"))
    scenes = scn["scenes"]
    total = sum(scene_duration(s) for s in scenes)
    paths = []
    for i, st in times:
        img = render_frame(scenes[i], st, st, total, i, len(scenes), bg, stars, A)
        p = os.path.join(out_dir, f"prev_{i}_{st}.png")
        img.save(p); paths.append(p)
    return paths


if __name__ == "__main__":
    scn = json.load(open(sys.argv[1], encoding="utf-8"))
    print("duration", render(scn, sys.argv[2]))
