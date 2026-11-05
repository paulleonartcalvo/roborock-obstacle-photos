"""HTTP endpoint that serves saved photos."""

from __future__ import annotations

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView

from .const import DOMAIN
from .manager import async_get_manager

PHOTO_URL = f"/api/{DOMAIN}/photo/{{duid}}/{{photo_id}}"


def photo_url(duid: str, photo_id: str) -> str:
    """Return the URL of a saved photo."""
    return PHOTO_URL.format(duid=duid, photo_id=photo_id)


class ObstaclePhotoView(HomeAssistantView):
    """Serve one saved photo; ids are looked up, never used as paths."""

    url = PHOTO_URL
    name = f"api:{DOMAIN}:photo"
    requires_auth = True

    async def get(
        self, request: web.Request, duid: str, photo_id: str
    ) -> web.StreamResponse:
        """Return the JPEG."""
        manager = async_get_manager(request.app[KEY_HASS], duid)
        if manager is None or (record := manager.photo(photo_id)) is None:
            raise web.HTTPNotFound
        return web.FileResponse(
            record["path"], headers={"Cache-Control": "private, max-age=86400"}
        )
