"""API endpoint tests, based on docs/spec.md.

Covers /healthz, /datasets, /schema, /columns, /rows (pagination, column
filtering, serialization), /vector/preview, and the graceful-degradation
path for unreadable datasets.
"""

import base64

import lancedb
import pytest
from packaging.version import parse as parse_version

from conftest import CLIP_DIM, ROWS, VEC_DIM


# /healthz

def test_healthz_reports_versions(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["lancedb_version"] == lancedb.__version__
    assert body["build_tag"] == f"app-{body['app_version']}_lancedb-{lancedb.__version__}"


def test_healthz_compat_flags(client):
    compat = client.get("/healthz").json()["compat"]
    installed = parse_version(lancedb.__version__)
    assert compat["vector_preview"] is True
    assert compat["schema_evolution"] == (installed >= parse_version("0.5"))
    assert compat["lance_v2_format"] == (installed >= parse_version("0.16"))


# /datasets

def test_datasets_lists_created_tables(client):
    response = client.get("/datasets")
    assert response.status_code == 200
    names = response.json()["datasets"]
    assert "sample" in names
    assert "broken" in names


# /datasets/{name}/schema

def test_schema_fields(client):
    response = client.get("/datasets/sample/schema")
    assert response.status_code == 200
    body = response.json()
    assert "metadata" in body
    fields = {f["name"]: f for f in body["fields"]}
    assert set(fields) == {"id", "text", "score", "blob", "vec", "embedding"}
    assert fields["id"]["type"] == "int64"
    assert fields["id"]["nullable"] is True
    assert fields["vec"]["type"] == "list<item: float>"
    assert fields["embedding"]["type"].startswith("fixed_size_list")
    assert str(CLIP_DIM) in fields["embedding"]["type"]


def test_schema_vector_dim_only_on_vector_fields(client):
    fields = {f["name"]: f for f in client.get("/datasets/sample/schema").json()["fields"]}
    assert "vector_dim" in fields["vec"]
    assert "vector_dim" in fields["embedding"]
    assert "vector_dim" not in fields["id"]
    assert "vector_dim" not in fields["text"]


def test_schema_invalid_dataset_name(client):
    assert client.get("/datasets/bad.name/schema").status_code == 400


def test_schema_missing_dataset(client):
    assert client.get("/datasets/nosuchtable/schema").status_code == 500


def test_schema_readable_on_corrupted_dataset(client):
    response = client.get("/datasets/broken/schema")
    assert response.status_code == 200
    assert [f["name"] for f in response.json()["fields"]] == ["id"]


# /datasets/{name}/columns

def test_columns_vector_flags(client):
    response = client.get("/datasets/sample/columns")
    assert response.status_code == 200
    columns = {c["name"]: c for c in response.json()["columns"]}
    assert columns["vec"]["is_vector"] is True
    assert columns["vec"]["dim"] is None
    assert columns["embedding"]["is_vector"] is True
    assert columns["id"]["is_vector"] is False
    assert "dim" not in columns["id"]


def test_columns_invalid_dataset_name(client):
    assert client.get("/datasets/bad.name/columns").status_code == 400


# /datasets/{name}/rows

def test_rows_defaults(client):
    response = client.get("/datasets/sample/rows")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == ROWS
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["rows"]) == ROWS


def test_rows_pagination(client):
    body = client.get("/datasets/sample/rows", params={"limit": 3, "offset": 0}).json()
    assert [r["id"] for r in body["rows"]] == [0, 1, 2]
    assert body["total"] == ROWS
    assert body["limit"] == 3

    body = client.get("/datasets/sample/rows", params={"limit": 3, "offset": 8}).json()
    assert [r["id"] for r in body["rows"]] == [8, 9]


def test_rows_offset_past_end(client):
    body = client.get("/datasets/sample/rows", params={"offset": ROWS}).json()
    assert body["rows"] == []
    assert body["total"] == ROWS


def test_rows_limit_bounds(client):
    assert client.get("/datasets/sample/rows", params={"limit": 0}).status_code == 422
    assert client.get("/datasets/sample/rows", params={"limit": 201}).status_code == 422
    assert client.get("/datasets/sample/rows", params={"offset": -1}).status_code == 422


def test_rows_column_filtering(client):
    body = client.get("/datasets/sample/rows", params={"columns": "id,text"}).json()
    assert all(set(row) == {"id", "text"} for row in body["rows"])


def test_rows_invalid_column_returns_400(client):
    response = client.get("/datasets/sample/rows", params={"columns": "id,nope"})
    assert response.status_code == 400
    assert "nope" in response.json()["detail"]


