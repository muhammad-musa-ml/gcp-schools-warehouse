import functools
import http.server
import threading
import zipfile

import pytest

from ingest import fetch


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def test_source_url_checks_the_year_code():
    assert fetch.source_url("2425").endswith("EDGE_GEOCODE_PUBLICSCH_2425.zip")
    for bad in ("24-25", "242", "20242025", ""):
        with pytest.raises(ValueError):
            fetch.source_url(bad)


def test_download_writes_file_and_skips_when_present(server, tmp_path):
    root, base = server
    (root / "a.zip").write_bytes(b"first")
    dest = tmp_path / "cache" / "a.zip"
    fetch.download(f"{base}/a.zip", dest)
    assert dest.read_bytes() == b"first"

    (root / "a.zip").write_bytes(b"second")
    fetch.download(f"{base}/a.zip", dest)
    assert dest.read_bytes() == b"first"
    fetch.download(f"{base}/a.zip", dest, refresh=True)
    assert dest.read_bytes() == b"second"
    assert not list(dest.parent.glob("*.part"))


def test_download_of_missing_file_leaves_no_partial(server, tmp_path):
    _, base = server
    dest = tmp_path / "cache" / "nope.zip"
    with pytest.raises(OSError):
        fetch.download(f"{base}/nope.zip", dest)
    assert not dest.exists()
    assert not list(dest.parent.glob("*.part"))


def test_open_text_member_reads_the_txt_and_strips_a_bom(tmp_path):
    z = tmp_path / "x.zip"
    make_zip(z, {"EDGE.xlsx": b"xx", "EDGE.TXT": b"\xef\xbb\xbfa|b\r\nc|d\r\n"})
    with fetch.open_text_member(z) as f:
        assert f.read() == "a|b\r\nc|d\r\n"


@pytest.mark.parametrize("members", [{"only.xlsx": b"x"}, {"a.TXT": b"1", "b.txt": b"2"}])
def test_open_text_member_wants_exactly_one_txt(tmp_path, members):
    z = tmp_path / "x.zip"
    make_zip(z, members)
    with pytest.raises(ValueError, match="one .TXT member"), fetch.open_text_member(z):
        pass


def test_sha256_of(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"abc")
    assert fetch.sha256_of(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
