import base64
from datetime import date, datetime, time, timedelta

import numpy as np
import pyarrow as pa


# Media larger than this is described but not sent. Base64 adds a third to
# the size, so a page of 50 rows stays near 4 MB in the worst case.
MEDIA_INLINE_MAX_BYTES = 64 * 1024

# Sizes of the DIB header that follows the 14-byte BMP file header. Every
# valid BMP uses one of these, so it tells a real bitmap apart from text.
_BMP_DIB_HEADER_SIZES = frozenset({12, 40, 52, 56, 64, 108, 124})


def _is_bmp(raw: bytes) -> bool:
    """Check the BMP magic and the DIB header behind it.

    "BM" on its own is two printable characters, so text such as "BM25" would
    otherwise be read as a bitmap.
    """
    if len(raw) < 18 or not raw.startswith(b"BM"):
        return False
    return int.from_bytes(raw[14:18], "little") in _BMP_DIB_HEADER_SIZES


def _is_id3(raw: bytes) -> bool:
    """Check the ID3v2 magic, version, and synchsafe size.

    "ID3" is also three printable characters, so text such as "ID3 tags" would
    otherwise be read as an MP3.
    """
    if len(raw) < 10 or not raw.startswith(b"ID3"):
        return False
    if raw[3] not in (2, 3, 4) or raw[4] == 0xFF:
        return False
    return all(byte < 0x80 for byte in raw[6:10])


def _is_ftyp(raw: bytes) -> bool:
    """Check the ISO base media magic and the box size in front of it.

    "ftyp" starts four bytes into the file, so binary that holds those
    characters at that offset would otherwise be read as video. A real box
    is at least 16 bytes and holds a whole number of 4-byte fields, so the
    size tells the two apart.
    """
    if len(raw) < 16 or raw[4:8] != b"ftyp":
        return False
    box_size = int.from_bytes(raw[0:4], "big")
    return 16 <= box_size <= len(raw) and box_size % 4 == 0


def detect_media_type(raw: bytes):
    """Return (media category, MIME type) from common file signatures."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image", "image/gif"
    if _is_bmp(raw):
        return "image", "image/bmp"
    if raw.startswith((b"II*\x00", b"MM\x00*")):
        return "image", "image/tiff"

    if len(raw) >= 12 and raw.startswith(b"RIFF"):
        container = raw[8:12]
        if container == b"WEBP":
            return "image", "image/webp"
        if container == b"WAVE":
            return "audio", "audio/wav"
        if container == b"AVI ":
            return "video", "video/x-msvideo"

    if raw.startswith(b"fLaC"):
        return "audio", "audio/flac"
    if raw.startswith(b"OggS"):
        return "audio", "audio/ogg"
    if _is_id3(raw):
        return "audio", "audio/mpeg"

    if _is_ftyp(raw):
        brands = raw[8:32]
        if any(brand in brands for brand in (b"avif", b"avis")):
            return "image", "image/avif"
        if any(brand in brands for brand in (b"heic", b"heix")):
            return "image", "image/heic"
        if any(brand in brands for brand in (b"M4A ", b"M4B ")):
            return "audio", "audio/mp4"
        return "video", "video/mp4"
    if raw.startswith(b"\x1aE\xdf\xa3"):
        return "video", "video/webm"
    if raw.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")):
        return "video", "video/mpeg"

    return None


def _serialize_binary(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw

    media = detect_media_type(raw)
    if media:
        media_type, mime_type = media
        value = {
            "type": "media",
            "media_type": media_type,
            "mime_type": mime_type,
            "size": len(raw),
            "inline": len(raw) <= MEDIA_INLINE_MAX_BYTES,
        }
        if value["inline"]:
            value["base64"] = base64.b64encode(raw).decode("ascii")
        return value

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return base64.b64encode(raw).decode("ascii")


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
        return _serialize_binary(obj.as_py())

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
        return _serialize_binary(obj)
    if isinstance(obj, pa.BinaryScalar):
        return _serialize_binary(obj.as_py())
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