def test_rows_invalid_dataset_name(client):
    assert client.get("/datasets/bad.name/rows").status_code == 400


def test_rows_missing_dataset(client):
    assert client.get("/datasets/nosuchtable/rows").status_code == 500


def test_rows_scalar_serialization(client):
    rows = client.get("/datasets/sample/rows").json()["rows"]
    assert rows[0]["id"] == 0
    assert rows[0]["text"] == "row 0"
    assert rows[0]["score"] == 0.0
    assert rows[1]["score"] == 1.5
    assert rows[3]["text"] is None


def test_rows_binary_serialization(client):
    rows = client.get("/datasets/sample/rows").json()["rows"]
    # UTF-8 decodable bytes come back as text, the rest as base64
    assert rows[0]["blob"] == "hello"
    assert rows[1]["blob"] == base64.b64encode(b"\xff\xfe\x01\x02").decode()


def test_rows_vector_serialization(client):
    rows = client.get("/datasets/sample/rows").json()["rows"]
    vec = rows[0]["vec"]
    assert vec["type"] == "vector"
    assert vec["dim"] == VEC_DIM
    assert vec["preview"] == [0.0, -1.0, 0.5, 2.0]
    assert vec["norm"] == pytest.approx(5.25 ** 0.5)
    assert vec["min"] == -1.0
    assert vec["max"] == 2.0
    assert vec["mean"] == pytest.approx(0.375)


def test_rows_null_vector(client, vec_nulls_preserved):
    rows = client.get("/datasets/sample/rows").json()["rows"]
    if vec_nulls_preserved:
        assert rows[5]["vec"] is None
    else:
        # storage turned the null into an empty list, which serializes
        # to the invalid-vector error object
        assert rows[5]["vec"] == {"type": "vector", "error": "Invalid vector data"}


def test_rows_clip_detection(client):
    embedding = client.get("/datasets/sample/rows").json()["rows"][0]["embedding"]
    assert embedding["type"] == "vector"
    assert embedding["dim"] == CLIP_DIM
    assert embedding["model"] == "likely_clip"
    assert len(embedding["preview"]) == 32
    assert embedding["norm"] == pytest.approx(1.0, abs=1e-3)
    assert embedding["stats"]["normalized"] is True
    assert embedding["stats"]["sparsity"] == 0.0
    assert embedding["stats"]["positive_ratio"] == 1.0


def test_rows_graceful_degradation_on_corrupted_dataset(client):
    response = client.get("/datasets/broken/rows")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    row = body["rows"][0]
    assert row["error"] == "Unable to read dataset"
    assert row["dataset"] == "broken"
    assert row["details"].startswith("Error:")


# /datasets/{name}/vector/preview

def test_vector_preview_stats(client, vec_nulls_preserved):
    response = client.get("/datasets/sample/vector/preview", params={"column": "vec"})
    assert response.status_code == 200
    body = response.json()
    # the null vector is filtered from the count; on format v1 it comes
    # back as an empty list instead, which counts but adds no values
    assert body["stats"]["count"] == (ROWS - 1 if vec_nulls_preserved else ROWS)
    assert body["stats"]["dim"] == VEC_DIM
    assert body["stats"]["min"] == -1.0
    assert body["stats"]["max"] == 9.0
    assert body["stats"]["mean"] == pytest.approx(53.5 / 36)
    assert len(body["preview"]) == ROWS - 1
    first = body["preview"][0]
    assert first["sample"] == [0.0, -1.0, 0.5, 2.0]
    assert first["norm"] == pytest.approx(5.25 ** 0.5)


def test_vector_preview_sample_capped_at_32(client):
    body = client.get(
        "/datasets/sample/vector/preview", params={"column": "embedding"}
    ).json()
    assert body["stats"]["dim"] == CLIP_DIM
    assert all(len(p["sample"]) == 32 for p in body["preview"])


def test_vector_preview_non_vector_column(client):
    response = client.get("/datasets/sample/vector/preview", params={"column": "score"})
    assert response.status_code == 400


def test_vector_preview_missing_column(client):
    response = client.get("/datasets/sample/vector/preview", params={"column": "nope"})
    assert response.status_code == 400


def test_vector_preview_column_param_required(client):
    assert client.get("/datasets/sample/vector/preview").status_code == 422


def test_vector_preview_invalid_dataset_name(client):
    response = client.get("/datasets/bad.name/vector/preview", params={"column": "vec"})
    assert response.status_code == 400
