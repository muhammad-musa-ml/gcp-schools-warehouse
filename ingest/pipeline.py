from dataclasses import asdict, dataclass
from pathlib import Path

from pyarrow import fs

from . import clean, fetch, gcs


@dataclass
class IngestSummary:
    source_url: str
    zip_sha256: str
    rows_seen: int
    rows_other_states: int
    rows_kept: int
    rows_rejected: int
    parquet_path: str
    parquet_bytes: int
    uploaded: gcs.ObjectInfo | None

    def as_dict(self) -> dict:
        return asdict(self)


def run(
    *,
    year_code: str,
    data_dir: Path,
    bucket: str | None,
    filesystem: fs.FileSystem | None = None,
    refresh: bool = False,
) -> IngestSummary:
    url = fetch.source_url(year_code)
    zip_path = fetch.download(url, data_dir / f"edge_publicsch_{year_code}.zip", refresh=refresh)

    with fetch.open_text_member(zip_path) as text:
        result = clean.clean_rows(clean.read_rows(text))

    if result.rejects:
        clean.write_rejects(result.rejects, data_dir / "wi_schools_rejects.csv")
    if not result.records:
        raise ValueError("no Wisconsin rows found; is the source file the expected layout?")

    parquet = data_dir / "wi_schools.parquet"
    clean.write_parquet(result.records, parquet)

    uploaded = None
    if bucket:
        filesystem = filesystem or gcs.gcs_filesystem()
        uploaded = gcs.upload_file(filesystem, parquet, f"{bucket}/{gcs.OBJECT_NAME}")

    return IngestSummary(
        source_url=url,
        zip_sha256=fetch.sha256_of(zip_path),
        rows_seen=result.rows_seen,
        rows_other_states=result.rows_other_states,
        rows_kept=len(result.records),
        rows_rejected=len(result.rejects),
        parquet_path=str(parquet),
        parquet_bytes=parquet.stat().st_size,
        uploaded=uploaded,
    )
