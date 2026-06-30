from __future__ import annotations

import logging
import re

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import Response

from .auth import require_api_token
from .config import get_settings
from .models import LegacySearchRequest, LegacySearchResponse, SearchResponse
from .subdivx import SubdivxBridge


settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(title="SubX Bridge", version="0.1.0")
bridge = SubdivxBridge(settings)
EPISODE_QUERY_RE = re.compile(r"\bS\d{1,2}E\d{1,3}\b|\b\d{1,2}x\d{1,3}\b", re.IGNORECASE)


def _resolve_video_type(
    *,
    video_type: str | None,
    query: str | None,
    imdb_id: str | None,
) -> str:
    if video_type in {"episode", "movie"}:
        return video_type
    if query and EPISODE_QUERY_RE.search(query):
        return "episode"
    return "movie"


def _to_legacy_search_response(response: SearchResponse) -> LegacySearchResponse:
    return LegacySearchResponse(
        items=[
            {
                "id": str(item.id),
                "title": item.title,
                "description": item.description,
                "downloads": item.downloads,
                "uploader_name": item.uploader_name,
            }
            for item in response.items
        ]
    )


@app.on_event("startup")
async def log_runtime_configuration() -> None:
    logger.info(
        "SubX Bridge startup: api_keys=%s cookie_header=%s cf_clearance=%s sdx=%s user_agent_mode=%s",
        len(settings.api_keys),
        "set" if settings.cookie_header.strip() else "unset",
        "set" if settings.cf_clearance.strip() else "unset",
        "set" if settings.sdx_cookie.strip() else "unset",
        "custom" if settings.has_custom_user_agent else "default",
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/subtitles/search")
async def search_subtitles(
    _: str = Depends(require_api_token),
    limit: int = Query(default=200, ge=1, le=500),
    video_type: str | None = Query(default=None, pattern="^(episode|movie)$"),
    imdb_id: str | None = Query(default=None),
    tmdb_id: str | None = Query(default=None),
    title: str | None = Query(default=None),
    query: str | None = Query(default=None),
    year: int | None = Query(default=None),
) -> SearchResponse | LegacySearchResponse:
    try:
        resolved_title = title or query
        resolved_video_type = _resolve_video_type(video_type=video_type, query=query, imdb_id=imdb_id)
        items = await bridge.search(
            title=resolved_title,
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
            video_type=resolved_video_type,
            year=year,
            limit=limit,
        )
        response = SearchResponse(total=len(items), items=items)
        if query is not None and title is None and video_type is None:
            return _to_legacy_search_response(response)
        return response
    except HTTPException:
        raise
    except httpx.HTTPStatusError as ex:
        upstream_body = ex.response.text[:400].strip()
        logger.warning(
            "Search upstream HTTP error: status=%s url=%s body=%r",
            ex.response.status_code,
            ex.request.url,
            upstream_body,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Upstream request failed.",
                "upstream_status": ex.response.status_code,
                "upstream_url": str(ex.request.url),
                "upstream_body": upstream_body,
            },
        ) from ex
    except Exception as ex:
        logger.exception("Search failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {ex}",
        ) from ex


@app.get("/api/subtitles/{subtitle_id}/download")
async def download_subtitle(
    subtitle_id: int,
    _: str = Depends(require_api_token),
) -> Response:
    try:
        result = await bridge.download(subtitle_id)
    except httpx.HTTPStatusError as ex:
        upstream_body = ex.response.text[:400].strip()
        logger.warning(
            "Download upstream HTTP error: subtitle_id=%s status=%s url=%s body=%r",
            subtitle_id,
            ex.response.status_code,
            ex.request.url,
            upstream_body,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Upstream download failed.",
                "upstream_status": ex.response.status_code,
                "upstream_url": str(ex.request.url),
                "upstream_body": upstream_body,
            },
        ) from ex
    except Exception as ex:
        logger.exception("Download failed for subtitle_id=%s", subtitle_id)
        raise HTTPException(status_code=500, detail=str(ex)) from ex

    headers: dict[str, str] = {}
    if result.filename:
        headers["Content-Disposition"] = f'attachment; filename="{result.filename}"'
    return Response(content=result.content, media_type=result.media_type, headers=headers)


@app.post("/search", response_model=LegacySearchResponse)
async def legacy_search_subtitles(
    payload: LegacySearchRequest | None = Body(default=None),
    _: str = Depends(require_api_token),
) -> LegacySearchResponse:
    payload = payload or LegacySearchRequest()
    query = payload.query
    response = await search_subtitles(
        _="",
        limit=200,
        video_type=_resolve_video_type(video_type=None, query=query, imdb_id=payload.imdb_id),
        imdb_id=payload.imdb_id,
        tmdb_id=payload.tmdb_id,
        title=query,
        query=None,
        year=None,
    )
    if isinstance(response, LegacySearchResponse):
        return response
    return _to_legacy_search_response(response)


@app.get("/download/{subtitle_id}")
async def legacy_download_subtitle(
    subtitle_id: int,
    _: str = Depends(require_api_token),
) -> Response:
    return await download_subtitle(subtitle_id=subtitle_id, _="")
