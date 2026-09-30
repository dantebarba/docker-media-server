"""Reverse proxy for Plex transcode decisions that forces server-side MDE for Plex for Android (TV).

The Android TV app decides Direct Play on its own for MKVs whose selected audio is DTS,
because it can software-decode DTS, so the server never transcodes the track to EAC3 and
the Chromecast outputs PCM. When such a request comes in with directPlay=1, this proxy
rewrites it to directPlay=0 so the server answers with a Direct Stream: video copied,
audio transcoded per the Android profile.
"""
import http.server
import os
import re
import socketserver
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

PLEX = os.environ.get("PLEX_URL", "http://plex:32400")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8080"))
TARGET_PRODUCT = os.environ.get("TARGET_PRODUCT", "Plex for Android (TV)")
FORCE_AUDIO_CODECS = set(os.environ.get("FORCE_AUDIO_CODECS", "dca").split(","))
HOP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-connection", "host"}


def first(params, key, default=None):
    values = params.get(key)
    return values[0] if values else default


def selected_stream(part, stream_type, forced_id):
    streams = [s for s in part.findall("Stream") if s.get("streamType") == stream_type]
    if forced_id:
        for s in streams:
            if s.get("id") == forced_id:
                return s
        return None
    for s in streams:
        if s.get("selected") == "1":
            return s
    return streams[0] if stream_type == "2" and streams else None


def should_force_transcode(params, headers):
    product = headers.get("X-Plex-Product") or first(params, "X-Plex-Product", "")
    if product != TARGET_PRODUCT or first(params, "directPlay") != "1":
        return False
    path = first(params, "path", "")
    match = re.match(r"^/library/metadata/(\d+)$", path)
    if not match:
        return False
    token = headers.get("X-Plex-Token") or first(params, "X-Plex-Token")
    if not token:
        return False
    req = urllib.request.Request(f"{PLEX}{path}", headers={"X-Plex-Token": token, "Accept": "application/xml"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        root = ET.fromstring(resp.read())
    video = root.find("Video")
    if video is None:
        return False
    media_list = video.findall("Media")
    media_index = int(first(params, "mediaIndex", "0"))
    if media_index >= len(media_list):
        return False
    parts = media_list[media_index].findall("Part")
    part_index = int(first(params, "partIndex", "0"))
    if part_index >= len(parts):
        return False
    part = parts[part_index]
    audio = selected_stream(part, "2", first(params, "audioStreamID"))
    return audio is not None and audio.get("codec") in FORCE_AUDIO_CODECS


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def do_GET(self):
        target = self.path
        try:
            parsed = urllib.parse.urlsplit(self.path)
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            if should_force_transcode(params, self.headers):
                query = re.sub(r"(^|&)directPlay=1(&|$)", r"\1directPlay=0\2", parsed.query)
                target = urllib.parse.urlunsplit(parsed._replace(query=query))
                self.log_message("forced directPlay=0 for %s", first(params, "path"))
        except Exception as exc:
            self.log_message("lookup failed, passing through: %s", exc)
        self.proxy(target)

    def proxy(self, target):
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
        headers["Host"] = self.headers.get("Host", "plex")
        req = urllib.request.Request(f"{PLEX}{target}", headers=headers, method="GET")
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as err:
            resp = err
        body = resp.read()
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            if k.lower() in HOP_HEADERS or k.lower() == "content-length":
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"plex-mde-shim listening on {LISTEN_PORT}, upstream {PLEX}, product {TARGET_PRODUCT!r}", flush=True)
    Server(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
