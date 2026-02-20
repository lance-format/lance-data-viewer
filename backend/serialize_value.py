import base64
from datetime import date, datetime, time, timedelta

import numpy as np
import pyarrow as pa


def _serialize_temporal(obj):
    """Convert temporal types to string representation."""
    if obj is None:
        return None
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return obj.total_seconds()
    return str(obj)


def _serialize_pyarrow_scalar(obj):
    """Convert PyArrow scalar types to JSON-serializable format."""
    if not getattr(obj, "is_valid", True):
        return None

    if pa.types.is_binary(obj.type) or pa.types.is_large_binary(obj.type):
        raw = obj.as_py()
        if raw is None:
            return None
        if isinstance(raw, str):
            return raw
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(raw).decode("utf-8")

    if pa.types.is_temporal(obj.type):
        return _serialize_temporal(obj.as_py())

    if (
        pa.types.is_list(obj.type)
        or pa.types.is_map(obj.type)
        or pa.types.is_fixed_size_list(obj.type)
    ):
        val = obj.as_py()
        if val is None:
            return None
        return [serialize_value(item) for item in val]

    if pa.types.is_struct(obj.type):
        # PREVENTS "'StructScalar' object has no attribute 'field'"
        val = obj.as_py()
        if val is None:
            return None
        return {k: serialize_value(v) for k, v in val.items()}

    if pa.types.is_floating(obj.type):
        val = obj.as_py()
        return float(val) if val is not None else None

    return obj.as_py()


def _serialize_container(obj):
    """Convert container types (dict, list, tuple) recursively."""
    if isinstance(obj, dict):
        return {key: serialize_value(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_value(item) for item in obj]
    return obj


def _serialize_basic_types(obj):
    """Convert basic Python types to JSON-serializable format."""
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(obj).decode("utf-8")
    if isinstance(obj, pa.BinaryScalar):
        raw = obj.as_py()
        if raw is None:
            return None
        if isinstance(raw, str):
            return raw
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(raw).decode("utf-8")
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return obj.total_seconds()
    if isinstance(obj, np.number):
        return obj.item()
    return obj


def serialize_value(obj):
    """
    Recursively convert objects to JSON-serializable format.
    """
    if obj is None:
        return None

    # First try basic type conversions
    result = _serialize_basic_types(obj)
    if result is not obj:
        return result

    # Then try container types
    result = _serialize_container(obj)
    if result is not obj:
        return result

    # Finally try PyArrow scalar types
    if isinstance(obj, pa.Scalar):
        return _serialize_pyarrow_scalar(obj)

    return obj
