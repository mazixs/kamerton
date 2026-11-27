"""Раздача собранного Vite интерфейса и его публичных ресурсов входа."""

import json
from pathlib import Path, PurePosixPath

from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles


WEB_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class WebAssets(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code in {200, 304}:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def page(name: str, cache_control: str):
    path = WEB_ROOT / name
    if path.is_file():
        return FileResponse(path, media_type="text/html", headers={"Cache-Control": cache_control})
    return HTMLResponse("Соберите веб-интерфейс командой npm run build в каталоге frontend.",
                        status_code=503, headers={"Cache-Control": "no-store"})


def public_login_assets() -> frozenset[str]:
    """Разрешаем до авторизации только статические зависимости страницы входа."""
    try:
        manifest = json.loads((WEB_ROOT / ".vite" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    paths, visited = set(), set()

    def collect(key):
        if key in visited or key not in manifest:
            return
        visited.add(key)
        entry = manifest[key]
        for path in [entry.get("file"), *entry.get("css", []), *entry.get("assets", [])]:
            if isinstance(path, str) and path.startswith("assets/") and ".." not in PurePosixPath(path).parts:
                paths.add("/static/" + path)
        for imported in entry.get("imports", []):
            collect(imported)

    collect("login.html")
    return frozenset(paths)
