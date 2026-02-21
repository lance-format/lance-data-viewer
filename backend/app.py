#!/usr/bin/env python3

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
import json

import lancedb
import pyarrow as pa
from fastapi import FastAPI, HTTPException, Query, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import duckdb
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Union
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
    allow_methods=["GET", "POST"],
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
            "schema_evolution": lancedb_version >= "0.5",
            "lance_v2_format": lancedb_version >= "0.16"
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

            if (pa.types.is_list(field.type) or pa.types.is_fixed_size_list(field.type)) and pa.types.is_floating(field.type.value_type):
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

            if (pa.types.is_list(field.type) or pa.types.is_fixed_size_list(field.type)) and pa.types.is_floating(field.type.value_type):
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
    limit: int = Query(default=50, le=MAX_LIMIT),
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
                    if (pa.types.is_list(field.type) or pa.types.is_fixed_size_list(field.type)) and pa.types.is_floating(field.type.value_type):
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
                # For other datasets, use native LanceDB scanner for high-performance pagination
                logger.info(f"Using LanceDB scanner for {dataset_name} pagination")
                
                total_count = table.count_rows()
                
                # Fetch only the requested page of data
                scanner = table.scanner(
                    columns=column_list,
                    limit=limit,
                    offset=offset
                )
                result_table = scanner.to_table()
                logger.info(f"Successfully read {result_table.num_rows} rows from {dataset_name}")

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
        if not ((pa.types.is_list(field.type) or pa.types.is_fixed_size_list(field.type)) and pa.types.is_floating(field.type.value_type)):
            raise HTTPException(status_code=400, detail=f"Column '{column}' is not a vector column")

        # Use scanner to only load the requested column and limit
        result = table.scanner(columns=[column], limit=limit).to_table()
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

class DataTablesRequest(BaseModel):
    draw: int
    start: int
    length: int
    search: Dict[str, Any]
    order: List[Dict[str, Any]]
    columns: List[Dict[str, Any]]
    searchBuilder: Optional[Dict[str, Any]] = None

def parse_searchbuilder_rules(rules: Dict[str, Any]) -> str:
    """Recursively parse DataTables searchBuilder rules into SQL"""
    # Handle both "rules"/"condition" and "criteria"/"logic" naming conventions
    child_rules = rules.get("rules") or rules.get("criteria")
    condition = rules.get("condition") or rules.get("logic")
    
    if child_rules is not None and condition is not None:
        condition = condition.upper()  # Ensure AND/OR is uppercase
        sql_parts = []
        for rule in child_rules:
            part = parse_searchbuilder_rules(rule)
            if part:
                sql_parts.append(part)
        
        if not sql_parts:
            return ""
            
        joiner = f" {condition} "
        return f"({joiner.join(sql_parts)})"
    
    # Base rule
    field = rules.get("origData") or rules.get("data")
    if field is None:
        return ""
        
    cond = rules.get("condition")
    if not cond:
        return ""
        
    values = rules.get("value", [])
    val1 = values[0] if len(values) > 0 else None
    val2 = values[1] if len(values) > 1 else None
    
    # Safe column name quoting
    col = f'"{field}"'
    
    # Helper to quote strings but leave numbers (if they are numbers)
    def sql_val(v):
        if v is None: return "NULL"
        if isinstance(v, (int, float)): return str(v)
        # Try to see if it's a numeric string
        try:
            if v.replace('.','',1).isdigit(): return v
        except: pass
        return f"'{v}'"

    if cond == "=":
        return f"{col} = {sql_val(val1)}"
    elif cond == "!=":
        return f"{col} != {sql_val(val1)}"
    elif cond == "<":
        return f"{col} < {sql_val(val1)}"
    elif cond == "<=":
        return f"{col} <= {sql_val(val1)}"
    elif cond == ">":
        return f"{col} > {sql_val(val1)}"
    elif cond == ">=":
        return f"{col} >= {sql_val(val1)}"
    elif cond == "contains":
        return f"CAST({col} AS VARCHAR) ILIKE '%{val1}%'"
    elif cond == "!contains":
        return f"CAST({col} AS VARCHAR) NOT ILIKE '%{val1}%'"
    elif cond == "starts":
        return f"CAST({col} AS VARCHAR) ILIKE '{val1}%'"
    elif cond == "!starts":
        return f"CAST({col} AS VARCHAR) NOT ILIKE '{val1}%'"
    elif cond == "ends":
        return f"CAST({col} AS VARCHAR) ILIKE '%{val1}'"
    elif cond == "!ends":
        return f"CAST({col} AS VARCHAR) NOT ILIKE '%{val1}'"
    elif cond == "null":
        return f"{col} IS NULL"
    elif cond == "!null":
        return f"{col} IS NOT NULL"
    elif cond == "between":
        return f"{col} BETWEEN {sql_val(val1)} AND {sql_val(val2)}"
    elif cond == "!between":
        return f"{col} NOT BETWEEN {sql_val(val1)} AND {sql_val(val2)}"
        
    return ""

