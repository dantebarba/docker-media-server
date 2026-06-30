from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Settings


@dataclass
class TmdbMetadata:
    title: str | None = None
    year: int | None = None


def _extract_year(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    if len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def _headers(settings: Settings) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": settings.user_agent,
    }
    if settings.tmdb_read_access_token:
        headers["Authorization"] = f"Bearer {settings.tmdb_read_access_token}"
    return headers


def _params(settings: Settings) -> dict[str, str]:
    params = {"language": "en-US"}
    if settings.tmdb_api_key and not settings.tmdb_read_access_token:
        params["api_key"] = settings.tmdb_api_key
    return params


async def resolve_tmdb_metadata(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    tmdb_id: str,
    video_type: str,
) -> TmdbMetadata:
    if not settings.tmdb_api_key and not settings.tmdb_read_access_token:
        return TmdbMetadata()

    endpoint = "movie" if video_type == "movie" else "tv"
    response = await client.get(
        f"{settings.tmdb_base_url}/{endpoint}/{tmdb_id}",
        headers=_headers(settings),
        params=_params(settings),
        timeout=15.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return TmdbMetadata()

    if video_type == "movie":
        return TmdbMetadata(
            title=str(payload.get("title") or payload.get("original_title") or "").strip() or None,
            year=_extract_year(payload.get("release_date")),
        )

    return TmdbMetadata(
        title=str(payload.get("name") or payload.get("original_name") or "").strip() or None,
        year=_extract_year(payload.get("first_air_date")),
    )
