from __future__ import annotations

from pydantic import BaseModel, Field


class SearchItem(BaseModel):
    id: int
    title: str
    description: str = ""
    downloads: int = 0
    uploader_name: str = "unknown"
    page_url: str
    season: int | None = None
    episode: int | None = None


class SearchResponse(BaseModel):
    total: int
    items: list[SearchItem] = Field(default_factory=list)


class LegacySearchRequest(BaseModel):
    query: str | None = None
    imdb_id: str | None = None
    tmdb_id: str | None = None


class LegacySearchItem(BaseModel):
    id: str
    title: str
    description: str = ""
    downloads: int = 0
    uploader_name: str = "unknown"


class LegacySearchResponse(BaseModel):
    items: list[LegacySearchItem] = Field(default_factory=list)


class SubtitleDownload(BaseModel):
    content: bytes
    media_type: str
    filename: str | None = None
