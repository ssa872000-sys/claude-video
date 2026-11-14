"""Одноразовый вход в YouTube-аккаунт. Запускать вручную: python3 auth.py"""
import json, os, sys

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
from google_auth_oauthlib.flow import Flow

HERE = os.path.dirname(os.path.abspath(__file__))
SECRET = os.path.join(HERE, "client_secret.json")
TOKEN = os.path.join(HERE, "token.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]


def main():
    if not os.path.exists(SECRET):
        print("\nВставь сюда ВСЁ содержимое файла client_secret...json (одна строка) и нажми Enter:\n")
        raw = ""
        while True:  # читаем строки, пока JSON не станет целым (вставка может быть в несколько строк)
            line = sys.stdin.readline()
            if not line:
                break
            raw += line
            try:
                json.loads(raw)
                break
            except ValueError:
                continue
        raw = json.dumps(json.loads(raw))  # проверка и в одну строку
        with open(SECRET, "w") as f:
            f.write(raw)
        os.chmod(SECRET, 0o600)
    flow = Flow.from_client_secrets_file(SECRET, scopes=SCOPES, redirect_uri="http://localhost:8080/")
    url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    print("\n1) Открой эту ссылку в браузере телефона и войди в аккаунт КАНАЛА:\n")
    print(url)
    print("\n2) Нажми «Продолжить» везде. В конце браузер покажет ошибку «Не удаётся открыть страницу» — это нормально.")
    print("3) Скопируй ПОЛНЫЙ адрес из адресной строки (начинается с http://localhost:8080/?state=...) и вставь сюда:\n")
    resp = sys.stdin.readline().strip()
    flow.fetch_token(authorization_response=resp)
    with open(TOKEN, "w") as f:
        f.write(flow.credentials.to_json())
    os.chmod(TOKEN, 0o600)
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", credentials=flow.credentials)
    ch = yt.channels().list(part="snippet", mine=True).execute()
    names = [i["snippet"]["title"] for i in ch.get("items", [])]
    print("\nГОТОВО! Подключён канал:", ", ".join(names) or "(не найден — проверь аккаунт)")


if __name__ == "__main__":
    main()
