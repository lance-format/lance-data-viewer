"""Shared fixtures: a temporary Lance database and a FastAPI test client.

Run from the backend directory:

    python -m pytest tests/ -v

The sample data is written once per session with whatever lancedb/pyarrow
versions are installed, so the same tests run against every constraints file.
"""

import os
import sys
from pathlib import Path

import lancedb
import pyarrow as pa
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROWS = 10
VEC_DIM = 4
CLIP_DIM = 512


def _sample_table() -> pa.Table:
    ids = list(range(ROWS))
    texts = [None if i == 3 else f"row {i}" for i in ids]
    scores = [i * 1.5 for i in ids]
    blobs = [b"hello" if i % 2 == 0 else b"\xff\xfe\x01\x02" for i in ids]
    vecs = [None if i == 5 else [float(i), -1.0, 0.5, 2.0] for i in ids]
    unit = 1.0 / CLIP_DIM ** 0.5
    embeddings = [[unit] * CLIP_DIM for _ in ids]

    return pa.table({
        "id": pa.array(ids, type=pa.int64()),
        "text": pa.array(texts, type=pa.string()),
        "score": pa.array(scores, type=pa.float64()),
        "blob": pa.array(blobs, type=pa.binary()),
        "vec": pa.array(vecs, type=pa.list_(pa.float32())),
        "embedding": pa.array(embeddings, type=pa.list_(pa.float32(), CLIP_DIM)),
    })


def _corrupt_table(db_dir: Path, name: str) -> None:
    """Overwrite the data fragments of a table so reads fail but the
    manifest stays intact and open_table() still succeeds."""
    table_dir = db_dir / f"{name}.lance"
    data_files = [p for p in table_dir.rglob("*.lance") if p.is_file()]
    assert data_files, f"no data files found under {table_dir}"
    for path in data_files:
        path.write_bytes(b"not a lance data file")


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("lance-data")
    db = lancedb.connect(str(path))
    db.create_table("sample", _sample_table())
    db.create_table("broken", pa.table({"id": pa.array([1, 2, 3], type=pa.int64())}))
    _corrupt_table(path, "broken")
    return path


@pytest.fixture(scope="session")
def vec_nulls_preserved(data_dir):
    """Lance format v1 (lancedb 0.3.x/0.5) stores a null list as an empty
    list. Detect what the installed version actually does so tests can
    assert the matching serialization."""
    db = lancedb.connect(str(data_dir))
    values = db.open_table("sample").to_arrow().column("vec").to_pylist()
    return values[5] is None


@pytest.fixture(scope="session")
def client(data_dir):
    # DATA_PATH is read at import time, so set it before importing app
    os.environ["DATA_PATH"] = str(data_dir)
    import app as app_module
    app_module.DATA_PATH = data_dir

    from fastapi.testclient import TestClient
    with TestClient(app_module.app) as test_client:
        yield test_client
