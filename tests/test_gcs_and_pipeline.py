import zipfile

import pyarrow.parquet as pq
import pytest
from pyarrow import fs

from ingest import gcs, pipeline
from ingest.schema import SCHEMA


@pytest.fixture
def store(tmp_path):
    # Stand-in for a bucket. Object stores have no directories, a local disk does,
    # so the prefixes the tests write under are created up front.
    root = tmp_path / "store"
    for prefix in ("schools", "a", "b/c"):
        (root / "bkt" / prefix).mkdir(parents=True)
    return fs.SubTreeFileSystem(str(root), fs.LocalFileSystem())


def files(store):
    infos = store.get_file_info(fs.FileSelector("bkt", recursive=True))
    return sorted(i.path for i in infos if i.is_file)


def test_upload_reports_size_and_mtime_from_the_store(store, tmp_path):
    local = tmp_path / "f.parquet"
    local.write_bytes(b"x" * 1234)
    info = gcs.upload_file(store, local, "bkt/schools/f.parquet")
    assert info.size == 1234
    assert isinstance(info.mtime_ns, int) and info.mtime_ns > 0
    assert files(store) == ["bkt/schools/f.parquet"]
    assert gcs.list_top_level(store, "bkt") == ["bkt/a", "bkt/b", "bkt/schools"]


def test_upload_of_missing_local_file_fails_before_touching_the_store(store, tmp_path):
    with pytest.raises(FileNotFoundError):
        gcs.upload_file(store, tmp_path / "missing", "bkt/x")
    assert files(store) == []


def test_empty_bucket_removes_nested_objects(store, tmp_path):
    local = tmp_path / "f"
    local.write_bytes(b"1")
    gcs.upload_file(store, local, "bkt/a/one")
    gcs.upload_file(store, local, "bkt/b/c/two")
    assert gcs.empty_bucket(store, "bkt") == 2
    assert files(store) == []


def build_source_zip(path, make_line):
    lines = [
        make_line(),
        make_line(NCESSCH="010000500870", LEAID="0100005", STATE="AL", CNTY="01095"),
        make_line(NCESSCH="550001602378", NAME="  Blair-Taylor   Middle/High "),
        make_line(NCESSCH="550001602379", LAT="9.9"),
    ]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("EDGE_GEOCODE_PUBLICSCH_2425.TXT", "".join(lines))


def test_pipeline_end_to_end_with_a_local_store(monkeypatch, tmp_path, store, make_line):
    data = tmp_path / "data"
    data.mkdir()
    build_source_zip(data / "edge_publicsch_2425.zip", make_line)
    monkeypatch.setattr(
        "ingest.fetch.download", lambda url, dest, refresh=False: dest, raising=True
    )

    summary = pipeline.run(year_code="2425", data_dir=data, bucket="bkt", filesystem=store)

    assert (summary.rows_seen, summary.rows_other_states) == (4, 1)
    assert (summary.rows_kept, summary.rows_rejected) == (2, 1)
    assert summary.uploaded.path == f"bkt/{gcs.OBJECT_NAME}"
    assert summary.uploaded.size == summary.parquet_bytes
    table = pq.read_table(data / "wi_schools.parquet")
    assert table.schema.equals(SCHEMA)
    assert "Blair-Taylor Middle/High" in table.column("school_name").to_pylist()
    assert (data / "wi_schools_rejects.csv").exists()


def test_pipeline_without_a_bucket_skips_upload(monkeypatch, tmp_path, make_line):
    data = tmp_path / "data"
    data.mkdir()
    build_source_zip(data / "edge_publicsch_2425.zip", make_line)
    monkeypatch.setattr("ingest.fetch.download", lambda url, dest, refresh=False: dest)
    summary = pipeline.run(year_code="2425", data_dir=data, bucket=None)
    assert summary.uploaded is None
    assert summary.as_dict()["rows_kept"] == 2


def test_pipeline_refuses_a_file_with_no_wisconsin_rows(monkeypatch, tmp_path, make_line):
    data = tmp_path / "data"
    data.mkdir()
    with zipfile.ZipFile(data / "edge_publicsch_2425.zip", "w") as zf:
        zf.writestr("x.TXT", make_line(STATE="AL"))
    monkeypatch.setattr("ingest.fetch.download", lambda url, dest, refresh=False: dest)
    with pytest.raises(ValueError, match="no Wisconsin rows"):
        pipeline.run(year_code="2425", data_dir=data, bucket=None)
    assert not (data / "wi_schools.parquet").exists()
