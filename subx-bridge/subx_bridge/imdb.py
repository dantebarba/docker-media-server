from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from .config import Settings


IMDB_JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">\s*(?P<payload>\{.*?\})\s*</script>',
    re.DOTALL,
)
IMDB_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">\s*(?P<payload>\{.*?\})\s*</script>',
    re.DOTALL,
)
IMDB_OG_TITLE_RE = re.compile(r'<meta property="og:title" content="(?P<title>[^"]+)"', re.IGNORECASE)
IMDB_HTML_TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass
class ImdbMetadata:
    title: str | None = None
    year: int | None = None
    season: int | None = None
    episode: int | None = None


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _extract_year_from_text(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", text)
    return int(match.group(0)) if match else None


def _clean_title_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    cleaned = re.sub(r"\s*[-|]\s*IMDb.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\((19|20)\d{2}\).*$", "", cleaned).strip()
    return cleaned or None


def _extract_from_next_data(html: str) -> ImdbMetadata:
    match = IMDB_NEXT_DATA_RE.search(html)
    if not match:
        return ImdbMetadata()

    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return ImdbMetadata()

    page_props = (
        payload.get("props", {})
        .get("pageProps", {})
    )
    above_the_fold = page_props.get("aboveTheFoldData", {})
    title_text = (
        above_the_fold.get("titleText", {}).get("text")
        or above_the_fold.get("originalTitleText", {}).get("text")
    )
    release_year = _coerce_int(above_the_fold.get("releaseYear", {}).get("year"))

    episode = _coerce_int(above_the_fold.get("episodeNumber", {}).get("episodeNumber"))
    season = _coerce_int(above_the_fold.get("series", {}).get("displayableEpisodeNumber", {}).get("season"))
    series_title = above_the_fold.get("series", {}).get("seriesTitleText", {}).get("text")
    if series_title:
        title_text = series_title

    return ImdbMetadata(
        title=_clean_title_text(title_text),
        year=release_year,
        season=season,
        episode=episode,
    )


def _extract_basic_html_fallback(html: str) -> ImdbMetadata:
    og_title_match = IMDB_OG_TITLE_RE.search(html)
    og_title = og_title_match.group("title") if og_title_match else None

    html_title_match = IMDB_HTML_TITLE_RE.search(html)
    html_title = html_title_match.group("title") if html_title_match else None

    raw_title = og_title or html_title
    return ImdbMetadata(
        title=_clean_title_text(raw_title),
        year=_extract_year_from_text(raw_title),
    )


async def resolve_imdb_metadata(
    client: httpx.AsyncClient,
    settings: Settings,
    imdb_id: str,
) -> ImdbMetadata:
    response = await client.get(
        f"{settings.imdb_base_url}/title/{imdb_id}/",
        headers={"User-Agent": settings.user_agent, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=15.0,
    )
    response.raise_for_status()

    match = IMDB_JSON_LD_RE.search(response.text)
    if not match:
        next_data_metadata = _extract_from_next_data(response.text)
        if next_data_metadata.title:
            return next_data_metadata
        return _extract_basic_html_fallback(response.text)

    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return ImdbMetadata()

    title = payload.get("name")
    year = None
    if isinstance(payload.get("datePublished"), str):
        date_published = payload["datePublished"]
        if len(date_published) >= 4 and date_published[:4].isdigit():
            year = int(date_published[:4])

    season = None
    episode = _coerce_int(payload.get("episodeNumber"))

    part_of_season = payload.get("partOfSeason")
    if isinstance(part_of_season, dict):
        season = _coerce_int(part_of_season.get("seasonNumber"))

    part_of_series = payload.get("partOfSeries")
    if isinstance(part_of_series, dict):
        title = part_of_series.get("name") or title

    metadata = ImdbMetadata(title=title, year=year, season=season, episode=episode)
    if metadata.title:
        return metadata

    next_data_metadata = _extract_from_next_data(response.text)
    if next_data_metadata.title:
        return ImdbMetadata(
            title=next_data_metadata.title,
            year=metadata.year or next_data_metadata.year,
            season=metadata.season or next_data_metadata.season,
            episode=metadata.episode or next_data_metadata.episode,
        )

    basic_fallback = _extract_basic_html_fallback(response.text)
    return ImdbMetadata(
        title=basic_fallback.title,
        year=metadata.year or basic_fallback.year,
        season=metadata.season,
        episode=metadata.episode,
    )
