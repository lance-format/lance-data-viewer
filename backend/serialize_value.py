import base64
from datetime import date, datetime, time, timedelta

import numpy as np
import pyarrow as pa


def _serialize_temporal(obj):
    """Convert temporal types to string representation."""
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return obj.total_seconds()
    return str(obj)


def _serialize_pyarrow_scalar(obj):
    """Convert PyArrow scalar types to JSON-serializable format."""
    if pa.types.is_binary(obj.type):
        return base64.b64encode(obj.as_py()).decode("utf-8")

    if pa.types.is_temporal(obj.type):
        return _serialize_temporal(obj.as_py())

    if pa.types.is_list(obj.type) or pa.types.is_map(obj.type):
        return [serialize_value(item) for item in obj.as_py()]

    if pa.types.is_struct(obj.type):
        return {
            field.name: serialize_value(obj.field(field.name).as_py())
            for field in obj.type
        }

    if pa.types.is_floating(obj.type):
        return float(obj.as_py())

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
    if isinstance(obj, (bytes, pa.BinaryScalar)):
        return base64.b64encode(obj).decode("utf-8")
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

    Handles:
    - bytes/PyArrow binary: Base64-encoded string
    - datetime types: ISO format string
    - PyArrow types: Python native types
    - nested types: recursive conversion
    """
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
