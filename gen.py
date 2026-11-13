"""Новая тема через Claude API (нужен ANTHROPIC_API_KEY в config.env).
Вызывается из run.py автоматически, когда банк тем закончился."""
import datetime, json, os, re, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
ACC = ["#4CC9F0", "#F72585", "#7CFC9A", "#FF7B54", "#B388FF", "#FFD93D", "#00F5D4", "#FFB627"]

EXAMPLE = json.load(open(os.path.join(HERE, "bank", "001.json"), encoding="utf-8"))

PROMPT = """Ты пишешь сценарий для YouTube Shorts канала «Факты, которые видно» (русский язык).
Нужен ОДИН новый удивительный, но ПРОВЕРЕННЫЙ факт (наука, космос, тело, животные, география, история, числа).
Только общеизвестные цифры из надёжных источников; если не уверен в числе — выбери другую тему.
Не повторяй эти темы: {used}

Верни ТОЛЬКО JSON такого вида (пример):
{example}

Правила:
- 4–6 сцен; первая — "hook" (цепляющий вопрос/утверждение до 10 слов), последняя — "outro".
- Типы сцен: hook(text, sub?), text(text), count(value, unit, caption?, decimals?),
  compare(title, items[label,value,text?,hl?], caption?) — 2–4 строки,
  dots(title, highlight, total=100, caption?), scale(title, items[label,value,text?,hl?], shape="bar"|"circle", caption?).
- *звёздочками* выделяй 1–2 ключевых слова. Тексты короткие.
- title — до 70 символов + " #shorts"; description — 2 строки + хэштеги; tags — 6–10 слов.
"""


def _valid(s):
    assert isinstance(s.get("scenes"), list) and 3 <= len(s["scenes"]) <= 7
    assert s["scenes"][0]["type"] == "hook" and s["scenes"][-1]["type"] == "outro"
    for sc in s["scenes"]:
        assert sc["type"] in ("hook", "text", "count", "compare", "dots", "scale", "outro")
        if sc["type"] in ("compare", "scale"):
            assert 2 <= len(sc["items"]) <= 4 and all(float(i["value"]) > 0 for i in sc["items"])
        if sc["type"] == "count":
            float(sc["value"])
        if sc["type"] == "dots":
            assert 0 <= int(sc["highlight"]) <= int(sc.get("total", 100)) <= 100
    assert s.get("title")


def generate(used_titles):
    import anthropic
    import render
    client = anthropic.Anthropic()
    ex = {k: EXAMPLE[k] for k in ("title", "description", "tags", "scenes")}
    prompt = PROMPT.format(used="; ".join(used_titles[-150:]) or "—",
                           example=json.dumps(ex, ensure_ascii=False))
    last = None
    for _ in range(3):
        msg = client.messages.create(model=MODEL, max_tokens=2500,
                                     messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        try:
            s = json.loads(m.group(0))
            _valid(s)
            sid = "gen_" + datetime.datetime.now().strftime("%Y%m%d_%H%M")
            s["id"] = sid
            s["accent"] = ACC[hash(sid) % len(ACC)]
            with tempfile.TemporaryDirectory() as d:  # пробный кадр каждой сцены
                render.preview(s, [(i, 2.0) for i in range(len(s["scenes"]))], d)
            p = os.path.join(HERE, "bank", sid + ".json")
            json.dump(s, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            return p
        except Exception as e:
            last = e
    raise RuntimeError(f"Claude API не дал корректный сценарий: {last}")
