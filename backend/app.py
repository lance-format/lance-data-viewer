#!/usr/bin/env python3

from contextlib import asynccontextmanager
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse
import json

import lancedb
import pyarrow as pa
from packaging.version import parse as parse_version
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from serialize_value import serialize_value

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _read_app_version() -> str:
    here = Path(__file__).resolve().parent
    for candidate in (here / "VERSION", here.parent / "VERSION"):
        if candidate.exists():
            return candidate.read_text().strip()
    return "0.0.0-dev"


APP_VERSION = _read_app_version()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Log version information on startup."""
    logger.info(f"Lance Data Viewer v{APP_VERSION}")
    logger.info(f"LanceDB: {lancedb.__version__}, PyArrow: {pa.__version__}")
    logger.info(f"Data path: {DATA_PATH}")
    yield


app = FastAPI(
    title="Lance Data Viewer",
    description="Read-only web viewer for Lance datasets",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

DATA_PATH = os.getenv("DATA_PATH")
MAX_LIMIT = 1000


class InvalidDatasetReference(ValueError):
    """Raised when a requested branch, tag, or version cannot be opened."""

def validate_dataset_name(name: str) -> bool:
    return (
        name.replace("_", "").replace("-", "").isalnum()
        and not name.startswith(".")
        and len(name) <= 100
    )

def local_database_path(location: str) -> Optional[Path]:
    """Return the filesystem path for a local location, or None if it is remote.

    Object store URIs such as s3:// are opened by LanceDB without touching the
    local filesystem, so only plain paths and file: URIs are local.
    """
    scheme = urlparse(location).scheme
    if scheme and scheme != "file" and len(scheme) > 1:
        return None
    if location.startswith("file://"):
        return Path(location[7:])
    if location.startswith("file:"):
        return Path(location[5:])
    return Path(location)


def get_lance_connection(data_location: Optional[str] = None):
    """Connect to the configured database, or a location supplied by the UI."""
    configured = str(DATA_PATH).strip() if DATA_PATH is not None else ""
    location = configured or (data_location or "").strip()
    if not location:
        raise HTTPException(
            status_code=400,
            detail="A Lance dataset location is required when DATA_PATH is not set",
        )
    # lancedb.connect() creates a local directory that does not exist. The
    # viewer never writes to Lance data, so refuse instead of creating one.
    path = local_database_path(location)
    if path is not None and not path.expanduser().is_dir():
        if configured:
            raise HTTPException(status_code=500, detail="Data path not found")
        raise HTTPException(
            status_code=400,
            detail=f"Lance database location not found: {location}",
        )
    return lancedb.connect(location)


def _checkout(table, reference):
    """Checkout a tag/version while retaining support for older LanceDB clients."""
    checkout = getattr(table, "checkout", None)
    if checkout is None:
        raise InvalidDatasetReference(
            "This LanceDB version does not support tag or version checkout"
        )
    checkout(reference)
    return table


def open_table_at_reference(db, dataset_name: str, reference: str = "main"):
    """Open a table at main/latest, a version, tag, or branch reference.

    Accepted forms are ``main``, ``42``, ``tag:release``,
    ``branch:experiment``, and ``branch:experiment@42``. A bare name is
    accepted as a convenience and resolves as a branch first, then as a tag.
    """
    value = (reference or "main").strip()
    if not value or value in {"main", "latest"}:
        return db.open_table(dataset_name)

    if value.isdigit():
        version = int(value)
        try:
            return db.open_table(dataset_name, version=version)
        except TypeError:
            return _checkout(db.open_table(dataset_name), version)
        except Exception as error:
            raise InvalidDatasetReference(
                f"Unable to open main at version {version}: {error}"
            ) from error

    if value.startswith("tag:"):
        tag = value.removeprefix("tag:").strip()
        if not tag:
            raise InvalidDatasetReference("Tag name cannot be empty")
        try:
            return _checkout(db.open_table(dataset_name), tag)
        except InvalidDatasetReference:
            raise
        except Exception as error:
            raise InvalidDatasetReference(f"Unable to open tag '{tag}': {error}") from error

    explicit_branch = value.startswith("branch:")
    branch_reference = value.removeprefix("branch:").strip() if explicit_branch else value
    branch, separator, version_text = branch_reference.rpartition("@")
    if not separator:
        branch = branch_reference
        version = None
    else:
        if not branch or not version_text.isdigit():
            raise InvalidDatasetReference(
                "Branch versions must use branch:name@<number>"
            )
        version = int(version_text)

    try:
        kwargs = {"branch": branch}
        if version is not None:
            kwargs["version"] = version
        return db.open_table(dataset_name, **kwargs)
    except Exception as branch_error:
        branch_unsupported = (
            isinstance(branch_error, TypeError)
            and "branch" in str(branch_error)
        )
        if explicit_branch or version is not None:
            if branch_unsupported:
                raise InvalidDatasetReference(
                    f"Branch selection is not supported by LanceDB {lancedb.__version__}"
                ) from branch_error
            raise InvalidDatasetReference(
                f"Unable to open branch '{branch_reference}': {branch_error}"
            ) from branch_error

        # A bare name may be either a branch or a tag. Branches take priority.
        try:
            return _checkout(db.open_table(dataset_name), value)
        except Exception as tag_error:
            if branch_unsupported:
                raise InvalidDatasetReference(
                    f"No tag named '{value}' was found, and branch selection is "
                    f"not supported by LanceDB {lancedb.__version__}"
                ) from tag_error
            raise InvalidDatasetReference(
                f"Unable to open branch or tag '{value}': {tag_error}"
            ) from branch_error


def get_dataset_table(
    dataset_name: str,
    data_location: Optional[str],
    reference: str,
):
    db = get_lance_connection(data_location)
    try:
        return open_table_at_reference(db, dataset_name, reference)
    except InvalidDatasetReference as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def serialize_schema_metadata(metadata):
    """Convert Arrow schema metadata into a JSON-safe dictionary.

    PyArrow exposes schema metadata as bytes keys and values, but JSON requires
    string keys and values. ``serialize_value`` decodes valid UTF-8 bytes and
    base64-encodes bytes that cannot be decoded, preventing FastAPI response
    serialization from raising ``UnicodeDecodeError``.
    """
    return {
        serialize_value(key): serialize_value(value)
        for key, value in (metadata or {}).items()
    }


def describe_schema(schema):
    """Build schema and column metadata in one pass."""
    fields = []
    columns = []
    for field in schema:
        is_vector = (
            (pa.types.is_list(field.type) or pa.types.is_fixed_size_list(field.type))
            and pa.types.is_floating(field.type.value_type)
        )
        field_info = {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
        }
        if is_vector:
            field_info["vector_dim"] = None
        fields.append(field_info)

        column_info = {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
            "is_vector": is_vector,
        }
        if is_vector:
            column_info["dim"] = None
        columns.append(column_info)

    return {
        "fields": fields,
        "metadata": serialize_schema_metadata(schema.metadata),
        "columns": columns,
    }


def serialize_arrow_value(value):
    try:
        # Stop immediately if the Arrow scalar is null
        if value is None or not getattr(value, "is_valid", True):
            return None

        # 1. Handle Vector columns (Top-level OR nested)
        if (pa.types.is_list(value.type) or pa.types.is_fixed_size_list(value.type)) and getattr(value.type, "value_type", None) and pa.types.is_floating(value.type.value_type):
            try:
                vec = value.as_py()
                if vec is None:
                    return None

                if not isinstance(vec, (list, tuple)) or len(vec) == 0:
                    return {"type": "vector", "error": "Invalid vector data"}

                valid_values = []
                for v in vec:
                    if v is not None and isinstance(v, (int, float)) and not (isinstance(v, float) and (v != v or v == float('inf') or v == float('-inf'))):
                        valid_values.append(float(v))
                    else:
                        valid_values.append(0.0)

                if not valid_values:
                    return {"type": "vector", "error": "No valid numeric values in vector"}

                norm = float(sum(x*x for x in valid_values) ** 0.5) if valid_values else 0.0
                vec_min = float(min(valid_values)) if valid_values else 0.0
                vec_max = float(max(valid_values)) if valid_values else 0.0
                vec_mean = float(sum(valid_values) / len(valid_values)) if valid_values else 0.0

                is_clip_vector = len(valid_values) == 512

                result = {
                    "type": "vector",
                    "dim": len(valid_values),
                    "norm": norm,
                    "min": vec_min,
                    "max": vec_max,
                    "mean": vec_mean,
                    "preview": valid_values[:32],
                }

                if is_clip_vector:
                    result["model"] = "likely_clip"
                    result["description"] = "512-dimensional CLIP embedding"
                    result["stats"] = {
                        "normalized": abs(norm - 1.0) < 0.01,
                        "sparsity": sum(1 for x in valid_values if abs(x) < 0.01) / len(valid_values),
                        "positive_ratio": sum(1 for x in valid_values if x > 0) / len(valid_values)
                    }
                return result
            except Exception as vec_error:
                logger.warning(f"Error processing vector data: {vec_error}")
                return {"type": "vector", "error": f"Vector processing failed: {str(vec_error)}"}

        # 2. Handle Structs recursively to catch vectors hidden inside objects
        if pa.types.is_struct(value.type):
            result = {}
            for field in value.type:
                # In PyArrow, value[field.name] fetches the nested pa.Scalar
                result[field.name] = serialize_arrow_value(value[field.name])
            return result

        # 3. Handle Lists recursively (e.g., Arrays of Structs containing Vectors)
        if pa.types.is_list(value.type) or pa.types.is_large_list(value.type) or pa.types.is_fixed_size_list(value.type):
            result = []
            for item in value:  # Iterating a PyArrow ListScalar yields nested pa.Scalars
                result.append(serialize_arrow_value(item))
            return result

        # 4. Fallback to normal serialization for strings, ints, dates, etc.
        return serialize_value(value)
    except Exception as e:
        logger.warning(f"Error serializing value: {e}")
        return {"error": f"Serialization failed: {str(e)}"}

@app.get("/healthz")
async def health_check():
    try:
        lancedb_version = lancedb.__version__
        pyarrow_version = pa.__version__

        # Determine compatibility features based on Lance version
        compat = {
            "vector_preview": True,
            "schema_evolution": parse_version(lancedb_version) >= parse_version("0.5"),
            "lance_v2_format": parse_version(lancedb_version) >= parse_version("0.16")
        }

        # Generate build tag
        build_tag = f"app-{APP_VERSION}_lancedb-{lancedb_version}"

        return {
            "ok": True,
            "app_version": APP_VERSION,
            "lancedb_version": lancedb_version,
            "pyarrow_version": pyarrow_version,
            "build_tag": build_tag,
            "compat": compat
        }
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/config")
def get_config():
    return {
        "data_path_configured": bool(DATA_PATH),
        "default_reference": "main",
    }


@app.get("/datasets")
def list_datasets(data_location: Optional[str] = Query(default=None)):
    try:
        db = get_lance_connection(data_location)
        if hasattr(db, "list_tables"):
            table_names = db.list_tables().tables
        else:
            # table_names() was deprecated in favor of list_tables(),
            # but older lancedb versions only have table_names()
            table_names = db.table_names()
        valid_tables = [name for name in table_names if validate_dataset_name(name)]
        return {"datasets": valid_tables}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing datasets: {e}")
        raise HTTPException(status_code=500, detail="Failed to list datasets")


@app.get("/datasets/{dataset_name}/metadata")
def get_dataset_metadata(
    dataset_name: str,
    data_location: Optional[str] = Query(default=None),
    reference: str = Query(default="main"),
):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        table = get_dataset_table(dataset_name, data_location, reference)
        return describe_schema(table.schema)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting metadata for {dataset_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dataset metadata")


@app.get("/datasets/{dataset_name}/schema")
def get_dataset_schema(
    dataset_name: str,
    data_location: Optional[str] = Query(default=None),
    reference: str = Query(default="main"),
):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        table = get_dataset_table(dataset_name, data_location, reference)
        description = describe_schema(table.schema)
        return {
            "fields": description["fields"],
            "metadata": description["metadata"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting schema for {dataset_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dataset schema")

@app.get("/datasets/{dataset_name}/columns")
def get_dataset_columns(
    dataset_name: str,
    data_location: Optional[str] = Query(default=None),
    reference: str = Query(default="main"),
):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        table = get_dataset_table(dataset_name, data_location, reference)
        description = describe_schema(table.schema)
        return {"columns": description["columns"]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting columns for {dataset_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dataset columns")

@app.get("/datasets/{dataset_name}/rows")
def get_dataset_rows(
    dataset_name: str,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    columns: Optional[str] = Query(default=None),
    data_location: Optional[str] = Query(default=None),
    reference: str = Query(default="main"),
):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        table = get_dataset_table(dataset_name, data_location, reference)

        column_list = None
        if columns:
            column_list = [col.strip() for col in columns.split(",") if col.strip()]
            schema_columns = [field.name for field in table.schema]
            invalid_columns = [col for col in column_list if col not in schema_columns]
            if invalid_columns:
                raise HTTPException(status_code=400, detail=f"Invalid columns: {invalid_columns}")

        # Read rows, falling back to an informational response if the dataset is unreadable
        result_table = None
        total_count = 0

        try:
            try:
                # Native pagination: read only the requested rows from disk
                total_count = table.count_rows()
                end = min(offset + limit, total_count)
                if offset >= total_count:
                    result_table = pa.table({field.name: pa.array([], type=field.type) for field in table.schema})
                else:
                    offsets = list(range(offset, end))
                    builder = table.take_offsets(offsets)
                    if column_list:
                        available_columns = [col for col in column_list if col in [field.name for field in table.schema]]
                        if available_columns:
                            builder = builder.select(available_columns)
                    result_table = builder.to_arrow()

                logger.info(f"Read {result_table.num_rows} rows (offset={offset}, limit={limit}) from {dataset_name} ({total_count} total)")

            except (AttributeError, TypeError):
                # Fallback for older Lance versions without take_offsets/count_rows
                logger.info(f"Native pagination unavailable, using Arrow slice for {dataset_name}")
                arrow_table = table.to_arrow()
                total_count = arrow_table.num_rows

                if column_list:
                    available_columns = [col for col in column_list if col in arrow_table.column_names]
                    if available_columns:
                        arrow_table = arrow_table.select(available_columns)

                result_table = arrow_table.slice(offset, limit)

        except Exception as read_error:
            # Graceful degradation: any dataset that fails to read (corruption,
            # format error, unreadable bytes) returns a single informational row
            # instead of a 500.
            logger.warning(f"Failed to read rows from {dataset_name}, falling back to informational response: {read_error}")

            error_schema = pa.schema([
                pa.field("error", pa.string()),
                pa.field("dataset", pa.string()),
                pa.field("details", pa.string())
            ])
            error_data = [
                ["Unable to read dataset"],
                [dataset_name],
                [f"Error: {str(read_error)[:200]}"]
            ]
            result_table = pa.Table.from_arrays(error_data, schema=error_schema)
            total_count = 1

        rows = []
        for i in range(result_table.num_rows):
            row = {}
            for j, column_name in enumerate(result_table.column_names):
                try:
                    value = result_table.column(j)[i]
                    row[column_name] = serialize_arrow_value(value)
                except Exception as serialize_error:
                    logger.warning(f"Failed to serialize column {column_name} at row {i}: {serialize_error}")
                    row[column_name] = {"error": "Failed to read value"}
            rows.append(row)

        return {
            "rows": rows,
            "total": total_count,
            "limit": limit,
            "offset": offset
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting rows for {dataset_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dataset rows")

@app.get("/datasets/{dataset_name}/vector/preview")
def get_vector_preview(
    dataset_name: str,
    column: str,
    limit: int = Query(default=100, le=MAX_LIMIT),
    data_location: Optional[str] = Query(default=None),
    reference: str = Query(default="main"),
):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        table = get_dataset_table(dataset_name, data_location, reference)

        if column not in [field.name for field in table.schema]:
            raise HTTPException(status_code=400, detail=f"Column '{column}' not found")

        field = next(field for field in table.schema if field.name == column)
        if not ((pa.types.is_list(field.type) or pa.types.is_fixed_size_list(field.type)) and pa.types.is_floating(field.type.value_type)):
            raise HTTPException(status_code=400, detail=f"Column '{column}' is not a vector column")

        result = table.to_arrow().select([column]).slice(0, limit)
        vectors = result.column(0).to_pylist()

        valid_vectors = [v for v in vectors if v is not None]
        if not valid_vectors:
            return {"stats": None, "preview": []}

        all_values = [val for vec in valid_vectors for val in vec]

        stats = {
            "count": len(valid_vectors),
            "dim": len(valid_vectors[0]) if valid_vectors else 0,
            "min": min(all_values) if all_values else 0,
            "max": max(all_values) if all_values else 0,
            "mean": sum(all_values) / len(all_values) if all_values else 0
        }

        preview = []
        for vec in valid_vectors[:20]:
            if vec:
                preview.append({
                    "norm": float(sum(x*x for x in vec) ** 0.5),
                    "sample": vec[:32]
                })

        return {"stats": stats, "preview": preview}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting vector preview for {dataset_name}.{column}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get vector preview")

# Mount static files - use vanilla version by default
# In production, Docker copies vanilla files to /web
# For local development, serve from web/vanilla
static_dir = "/web"
if not os.path.exists(static_dir):
    # Local development - serve vanilla version
    static_dir = os.path.join(os.path.dirname(__file__), "..", "web", "vanilla")

if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    # Log version information on startup
    logger.info(f"Lance Data Viewer v{APP_VERSION}")
    logger.info(f"LanceDB: {lancedb.__version__}, PyArrow: {pa.__version__}")
    logger.info(f"Data path: {DATA_PATH}")

    uvicorn.run(app, host="0.0.0.0", port=8080)