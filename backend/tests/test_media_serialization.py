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

# A 24-byte ISO base media box: the size, the "ftyp" marker, the major
# brand, the minor version, and two compatible brands.
MP4_HEADER = (
    (24).to_bytes(4, "big")
    + b"ftyp"
    + b"isom"
    + b"\x00\x00\x02\x00"
    + b"isom"
    + b"iso2"
)


@pytest.mark.parametrize(
    ("payload", "media_type", "mime_type"),
    [
        (b"\x89PNG\r\n\x1a\npayload", "image", "image/png"),
        (b"\xff\xd8\xff\xe0payload", "image", "image/jpeg"),
        (b"RIFF\x00\x00\x00\x00WAVEpayload", "audio", "audio/wav"),
        (b"ID3\x04\x00\x00payload", "audio", "audio/mpeg"),
        (MP4_HEADER, "video", "video/mp4"),
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


@pytest.mark.parametrize(
    "payload",
    [
        # UTF-16 text starts with the byte order mark FF FE, which is also a
        # valid MPEG-1 Layer I frame header.
        "A note held in a binary column, long enough to be a frame.".encode(
            "utf-16"
        ),
        # Any binary at all can open with those two bytes.
        b"\xff\xe0" + b"\x00" * 200,
    ],
)
def test_binary_that_opens_like_a_frame_is_not_audio(payload):
    """A bare frame header is 11 bits, too few to name a value as audio."""
    assert detect_media_type(payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        # The box size is smaller than the header it counts.
        (8).to_bytes(4, "big") + MP4_HEADER[4:],
        # The box size is longer than the value that holds it.
        (4096).to_bytes(4, "big") + MP4_HEADER[4:],
        # A box holds whole 4-byte fields, so 26 cannot be a size.
        (26).to_bytes(4, "big") + MP4_HEADER[4:] + b"\x00" * 8,
        # Text that carries the marker at the offset a real box uses.
        b"the ftyp box names the brand of an MP4 file",
    ],
)
def test_ftyp_without_a_valid_box_size_is_not_video(payload):
    """"ftyp" is four printable characters four bytes into the value."""
    assert detect_media_type(payload) is None


def test_mp3_needs_an_id3_tag_to_be_detected():
    """Dropping the bare frame header costs us the tagless MP3.

    Such a value falls back to base64, which is what it did before media
    detection existed.
    """
    tagged = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb" + b"\x00" * 128
    assert detect_media_type(tagged) == ("audio", "audio/mpeg")
    assert detect_media_type(b"\xff\xfb" + b"\x00" * 128) is None


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
