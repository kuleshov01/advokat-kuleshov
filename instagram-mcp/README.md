# instagram-mcp (локальный)

Публикация фото, каруселей и Reels из Claude. Работает на твоём компьютере, файлы берутся с диска.
Использует неофициальный API (instagrapi) — риск ограничений аккаунта остаётся.

## Установка
```bash
cd instagram-mcp
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Подключение к Claude Code
```bash
claude mcp add instagram \
  -e IG_MAIN_USER=твой_логин -e IG_MAIN_PASS=пароль \
  -- /полный/путь/instagram-mcp/.venv/bin/python /полный/путь/instagram-mcp/server.py
```
Для Claude Desktop — тот же `command`/`args`/`env` в `claude_desktop_config.json`.
Несколько аккаунтов: добавь `IG_ВТОРОЙ_USER` / `IG_ВТОРОЙ_PASS` (имя аккаунта в вызове — `main`, `второй`).
Если включена 2FA через приложение: `IG_MAIN_2FA=<TOTP-секрет>`.

## Использование
Попроси: «опубликуй рилс ~/video/reel.mp4 в main с подписью …». Сначала придёт черновик,
публикация — только после `confirm=true`.

## Советы
- Первый вход делай с этого же компьютера и IP, подтверди вход в приложении Instagram.
- Сессия сохраняется в `~/.instagram-mcp/` (не логинится каждый раз).
- Не публикуй чаще пары раз в день. Начни с тестового аккаунта.
