#!/usr/bin/env python3
"""Small standalone probe for the SubX Bridge HTTP API.

Examples:
  python3 tools/bridge_probe.py \
    --base-url http://127.0.0.1:8787 \
    --api-key my-key \
    --video-type movie \
    --title "El secreto de sus ojos" \
    --year 2009

  python3 tools/bridge_probe.py \
    --base-url http://127.0.0.1:8787 \
    --api-key my-key \
    --video-type episode \
    --imdb-id tt0386676
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def request_json(url: str, api_key: str) -> object:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def request_download(url: str, api_key: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
        headers = {k.lower(): v for k, v in response.headers.items()}
        return body, headers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--video-type", required=True, choices=["movie", "episode"])
    parser.add_argument("--title", default=None)
    parser.add_argument("--imdb-id", default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--download-first", action="store_true")
    args = parser.parse_args()

    query = {
        "limit": str(args.limit),
        "video_type": args.video_type,
    }
    if args.title:
        query["title"] = args.title
    if args.imdb_id:
        query["imdb_id"] = args.imdb_id
    if args.year is not None:
        query["year"] = str(args.year)

    url = args.base_url.rstrip("/") + "/api/subtitles/search?" + urllib.parse.urlencode(query)

    try:
        payload = request_json(url, args.api_key)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code} calling search", file=sys.stderr)
        print(body, file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Connection error calling search: {exc}", file=sys.stderr)
        return 2

    if not isinstance(payload, dict):
        print(f"Unexpected payload: {payload!r}", file=sys.stderr)
        return 3

    items = payload.get("items")
    if not isinstance(items, list):
        print(f"Unexpected items field: {items!r}", file=sys.stderr)
        return 4

    print(f"Search URL: {url}")
    print(f"Total: {payload.get('total')}")
    for item in items:
        if not isinstance(item, dict):
            continue
        print("-" * 40)
        print(f"id: {item.get('id')}")
        print(f"title: {item.get('title')}")
        print(f"uploader: {item.get('uploader_name')}")
        print(f"season: {item.get('season')}")
        print(f"episode: {item.get('episode')}")
        print(f"page_url: {item.get('page_url')}")
        print(f"description: {item.get('description')}")

    if args.download_first and items:
        first_item = items[0] if isinstance(items[0], dict) else None
        subtitle_id = first_item.get("id") if first_item else None
        if subtitle_id is None:
            print("First result has no id, skipping download.", file=sys.stderr)
            return 5

        download_url = args.base_url.rstrip("/") + f"/api/subtitles/{subtitle_id}/download"
        try:
            content, headers = request_download(download_url, args.api_key)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"HTTP {exc.code} calling download", file=sys.stderr)
            print(body, file=sys.stderr)
            return 6
        except urllib.error.URLError as exc:
            print(f"Connection error calling download: {exc}", file=sys.stderr)
            return 7

        print("-" * 40)
        print(f"download_url: {download_url}")
        print(f"download_bytes: {len(content)}")
        print(f"content_type: {headers.get('content-type')}")
        print(f"content_disposition: {headers.get('content-disposition')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
