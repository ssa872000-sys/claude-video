#!/bin/bash
# Вызывается расписанием 2 раза в день. Небольшая случайная задержка — чтобы время выхода не было «роботским».
cd "$(dirname "$0")"
git pull -q --ff-only >/dev/null 2>&1 || true   # подтягиваем новые темы и исправления
[ -f config.env ] && set -a && . ./config.env && set +a
sleep $((RANDOM % 900))
./venv/bin/python run.py >> state/cron.out 2>&1