@app.post("/datasets/{dataset_name}/datatables")
async def get_datatables_data(dataset_name: str, request: Request):
    if not validate_dataset_name(dataset_name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")

    try:
        body = await request.body()
        logger.info(f"Received datatables request for {dataset_name}. Body size: {len(body)}")
        
        try:
            payload_dict = json.loads(body)
            payload = DataTablesRequest(**payload_dict)
        except Exception as json_err:
            logger.error(f"Failed to parse JSON body: {json_err}. Body: {body[:500]}")
            return {
                "draw": 0,
                "error": f"JSON Parse Error: {str(json_err)}",
                "data": []
            }
        db = get_lance_connection()
        table = db.open_table(dataset_name)
        
        # Get total records without filtering - very fast in Lance
        recordsTotal = table.count_rows()
        
        # Connect to duckdb
        con = duckdb.connect()
        
        # Register the dataset. Using to_lance() provides the underlying Dataset object,
        # which DuckDB can scan lazily without materializing all rows into memory.
        try:
            # check if to_lance() exists, otherwise use the table object directly
            # which might implement the arrow protocol
            dataset_source = getattr(table, "to_lance", lambda: table)()
            con.register('dataset', dataset_source)
            logger.info(f"Registered dataset '{dataset_name}' lazily")
        except Exception as reg_err:
            logger.warning(f"Lazy registration failed for {dataset_name}: {reg_err}. Materializing as fallback.")
            con.register('dataset', table.to_arrow())
        
        # Build SQL Query parts
        where_clauses = []
        
        # 1. Global Search
        search_value = payload.search.get("value")
        if search_value:
            global_search = []
            for col in payload.columns:
                if col.get("searchable") and col.get("data"):
                    # Cast everything to string for global search
                    col_name = col["data"]
                    global_search.append(f"CAST(\"{col_name}\" AS VARCHAR) ILIKE '%{search_value}%'")
            if global_search:
                where_clauses.append(f"({' OR '.join(global_search)})")
                
        # 2. SearchBuilder
        if payload.searchBuilder:
            # support both "rules" and "criteria" formats
            rules_key = "rules" if "rules" in payload.searchBuilder else "criteria"
            if rules_key in payload.searchBuilder and payload.searchBuilder[rules_key]:
                sb_sql = parse_searchbuilder_rules(payload.searchBuilder)
                if sb_sql:
                    where_clauses.append(sb_sql)
                
        # 3. Column specific searches
        for col in payload.columns:
            if col.get("searchable") and col.get("search") and col["search"].get("value"):
                col_val = col["search"]["value"]
                col_name = col["data"]
                where_clauses.append(f"CAST(\"{col_name}\" AS VARCHAR) ILIKE '%{col_val}%'")

        where_sql = ""
        if where_clauses:
            where_sql = f" WHERE {' AND '.join(where_clauses)}"
            
        logger.info(f"Final WHERE clause: {where_sql}")
            
        # Build Order By
        order_sql = ""
        if payload.order:
            order_parts = []
            for order in payload.order:
                col_idx = order.get("column")
                if col_idx is not None and col_idx < len(payload.columns):
                    col_name = payload.columns[col_idx].get("data")
                    if col_name:
                        dir = order.get("dir", "asc").upper()
                        if dir not in ["ASC", "DESC"]: 
                            dir = "ASC"
                        order_parts.append(f"\"{col_name}\" {dir}")
            
            if order_parts:
                order_sql = f" ORDER BY {', '.join(order_parts)}"
                
        # Get total records after filtering
        if where_clauses:
            count_query = f"SELECT COUNT(*) FROM dataset {where_sql}"
            recordsFiltered = con.execute(count_query).fetchone()[0]
        else:
            recordsFiltered = recordsTotal
        
        # Get the actual page of data
        limit = payload.length
        offset = payload.start
        
        data_query = f"SELECT * FROM dataset {where_sql} {order_sql}"
        logger.info(f"Executing data query: {data_query}")
        if limit > 0:  # DataTables uses -1 for "All"
            data_query += f" LIMIT {limit} OFFSET {offset}"
            
        result_arrow = con.execute(data_query).arrow()
        
        # duckdb .arrow() might return a RecordBatchReader in some versions,
        # so we need to collect it into a Table
        if hasattr(result_arrow, "read_all"):
            result_arrow = result_arrow.read_all()
            
        # Process result rows just like the standard /rows endpoint
        rows = []
        for i in range(result_arrow.num_rows):
            row = {}
            for j, column_name in enumerate(result_arrow.column_names):
                try:
                    value = result_arrow.column(j)[i]
                    row[column_name] = serialize_arrow_value(value)
                except Exception as serialize_error:
                    logger.warning(f"Failed to serialize column {column_name} at row {i}: {serialize_error}")
                    row[column_name] = {"error": "Failed to read value"}
            rows.append(row)
            
        return {
            "draw": payload.draw,
            "recordsTotal": recordsTotal,
            "recordsFiltered": recordsFiltered,
            "data": rows
        }

    except Exception as e:
        logger.error(f"Error entirely: {e}")
        return {
            "draw": payload.draw,
            "error": str(e),
            "data": []
        }


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