from __future__ import annotations

from json import JSONDecodeError
import logging
import re
import asyncio
import unicodedata
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings
from .imdb import resolve_imdb_metadata
from .models import SearchItem, SubtitleDownload
from .tmdb import resolve_tmdb_metadata


logger = logging.getLogger(__name__)

VERSION_RE = re.compile(r"(?:index-min\.js|sdx-min\.css)\?v=([0-9.]+)", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
SEARCH_MIN_INTERVAL_SECONDS = 5.0
EPISODE_PATTERNS = [
    re.compile(r"\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b", re.IGNORECASE),
]
SEASON_PACK_PATTERNS = [
    re.compile(r"\bS(?P<season>\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\btemporada\s*(?P<season>\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bseason\s*(?P<season>\d{1,2})\b", re.IGNORECASE),
]


@dataclass
class SearchContext:
    video_type: str
    title: str | None = None
    year: int | None = None
    season: int | None = None
    episode: int | None = None


class SubdivxBridge:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._version_suffix: str | None = None
        self._version_suffix_expiration = 0.0
        self._search_lock = asyncio.Lock()
        self._last_search_at = 0.0

    def _default_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.1",
            "Origin": self._settings.subdivx_base_url,
            "Referer": f"{self._settings.subdivx_base_url}/",
            "User-Agent": self._settings.user_agent,
            "X-Requested-With": "XMLHttpRequest",
        }
        cookie_header = self._settings.combined_cookie_header
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    async def _get_version_suffix(self, client: httpx.AsyncClient) -> str:
        if self._version_suffix and monotonic() < self._version_suffix_expiration:
            return self._version_suffix

        response = await client.get(
            f"{self._settings.subdivx_base_url}/",
            headers=self._default_headers(),
            timeout=20.0,
        )
        response.raise_for_status()
        match = VERSION_RE.search(response.text)
        if not match:
            raise RuntimeError("Could not determine Subdivx frontend version.")

        self._version_suffix = match.group(1).replace(".", "", 16)
        self._version_suffix_expiration = monotonic() + 600
        return self._version_suffix

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        response = await client.get(
            f"{self._settings.subdivx_base_url}/inc/gt.php?gt=1",
            headers=self._default_headers(),
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("token") if isinstance(payload, dict) else None
        if not token:
            raise RuntimeError(f"Invalid Subdivx token response: {payload!r}")
        return str(token)

    @staticmethod
    def _normalize_query(query: str) -> str:
        return re.sub(r"\s+", " ", query.replace(".", " ").replace("_", " ")).strip()

    @classmethod
    def _extract_context_from_title(cls, title: str) -> tuple[str, int | None, int | None]:
        normalized = cls._normalize_query(title)
        if not normalized:
            return "", None, None

        season: int | None = None
        episode: int | None = None
        cleaned = normalized

        for pattern in EPISODE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                season = int(match.group("season"))
                episode = int(match.group("episode"))
                cleaned = cls._normalize_query(pattern.sub(" ", normalized, count=1))
                return cleaned, season, episode

        for pattern in SEASON_PACK_PATTERNS:
            match = pattern.search(normalized)
            if match:
                season = int(match.group("season"))
                cleaned = cls._normalize_query(pattern.sub(" ", normalized, count=1))
                return cleaned, season, None

        return normalized, None, None

    @classmethod
    def _ascii_fold(cls, query: str) -> str:
        normalized = unicodedata.normalize("NFKD", query)
        folded = normalized.encode("ascii", "ignore").decode("ascii")
        return cls._normalize_query(folded)

    @classmethod
    def _title_variants(cls, title: str) -> list[str]:
        normalized = cls._normalize_query(title)
        if not normalized:
            return []

        candidates = [normalized]

        trailing_year_stripped = re.sub(r"\s+\(?((?:19|20)\d{2})\)?$", "", normalized).strip()
        if trailing_year_stripped and trailing_year_stripped != normalized:
            candidates.append(trailing_year_stripped)

        # Titles like "Maze Runner: La cura mortal" often work better with the base title too.
        for source in list(candidates):
            for separator in (" : ", ": ", " - ", " – ", " — "):
                if separator in source:
                    head = cls._normalize_query(source.split(separator, 1)[0])
                    if head and len(head) >= 4:
                        candidates.append(head)

        for source in list(candidates):
            if ":" in source:
                head = cls._normalize_query(source.split(":", 1)[0])
                if head and len(head) >= 4:
                    candidates.append(head)

        ascii_folded = cls._ascii_fold(normalized)
        if ascii_folded and ascii_folded != normalized:
            candidates.append(ascii_folded)

            trailing_year_ascii = re.sub(r"\s+\(?((?:19|20)\d{2})\)?$", "", ascii_folded).strip()
            if trailing_year_ascii and trailing_year_ascii != ascii_folded:
                candidates.append(trailing_year_ascii)

            for separator in (" : ", ": ", " - ", " – ", " — "):
                if separator in ascii_folded:
                    head = cls._normalize_query(ascii_folded.split(separator, 1)[0])
                    if head and len(head) >= 4:
                        candidates.append(head)

        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in candidates:
            key = candidate.lower()
            if candidate and key not in seen:
                seen.add(key)
                ordered.append(candidate)
        return ordered[:4]

    def _build_queries(self, context: SearchContext) -> list[str]:
        title_variants = self._title_variants(context.title or "")
        if not title_variants:
            return []

        queries: list[str] = []
        if context.video_type == "episode":
            for title in title_variants[:2]:
                if context.season is not None and context.episode is not None:
                    queries.append(f"{title} S{context.season:02d}E{context.episode:02d}")
                    queries.append(f"{title} {context.season}x{context.episode:02d}")
                if context.season is not None:
                    queries.append(f"{title} S{context.season:02d}")
                queries.append(title)
        else:
            for title in title_variants:
                if context.year:
                    queries.append(f"{title} {context.year}")
                queries.append(title)

        seen: set[str] = set()
        result: list[str] = []
        for query in queries:
            normalized = self._normalize_query(query)
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower())
                result.append(normalized)
        return result

    @staticmethod
    def _strip_html(text: str | None) -> str:
        if not text:
            return ""
        return HTML_TAG_RE.sub("", text).strip()

    @staticmethod
    def _extract_season_episode(text: str) -> tuple[int | None, int | None]:
        for pattern in EPISODE_PATTERNS:
            match = pattern.search(text)
            if match:
                return int(match.group("season")), int(match.group("episode"))

        for pattern in SEASON_PACK_PATTERNS:
            match = pattern.search(text)
            if match:
                return int(match.group("season")), None

        return None, None

    @staticmethod
    def _score_item(item: dict[str, Any], context: SearchContext, query: str) -> int:
        haystack = f"{item.get('titulo', '')} {item.get('descripcion', '')}".lower()
        score = 0
        for token in query.lower().split():
            if token in haystack:
                score += 10

        parsed_season, parsed_episode = SubdivxBridge._extract_season_episode(haystack)
        if context.season is not None and parsed_season == context.season:
            score += 100
        if context.episode is not None and parsed_episode == context.episode:
            score += 100
        if context.year and str(context.year) in haystack:
            score += 40

        downloads = int(item.get("descargas") or 0)
        comments = int(item.get("comentarios") or 0)
        score += min(downloads // 25, 50)
        score += min(comments * 2, 10)
        return score

    async def _run_single_search(
        self,
        client: httpx.AsyncClient,
        token: str,
        version_suffix: str,
        query: str,
    ) -> list[dict[str, Any]]:
        form_data = {
            "tabla": "resultados",
            "filtros": "",
            f"buscar{version_suffix}": query,
            "token": token,
        }

        async with self._search_lock:
            elapsed = monotonic() - self._last_search_at
            if elapsed < SEARCH_MIN_INTERVAL_SECONDS:
                await asyncio.sleep(SEARCH_MIN_INTERVAL_SECONDS - elapsed)

            response = await client.post(
                f"{self._settings.subdivx_base_url}/inc/ajax.php",
                headers=self._default_headers() | {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                content=urlencode(form_data).encode("utf-8"),
                timeout=30.0,
            )
            self._last_search_at = monotonic()

            response.raise_for_status()
            try:
                payload = response.json()
            except JSONDecodeError:
                body_preview = response.text[:400].strip()
                logger.warning(
                    "Subdivx returned non-JSON search payload for query '%s': status=%s content_type=%r body=%r",
                    query,
                    response.status_code,
                    response.headers.get("content-type"),
                    body_preview,
                )
                return []
            if not isinstance(payload, dict):
                logger.warning(
                    "Subdivx returned unexpected search payload type for query '%s': %r",
                    query,
                    type(payload).__name__,
                )
                return []
            items = payload.get("aaData")
            return items if isinstance(items, list) else []

    async def _search_uncached(
        self,
        *,
        title: str | None,
        imdb_id: str | None,
        tmdb_id: str | None,
        video_type: str,
        year: int | None,
        limit: int,
    ) -> list[SearchItem]:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            context = SearchContext(video_type=video_type, title=title, year=year)

            if context.video_type == "episode" and context.title:
                cleaned_title, parsed_season, parsed_episode = self._extract_context_from_title(context.title)
                context.title = cleaned_title or context.title
                context.season = context.season or parsed_season
                context.episode = context.episode or parsed_episode

            if not context.title and tmdb_id:
                metadata = await resolve_tmdb_metadata(
                    client,
                    self._settings,
                    tmdb_id=tmdb_id,
                    video_type=video_type,
                )
                context.title = metadata.title
                context.year = context.year or metadata.year
                logger.info(
                    "Resolved tmdb_id=%s to title=%s year=%s",
                    tmdb_id,
                    context.title,
                    context.year,
                )

            if not context.title and imdb_id:
                metadata = await resolve_imdb_metadata(client, self._settings, imdb_id)
                context.title = metadata.title
                context.year = context.year or metadata.year
                context.season = metadata.season
                context.episode = metadata.episode
                logger.info(
                    "Resolved imdb_id=%s to title=%s year=%s season=%s episode=%s",
                    imdb_id,
                    context.title,
                    context.year,
                    context.season,
                    context.episode,
                )

            queries = self._build_queries(context)
            if not queries:
                return []

            version_suffix = await self._get_version_suffix(client)
            token = await self._get_token(client)

            ranked_items: list[tuple[int, dict[str, Any]]] = []
            seen_ids: set[int] = set()

            for query in queries:
                logger.info("Subdivx bridge search query: %s", query)
                items = await self._run_single_search(client, token, version_suffix, query)
                logger.info("Subdivx bridge query '%s' returned %d item(s)", query, len(items))

                for item in items:
                    try:
                        item_id = int(item.get("id"))
                    except (TypeError, ValueError):
                        continue
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                    ranked_items.append((self._score_item(item, context, query), item))

                if ranked_items:
                    break

            ranked_items.sort(
                key=lambda pair: (pair[0], int(pair[1].get("descargas") or 0)),
                reverse=True,
            )

            results: list[SearchItem] = []
            for _, item in ranked_items[:limit]:
                item_id = int(item["id"])
                description = self._strip_html(item.get("descripcion"))
                full_text = f"{item.get('titulo', '')} {description}"
                season, episode = self._extract_season_episode(full_text)
                results.append(
                    SearchItem(
                        id=item_id,
                        title=str(item.get("titulo") or f"Subdivx #{item_id}"),
                        description=description,
                        downloads=int(item.get("descargas") or 0),
                        uploader_name=str(item.get("nick") or "unknown"),
                        page_url=f"{self._settings.subdivx_base_url}/descargar.php?f=1&id={item_id}",
                        season=season,
                        episode=episode,
                    )
                )

            return results

    async def search(
        self,
        *,
        title: str | None,
        imdb_id: str | None,
        tmdb_id: str | None,
        video_type: str,
        year: int | None,
        limit: int,
    ) -> list[SearchItem]:
        return await self._search_uncached(
            title=title,
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
            video_type=video_type,
            year=year,
            limit=limit,
        )

    async def download(self, subtitle_id: int) -> SubtitleDownload:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                f"{self._settings.subdivx_base_url}/descargar.php?f=1&id={subtitle_id}",
                headers=self._default_headers(),
                timeout=60.0,
            )
            response.raise_for_status()

            media_type = response.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
            filename = None
            disposition = response.headers.get("content-disposition", "")
            match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition, re.IGNORECASE)
            if match:
                filename = match.group(1).strip('"')

            return SubtitleDownload(content=response.content, media_type=media_type, filename=filename)
