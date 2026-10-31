"""Локальный MCP-сервер для публикации в Instagram через instagrapi.

Запускается на твоём компьютере (stdio), логин идёт с твоего IP.
Неофициальный API: нарушает условия Instagram, используй осознанно.
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import LoginRequired
from mcp.server.fastmcp import FastMCP

import queue_db

MIN_GAP = float(os.environ.get("IG_MIN_GAP_SECONDS", 600))  # пауза между публикациями одного аккаунта

SESSION_DIR = Path(os.environ.get("IG_SESSION_DIR", Path.home() / ".instagram-mcp"))
SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

mcp = FastMCP("instagram")
_clients: dict[str, Client] = {}
_publish_lock = threading.Lock()


def _login(name: str) -> Client:
    """Аккаунт `name` берётся из IG_<NAME>_USER / IG_<NAME>_PASS (+ IG_<NAME>_2FA, TOTP-секрет)."""
    if name in _clients:
        return _clients[name]
    key = name.upper()
    user = os.environ[f"IG_{key}_USER"]
    password = os.environ[f"IG_{key}_PASS"]
    totp_secret = os.environ.get(f"IG_{key}_2FA", "")
    session_file = SESSION_DIR / f"{name}.json"

    cl = Client()
    cl.delay_range = [2, 6]  # паузы между запросами
    if session_file.exists():
        cl.load_settings(session_file)
    try:
        cl.login(user, password, verification_code=cl.totp_generate_code(totp_secret) if totp_secret else "")
        cl.get_timeline_feed()  # проверка, что сессия жива
    except LoginRequired:
        session_file.unlink(missing_ok=True)
        cl = Client()
        cl.delay_range = [2, 6]
        cl.login(user, password, verification_code=cl.totp_generate_code(totp_secret) if totp_secret else "")
    cl.dump_settings(session_file)
    session_file.chmod(0o600)
    _clients[name] = cl
    return cl


def _check(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Файл не найден: {p}")
    return p


@mcp.tool()
def publish_photo(account: str, photo_path: str, caption: str = "", confirm: bool = False) -> str:
    """Опубликовать фото. Без confirm=true только показывает, что будет опубликовано."""
    p = _check(photo_path)
    if not confirm:
        return f"[черновик] {account}: фото {p}\nПодпись: {caption}\nДля публикации вызови с confirm=true."
    media = _login(account).photo_upload(p, caption)
    return f"Опубликовано: https://www.instagram.com/p/{media.code}/"


@mcp.tool()
def publish_carousel(account: str, photo_paths: list[str], caption: str = "", confirm: bool = False) -> str:
    """Опубликовать карусель (2-10 фото)."""
    paths = [_check(p) for p in photo_paths]
    if not 2 <= len(paths) <= 10:
        raise ValueError("В карусели должно быть от 2 до 10 файлов")
    if not confirm:
        return f"[черновик] {account}: карусель из {len(paths)} фото\nПодпись: {caption}\nДля публикации вызови с confirm=true."
    media = _login(account).album_upload(paths, caption)
    return f"Опубликовано: https://www.instagram.com/p/{media.code}/"


@mcp.tool()
def publish_reel(account: str, video_path: str, caption: str = "", cover_path: str = "", confirm: bool = False) -> str:
    """Опубликовать Reels (вертикальное видео mp4, до 90 с)."""
    v = _check(video_path)
    cover = _check(cover_path) if cover_path else None
    if not confirm:
        return f"[черновик] {account}: рилс {v}\nПодпись: {caption}\nДля публикации вызови с confirm=true."
    media = _login(account).clip_upload(v, caption, thumbnail=cover)
    return f"Опубликовано: https://www.instagram.com/reel/{media.code}/"


def _publish(account: str, kind: str, paths: list[str], caption: str, cover: str) -> str:
    with _publish_lock:
        cl = _login(account)
        if kind == "photo":
            media = cl.photo_upload(Path(paths[0]), caption)
            return f"https://www.instagram.com/p/{media.code}/"
        if kind == "carousel":
            media = cl.album_upload([Path(p) for p in paths], caption)
            return f"https://www.instagram.com/p/{media.code}/"
        if kind == "reel":
            media = cl.clip_upload(Path(paths[0]), caption, thumbnail=Path(cover) if cover else None)
            return f"https://www.instagram.com/reel/{media.code}/"
    raise ValueError(f"Неизвестный тип: {kind}")


def run_due() -> int:
    """Публикует просроченные посты из очереди. Возвращает число обработанных."""
    n = 0
    while (post := queue_db.claim_due(MIN_GAP)) is not None:
        try:
            url = _publish(post["account"], post["kind"], json.loads(post["paths"]), post["caption"], post["cover"])
            queue_db.finish(post["id"], True, url)
        except Exception as e:  # без автоповторов: повторные логины рискованнее
            queue_db.finish(post["id"], False, f"{type(e).__name__}: {e}")
        n += 1
    return n


def _worker_loop() -> None:
    while True:
        try:
            run_due()
        except Exception:
            pass
        time.sleep(30)


def _parse_when(when: str) -> float:
    """'2026-11-02 18:30' (местное время компьютера) или ISO с часовым поясом."""
    dt = datetime.fromisoformat(when.strip().replace("T", " "))
    ts = dt.timestamp()
    if ts <= time.time():
        raise ValueError("Время публикации должно быть в будущем")
    return ts


@mcp.tool()
def schedule_post(
    account: str,
    kind: str,
    paths: list[str],
    when: str,
    caption: str = "",
    cover_path: str = "",
) -> str:
    """Запланировать публикацию. kind: photo | carousel | reel. when: '2026-11-02 18:30' по местному времени.
    Файлы должны оставаться на месте до публикации. Для photo/reel — один путь, для carousel — 2-10."""
    if kind not in ("photo", "carousel", "reel"):
        raise ValueError("kind должен быть photo, carousel или reel")
    if account not in list_accounts():
        raise ValueError(f"Неизвестный аккаунт {account!r}. Доступны: {list_accounts()}")
    files = [str(_check(p).resolve()) for p in paths]
    if kind in ("photo", "reel") and len(files) != 1:
        raise ValueError("Для photo и reel нужен ровно один файл")
    if kind == "carousel" and not 2 <= len(files) <= 10:
        raise ValueError("В карусели должно быть от 2 до 10 файлов")
    cover = str(_check(cover_path).resolve()) if cover_path else ""
    ts = _parse_when(when)
    pid = queue_db.add(account, kind, files, caption, cover, ts)
    return f"Запланировано #{pid}: {account}, {kind}, {datetime.fromtimestamp(ts):%Y-%m-%d %H:%M}"


@mcp.tool()
def list_scheduled(status: str = "pending") -> list[dict]:
    """Очередь: status = pending | done | failed | cancelled | running."""
    out = []
    for r in queue_db.list_posts(status):
        out.append(
            {
                "id": r["id"],
                "account": r["account"],
                "kind": r["kind"],
                "when": f"{datetime.fromtimestamp(r['run_at']):%Y-%m-%d %H:%M}",
                "files": json.loads(r["paths"]),
                "caption": r["caption"][:80],
                "result": r["result"],
            }
        )
    return out


@mcp.tool()
def cancel_scheduled(post_id: int) -> str:
    """Отменить запланированную публикацию (пока она не началась)."""
    return "Отменено" if queue_db.cancel(post_id) else "Не найдено или уже обработано"


@mcp.tool()
def list_accounts() -> list[str]:
    """Аккаунты, настроенные через переменные окружения IG_<NAME>_USER."""
    return sorted(k[3:-5].lower() for k in os.environ if k.startswith("IG_") and k.endswith("_USER"))


if __name__ == "__main__":
    if os.environ.get("IG_EMBEDDED_WORKER", "1") == "1":
        threading.Thread(target=_worker_loop, daemon=True).start()
    mcp.run()
