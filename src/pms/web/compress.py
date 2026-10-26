"""Gzip for the text the phone downloads.

On the laptop the transfer is instant; through Tailscale on a phone network,
the dashboard's 140 KB of HTML (mostly SVG coordinates) are what a click
waits for, and they shrink to about 23 KB. Done here rather than with
flask-compress: a dozen lines do not justify a dependency.

Only text is compressed. PNG icons and xlsx exports (a zip) are compressed
already; gzipping them again costs time and saves nothing. No page carries a
secret (no CSRF token, no session: `guard` checks the Origin), so the BREACH
family of attacks, which reads a secret through compressed sizes, has nothing
to read.
"""

from __future__ import annotations

import gzip

from flask import Flask, Response, request

TYPES = frozenset({
    "text/html", "text/css", "text/javascript", "application/javascript",
    "application/json", "application/manifest+json", "image/svg+xml",
    "text/csv",
})
# Below this the gzip header and the work outweigh what is saved.
MIN_BYTES = 1024
# Level 9 (gzip.compress's default) is several times slower for a percent
# or two less; every page pays it.
LEVEL = 6


def install(app: Flask) -> None:
    app.after_request(_compress)


def _compress(response: Response) -> Response:
    if response.mimetype not in TYPES:
        return response
    # Whether a cache may reuse this answer depends on what the client
    # accepted, compressed or not.
    response.vary.add("Accept-Encoding")
    if (response.status_code != 200
            or "Content-Encoding" in response.headers
            or not request.accept_encodings["gzip"]):
        return response
    # A static file is passed through as an open file; a generator is a
    # stream on purpose, and buffering it would defeat it.
    if response.is_streamed and not response.direct_passthrough:
        return response
    response.direct_passthrough = False
    data = response.get_data()
    if len(data) < MIN_BYTES:
        return response
    response.set_data(gzip.compress(data, compresslevel=LEVEL, mtime=0))
    response.headers["Content-Encoding"] = "gzip"
    # The compressed bytes are not the file the ETag names. A weak ETag says
    # "same content", which still lets the next visit revalidate to a 304.
    etag, _ = response.get_etag()
    if etag:
        response.set_etag(etag, weak=True)
    return response
