#!/bin/bash
# Установка автопостинга Shorts на сервер Ubuntu. Запуск:  bash install.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
echo "=== 1/5 Ставлю программы (1–3 минуты) ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip ffmpeg git cron >/dev/null
timedatectl set-timezone Europe/Moscow 2>/dev/null || ln -sf /usr/share/zoneinfo/Europe/Moscow /etc/localtime
echo "=== 2/5 Ставлю библиотеки Python ==="
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt
mkdir -p state out
[ -f config.env ] || cat > config.env <<'CFG'
# Необязательно: ключ Claude API — тогда темы будут придумываться автоматически, когда закончится банк.
ANTHROPIC_API_KEY=
CFG
chmod +x cron.sh
echo "=== 3/5 Ставлю расписание: каждый день 12:00 и 19:00 по Москве ==="
( crontab -l 2>/dev/null | grep -v autoshorts_cron ; \
  echo "0 12 * * * $DIR/cron.sh # autoshorts_cron" ; \
  echo "0 19 * * * $DIR/cron.sh # autoshorts_cron" ) | crontab -
systemctl enable --now cron >/dev/null 2>&1 || true
echo "=== 4/5 Пробное видео (без загрузки) ==="
./venv/bin/python run.py --dry
echo "=== 5/5 Вход в YouTube ==="
if [ ! -f token.json ]; then ./venv/bin/python auth.py; fi
echo
echo "ВСЁ ГОТОВО. Видео будут выходить сами в 12:00 и 19:00 (МСК)."
echo "Выложить первое видео прямо сейчас:  cd $DIR && ./venv/bin/python run.py"
