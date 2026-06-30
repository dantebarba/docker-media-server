from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class Settings:
    api_keys: tuple[str, ...]
    subdivx_base_url: str
    imdb_base_url: str
    tmdb_base_url: str
    tmdb_api_key: str
    tmdb_read_access_token: str
    cookie_header: str
    cf_clearance: str
    sdx_cookie: str
    user_agent: str
    log_level: str

    @property
    def combined_cookie_header(self) -> str:
        if self.cookie_header.strip():
            return self.cookie_header.strip()

        parts: list[str] = []
        if self.cf_clearance.strip():
            parts.append(f"cf_clearance={self.cf_clearance.strip()}")
        if self.sdx_cookie.strip():
            parts.append(f"sdx={self.sdx_cookie.strip()}")
        return "; ".join(parts)

    @property
    def has_custom_user_agent(self) -> bool:
        return bool(os.environ.get("SUBDIVX_USER_AGENT", "").strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw_keys = os.environ.get("SUBX_API_KEYS", "")
    api_keys = tuple(x.strip() for x in raw_keys.split(",") if x.strip())
    return Settings(
        api_keys=api_keys,
        subdivx_base_url=os.environ.get("SUBDIVX_BASE_URL", "https://subdivx.com").rstrip("/"),
        imdb_base_url=os.environ.get("IMDB_BASE_URL", "https://www.imdb.com").rstrip("/"),
        tmdb_base_url=os.environ.get("TMDB_BASE_URL", "https://api.themoviedb.org/3").rstrip("/"),
        tmdb_api_key=os.environ.get("TMDB_API_KEY", "").strip(),
        tmdb_read_access_token=os.environ.get("TMDB_READ_ACCESS_TOKEN", "").strip(),
        cookie_header=os.environ.get("SUBDIVX_COOKIE_HEADER", ""),
        cf_clearance=os.environ.get("SUBDIVX_CF_CLEARANCE", ""),
        sdx_cookie=os.environ.get("SUBDIVX_SDX", ""),
        user_agent=os.environ.get(
            "SUBDIVX_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64; rv:148.0) Gecko/20100101 Firefox/148.0",
        ),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )
