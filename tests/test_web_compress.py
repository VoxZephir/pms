"""Gzip on the way to the phone: text only, never changing what is served."""

import gzip

from pms.web.api import SPA

GZIP = {"Accept-Encoding": "gzip, deflate, br"}


def test_the_data_is_compressed_to_the_same_json(client):
    url = "/api/dashboard?preset=all"
    plain = client.get(url)
    packed = client.get(url, headers=GZIP)
    assert "Content-Encoding" not in plain.headers
    assert packed.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(packed.data) == plain.data
    assert len(packed.data) < len(plain.data) / 3
    assert int(packed.headers["Content-Length"]) == len(packed.data)
    assert "Accept-Encoding" in packed.headers["Vary"]
    assert "Accept-Encoding" in plain.headers["Vary"]


def test_the_page_is_compressed_too(client):
    plain = client.get("/")
    packed = client.get("/", headers=GZIP)
    assert packed.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(packed.data) == plain.data


def test_a_client_that_refuses_gzip_gets_it_plain(client):
    data = client.get("/api/dashboard", headers={"Accept-Encoding": "gzip;q=0, br"})
    assert "Content-Encoding" not in data.headers


def test_a_built_script_still_revalidates_to_304(client):
    script = max((SPA / "assets").glob("*.js"), key=lambda p: p.stat().st_size)
    url = f"/static/spa/assets/{script.name}"
    first = client.get(url, headers=GZIP)
    assert first.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(first.data) == client.get(url).data
    etag = first.headers["ETag"]
    assert etag.startswith('W/"')
    again = client.get(url, headers={**GZIP, "If-None-Match": etag})
    assert again.status_code == 304


def test_images_are_not_compressed_again(client):
    icon = client.get("/static/icon-512.png", headers=GZIP)
    assert icon.status_code == 200
    assert "Content-Encoding" not in icon.headers


def test_an_xlsx_export_is_left_as_is(client):
    # A zip already: gzip would only cost time.
    export = client.get("/export.xlsx", headers=GZIP)
    assert export.status_code == 200
    assert "Content-Encoding" not in export.headers
    assert export.data.startswith(b"PK")


def test_a_csv_export_is_compressed_to_the_same_file(client):
    plain = client.get("/export.csv")
    packed = client.get("/export.csv", headers=GZIP)
    assert packed.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(packed.data) == plain.data
