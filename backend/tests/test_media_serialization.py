import base64

import pyarrow as pa
import pytest

from serialize_value import (
    MEDIA_INLINE_MAX_BYTES,
    detect_media_type,
    serialize_value,
)


# A 4x1 24-bit bitmap: the 14-byte file header, a 40-byte DIB header, and
# one row of pixel data.
BMP_IMAGE = (
    b"BM"
    + (66).to_bytes(4, "little")
    + b"\x00\x00\x00\x00"
    + (54).to_bytes(4, "little")
    + (40).to_bytes(4, "little")
    + (4).to_bytes(4, "little")
    + (1).to_bytes(4, "little")
    + (1).to_bytes(2, "little")
    + (24).to_bytes(2, "little")
    + b"\x00" * 24
)


@pytest.mark.parametrize(
    ("payload", "media_type", "mime_type"),
    [
        (b"\x89PNG\r\n\x1a\npayload", "image", "image/png"),
        (b"\xff\xd8\xff\xe0payload", "image", "image/jpeg"),
        (b"RIFF\x00\x00\x00\x00WAVEpayload", "audio", "audio/wav"),
        (b"ID3\x04\x00\x00payload", "audio", "audio/mpeg"),
        (b"\x00\x00\x00\x18ftypisompayload", "video", "video/mp4"),
        (b"\x1aE\xdf\xa3payload", "video", "video/webm"),
        (BMP_IMAGE, "image", "image/bmp"),
    ],
)
def test_detect_media_type(payload, media_type, mime_type):
    assert detect_media_type(payload) == (media_type, mime_type)


@pytest.mark.parametrize(
    "payload",
    [
        b"BMW is a great car",
        b"BM25 scoring is used for full-text search",
        b"ID3 tag documentation",
        b"ID3v2 notes",
    ],
)
def test_text_that_starts_with_a_signature_stays_text(payload):
    """"BM" and "ID3" are printable, so plain text can start with them."""
    assert detect_media_type(payload) is None
    assert serialize_value(payload) == payload.decode("utf-8")


def test_media_binary_serialization():
    payload = b"\x89PNG\r\n\x1a\npayload"
    result = serialize_value(pa.scalar(payload, type=pa.large_binary()))
    assert result == {
        "type": "media",
        "media_type": "image",
        "mime_type": "image/png",
        "size": len(payload),
        "inline": True,
        "base64": base64.b64encode(payload).decode("ascii"),
    }


def test_media_at_the_size_limit_is_still_inline():
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MEDIA_INLINE_MAX_BYTES - 8)
    result = serialize_value(payload)
    assert len(payload) == MEDIA_INLINE_MAX_BYTES
    assert result["inline"] is True
    assert result["base64"] == base64.b64encode(payload).decode("ascii")


def test_media_over_the_size_limit_carries_no_payload():
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * MEDIA_INLINE_MAX_BYTES
    result = serialize_value(payload)
    assert result == {
        "type": "media",
        "media_type": "image",
        "mime_type": "image/png",
        "size": len(payload),
        "inline": False,
    }
    assert "base64" not in result


def test_non_media_binary_serialization_is_unchanged():
    assert serialize_value(b"hello") == "hello"
    payload = b"\xff\xfe\x01\x02"
    assert serialize_value(payload) == base64.b64encode(payload).decode("ascii")
