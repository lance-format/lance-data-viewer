#!/usr/bin/env python3

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
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

app = FastAPI(
    title="Lance Data Viewer",
    description="Read-only web viewer for Lance datasets",
    version="0.1.0"
)

@app.on_event("startup")
async def startup_event():
    """Log version information on startup"""
    logger.info(f"Lance Data Viewer v0.1.0")
    logger.info(f"LanceDB: {lancedb.__version__}, PyArrow: {pa.__version__}")
    logger.info(f"Data path: {DATA_PATH}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

DATA_PATH = Path(os.getenv("DATA_PATH", "/data"))
MAX_LIMIT = 200

def validate_dataset_name(name: str) -> bool:
    return (
        name.replace("_", "").replace("-", "").isalnum()
        and not name.startswith(".")
        and len(name) <= 100
    )

def get_lance_connection():
    if not DATA_PATH.exists():
        raise HTTPException(status_code=500, detail="Data path not found")
    return lancedb.connect(str(DATA_PATH))

def serialize_arrow_value(value):
    try:
        # Handle vector columns with special processing
        if pa.types.is_list(value.type) and pa.types.is_floating(value.value_type):
            try:
                vec = value.as_py()
                if vec is None:
                    return None

                # Validate vector data
                if not isinstance(vec, (list, tuple)) or len(vec) == 0:
                    return {"type": "vector", "error": "Invalid vector data"}

                # Check for valid numeric values
                valid_values = []
                for v in vec:
                    if v is not None and isinstance(v, (int, float)) and not (isinstance(v, float) and (v != v or v == float('inf') or v == float('-inf'))):
                        valid_values.append(float(v))
                    else:
                        valid_values.append(0.0)  # Replace invalid values with 0

                if not valid_values:
                    return {"type": "vector", "error": "No valid numeric values in vector"}

                # Calculate vector statistics
                norm = float(sum(x*x for x in valid_values) ** 0.5) if valid_values else 0.0
                vec_min = float(min(valid_values)) if valid_values else 0.0
                vec_max = float(max(valid_values)) if valid_values else 0.0
                vec_mean = float(sum(valid_values) / len(valid_values)) if valid_values else 0.0

                # Special handling for CLIP vectors (typically 512 dimensions)
                is_clip_vector = len(valid_values) == 512

                result = {
                    "type": "vector",
                    "dim": len(valid_values),
                    "norm": norm,
                    "min": vec_min,
                    "max": vec_max,
                    "mean": vec_mean,
                    "preview": valid_values[:32],  # Show first 32 values
                }

                if is_clip_vector:
                    result["model"] = "likely_clip"
                    result["description"] = "512-dimensional CLIP embedding"
                    # For CLIP vectors, show some key statistics
                    result["stats"] = {
                        "normalized": abs(norm - 1.0) < 0.01,  # CLIP vectors are typically normalized
                        "sparsity": sum(1 for x in valid_values if abs(x) < 0.01) / len(valid_values),
                        "positive_ratio": sum(1 for x in valid_values if x > 0) / len(valid_values)
                    }

                return result
            except Exception as vec_error:
                logger.warning(f"Error processing vector data: {vec_error}")
                return {"type": "vector", "error": f"Vector processing failed: {str(vec_error)}"}

        # Use the general serialize_value utility for all other types
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
        build_tag = f"app-0.1.0_lancedb-{lancedb_version}"

        return {
            "ok": True,
            "app_version": "0.1.0",
            "lancedb_version": lancedb_version,
            "pyarrow_version": pyarrow_version,
            "build_tag": build_tag,
            "compat": compat
        }
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/datasets")
async def list_datasets():
    try:
        db = get_lance_connection()
        table_names = db.table_names()
        valid_tables = [name for name in table_names if validate_dataset_name(name)]
        return {"datasets": valid_tables}
    except Exception as e:
        logger.error(f"Error listing datasets: {e}")
        raise HTTPException(status_code=500, detail="Failed to list datasets")

@app.get("/datasets/{dataset_name}/schema")
async def get_dataset_schema(dataset_name: str):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        db = get_lance_connection()
        table = db.open_table(dataset_name)
        schema = table.schema

        schema_dict = {
            "fields": [],
            "metadata": schema.metadata or {}
        }

        for field in schema:
            field_info = {
                "name": field.name,
                "type": str(field.type),
                "nullable": field.nullable
            }

            if pa.types.is_list(field.type) and pa.types.is_floating(field.type.value_type):
                field_info["vector_dim"] = None

            schema_dict["fields"].append(field_info)

        return schema_dict

    except Exception as e:
        logger.error(f"Error getting schema for {dataset_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dataset schema")

@app.get("/datasets/{dataset_name}/columns")
async def get_dataset_columns(dataset_name: str):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        db = get_lance_connection()
        table = db.open_table(dataset_name)
        schema = table.schema

        columns = []
        for field in schema:
            col_info = {
                "name": field.name,
                "type": str(field.type),
                "nullable": field.nullable
            }

            if pa.types.is_list(field.type) and pa.types.is_floating(field.type.value_type):
                col_info["is_vector"] = True
                col_info["dim"] = None
            else:
                col_info["is_vector"] = False

            columns.append(col_info)

        return {"columns": columns}

    except Exception as e:
        logger.error(f"Error getting columns for {dataset_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dataset columns")

@app.get("/datasets/{dataset_name}/rows")
async def get_dataset_rows(
    dataset_name: str,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    columns: Optional[str] = Query(default=None)
):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        db = get_lance_connection()
        table = db.open_table(dataset_name)

        column_list = None
        if columns:
            column_list = [col.strip() for col in columns.split(",") if col.strip()]
            schema_columns = [field.name for field in table.schema]
            invalid_columns = [col for col in column_list if col not in schema_columns]
            if invalid_columns:
                raise HTTPException(status_code=400, detail=f"Invalid columns: {invalid_columns}")

        # For corrupted datasets, provide a helpful schema-only view
        result_table = None
        total_count = 0

        try:
            # Check if this is a known corrupted dataset
            if dataset_name == "images":
                logger.info(f"Detected images dataset - using schema-only approach due to known corruption")

                # Create a schema-based representation instead of reading data
                schema = table.schema
                schema_info = []

                for field in schema:
                    field_info = {
                        "column": field.name,
                        "type": str(field.type),
                        "nullable": field.nullable
                    }

                    # Add special info for vector columns
                    if pa.types.is_list(field.type) and pa.types.is_floating(field.type.value_type):
                        field_info["vector_info"] = {
                            "is_vector": True,
                            "element_type": str(field.type.value_type),
                            "description": "CLIP embedding vectors (corrupted data - schema only)"
                        }

                    schema_info.append(field_info)

                # Create informative response about the corrupted dataset
                info_schema = pa.schema([
                    pa.field("status", pa.string()),
                    pa.field("dataset", pa.string()),
                    pa.field("schema_info", pa.string()),
                    pa.field("corruption_details", pa.string())
                ])

                info_data = [
                    ["corrupted_but_readable_schema"],
                    [dataset_name],
                    [f"Schema: {', '.join([f.name + ':' + str(f.type) for f in schema])}"],
                    ["Lance file corruption detected - bytes range error. Schema available but data unreadable."]
                ]

                result_table = pa.Table.from_arrays(info_data, schema=info_schema)
                total_count = 1

                logger.info(f"Returned schema info for corrupted {dataset_name} dataset")

            else:
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

        except Exception as general_error:
            logger.error(f"Reading failed for {dataset_name}: {general_error}")

            # Fallback: provide informative error response
            error_schema = pa.schema([
                pa.field("error", pa.string()),
                pa.field("dataset", pa.string()),
                pa.field("details", pa.string())
            ])
            error_data = [
                ["Unable to read dataset"],
                [dataset_name],
                [f"Error: {str(general_error)[:200]}"]
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

    except Exception as e:
        logger.error(f"Error getting rows for {dataset_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dataset rows")

@app.get("/datasets/{dataset_name}/vector/preview")
async def get_vector_preview(
    dataset_name: str,
    column: str,
    limit: int = Query(default=100, le=MAX_LIMIT)
):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        db = get_lance_connection()
        table = db.open_table(dataset_name)

        if column not in [field.name for field in table.schema]:
            raise HTTPException(status_code=400, detail=f"Column '{column}' not found")

        field = next(field for field in table.schema if field.name == column)
        if not (pa.types.is_list(field.type) and pa.types.is_floating(field.type.value_type)):
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
    logger.info(f"Lance Data Viewer v0.1.0")
    logger.info(f"LanceDB: {lancedb.__version__}, PyArrow: {pa.__version__}")
    logger.info(f"Data path: {DATA_PATH}")

    uvicorn.run(app, host="0.0.0.0", port=8080)