"""Один запуск: взять следующую тему -> сделать видео -> выложить на YouTube.

  python3 run.py            — обычный запуск (так вызывает расписание)
  python3 run.py --dry      — только сделать видео, не выкладывать
  python3 run.py --private  — выложить как приватное (для проверки)
"""
import datetime, fcntl, glob, json, os, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render

BANK = os.path.join(HERE, "bank")
STATE = os.path.join(HERE, "state")
OUT = os.path.join(HERE, "out")
USED = os.path.join(STATE, "used.json")
LOG = os.path.join(STATE, "run.log")
TOKEN = os.path.join(HERE, "token.json")


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_used():
    if os.path.exists(USED):
        return json.load(open(USED, encoding="utf-8"))
    return {}


def save_used(u):
    tmp = USED + ".tmp"
    json.dump(u, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, USED)


def next_scenario(used):
    for p in sorted(glob.glob(os.path.join(BANK, "*.json"))):
        sid = os.path.splitext(os.path.basename(p))[0]
        if sid not in used:
            return sid, json.load(open(p, encoding="utf-8"))
    if os.environ.get("ANTHROPIC_API_KEY"):
        import gen
        log("Банк закончился — придумываю новую тему через Claude API")
        p = gen.generate([v.get("title", "") for v in used.values()])
        sid = os.path.splitext(os.path.basename(p))[0]
        return sid, json.load(open(p, encoding="utf-8"))
    return None, None


def upload(path, scn, privacy):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials.from_authorized_user_file(TOKEN)
    if not creds.valid:
        creds.refresh(Request())
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = {
        "snippet": {"title": scn["title"][:100], "description": scn.get("description", ""),
                    "tags": scn.get("tags", [])[:15], "categoryId": "27",
                    "defaultLanguage": "ru", "defaultAudioLanguage": "ru"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": False},
    }
    media = MediaFileUpload(path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, tries = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except Exception:
            tries += 1
            if tries > 5:
                raise
            time.sleep(10 * tries)
    vid = resp["id"]
    # проверяем реальный статус (YouTube может принудительно сделать видео приватным)
    st = yt.videos().list(part="status", id=vid).execute()["items"][0]["status"]
    return vid, st.get("privacyStatus")


def main():
    os.makedirs(STATE, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    lock = open(os.path.join(STATE, "lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("Уже идёт другой запуск — выхожу")
        return
    dry = "--dry" in sys.argv
    privacy = "private" if "--private" in sys.argv else "public"
    used = load_used()
    sid, scn = next_scenario(used)
    if not scn:
        log("ТЕМЫ ЗАКОНЧИЛИСЬ. Добавь новые сценарии в bank/ или ключ ANTHROPIC_API_KEY в config.env")
        return
    out = os.path.join(OUT, f"{sid}.mp4")
    log(f"Делаю видео {sid}: {scn['title']}")
    dur = render.render(scn, out)
    log(f"Видео готово ({dur:.0f} сек): {out}")
    if dry:
        return
    vid, real = upload(out, scn, privacy)
    log(f"ВЫЛОЖЕНО: https://youtube.com/shorts/{vid}  (статус: {real})")
    if privacy == "public" and real != "public":
        log("ВНИМАНИЕ: YouTube сделал видео приватным — нужен аудит Google API (см. README)")
    used[sid] = {"title": scn["title"], "video": vid, "status": real,
                 "at": datetime.datetime.now().isoformat(timespec="minutes")}
    save_used(used)
    # храним только 3 последних файла, чтобы не забивать диск
    for p in sorted(glob.glob(os.path.join(OUT, "*.mp4")), key=os.path.getmtime)[:-3]:
        os.remove(p)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        os.makedirs(STATE, exist_ok=True)
        log("ОШИБКА:\n" + traceback.format_exc())
        sys.exit(1)
