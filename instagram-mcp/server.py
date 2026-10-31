"""Локальный MCP-сервер для публикации в Instagram через instagrapi.

Запускается на твоём компьютере (stdio), логин идёт с твоего IP.
Неофициальный API: нарушает условия Instagram, используй осознанно.
"""
import os
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import LoginRequired
from mcp.server.fastmcp import FastMCP

SESSION_DIR = Path(os.environ.get("IG_SESSION_DIR", Path.home() / ".instagram-mcp"))
SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

mcp = FastMCP("instagram")
_clients: dict[str, Client] = {}


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


@mcp.tool()
def list_accounts() -> list[str]:
    """Аккаунты, настроенные через переменные окружения IG_<NAME>_USER."""
    return sorted(k[3:-5].lower() for k in os.environ if k.startswith("IG_") and k.endswith("_USER"))


if __name__ == "__main__":
    mcp.run()
