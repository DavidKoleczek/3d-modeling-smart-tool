"""PNG images as the color and detail checks read them, in plain Python, so a palette is read exactly and without
Blender."""

from collections.abc import Iterator
from dataclasses import dataclass
import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Each color type's channels: gray, RGB, an index into the palette chunk, gray and alpha, and RGBA.
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
INDEXED = 3

type Rgba = tuple[int, int, int, int]


@dataclass
class Png:
    width: int
    height: int
    # Top row first, 8 bits a channel.
    rows: list[list[Rgba]]


@dataclass
class PngHeader:
    width: int
    height: int
    bit_depth: int
    color_type: int
    # The kind of each chunk, in order.
    chunks: list[str]


def png_size(data: bytes) -> tuple[int, int]:
    """The image's width and height from its header, raising ValueError when it is not a PNG."""
    if data[:8] != SIGNATURE or len(data) < 24 or data[12:16] != b"IHDR":
        raise ValueError("it is not a PNG")
    width, height = struct.unpack_from(">II", data, 16)
    return width, height


def png_header(data: bytes) -> PngHeader:
    """The image's header and the kinds of its chunks, without its pixels, raising ValueError when it is not a PNG."""
    width, height = png_size(data)
    if len(data) < 26:
        raise ValueError("its header is cut short")
    depth, color = struct.unpack_from(">BB", data, 24)
    return PngHeader(
        width=width,
        height=height,
        bit_depth=depth,
        color_type=color,
        chunks=[kind.decode("latin-1") for kind, _ in _chunks(data)],
    )


def read_png(data: bytes, most_pixels: int) -> Png:
    """The image's pixels, raising ValueError, saying why, for one this cannot read or one over `most_pixels`."""
    width, height = png_size(data)
    if width * height > most_pixels:
        raise ValueError(f"at {width} by {height} pixels it is larger than this reads")
    header = b""
    palette = b""
    transparency = b""
    compressed = bytearray()
    for kind, chunk in _chunks(data):
        if kind == b"IHDR":
            header = chunk
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            transparency = chunk
        elif kind == b"IDAT":
            compressed += chunk
    depth, color, _, _, interlaced = struct.unpack_from(">BBBBB", header, 8)
    if color not in CHANNELS:
        raise ValueError(f"its color type {color} is not one PNG has")
    if interlaced:
        raise ValueError("it is interlaced, which this check does not read")
    if depth not in (8, 16) and not (color == INDEXED and depth in (1, 2, 4)):
        raise ValueError(f"its {depth} bit {'indices' if color == INDEXED else 'channels'} are not ones this reads")
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as error:
        raise ValueError(f"its image data does not decompress: {error}") from None
    channels = CHANNELS[color]
    stride = (width * channels * depth + 7) // 8
    if len(raw) < (stride + 1) * height:
        raise ValueError("its image data is cut short")
    # How far back the byte a filter compares with is: a whole pixel, or one byte for pixels smaller than one.
    step = max(1, channels * depth // 8)
    rows: list[list[Rgba]] = []
    above = bytearray(stride)
    for row in range(height):
        start = row * (stride + 1)
        line = _unfiltered(raw[start], bytearray(raw[start + 1 : start + 1 + stride]), above, step)
        rows.append(_pixels(line, width, color, depth, palette, transparency))
        above = line
    return Png(width=width, height=height, rows=rows)


def _chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    """Each chunk's kind and body, up to the end of the image."""
    offset = 8
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        yield kind, data[offset + 8 : offset + 8 + size]
        if kind == b"IEND":
            return
        offset += 12 + size


def _unfiltered(kind: int, line: bytearray, above: bytearray, step: int) -> bytearray:
    """A scanline with its filter undone: none, sub, up, average, or Paeth."""
    if kind > 4:
        raise ValueError(f"a row has the filter {kind}, which PNG does not have")
    for index in range(len(line)):
        left = line[index - step] if index >= step else 0
        up = above[index]
        corner = above[index - step] if index >= step else 0
        if kind == 1:
            line[index] = (line[index] + left) & 0xFF
        elif kind == 2:
            line[index] = (line[index] + up) & 0xFF
        elif kind == 3:
            line[index] = (line[index] + (left + up) // 2) & 0xFF
        elif kind == 4:
            estimate = left + up - corner
            nearest = min(
                (abs(estimate - left), 0, left), (abs(estimate - up), 1, up), (abs(estimate - corner), 2, corner)
            )
            line[index] = (line[index] + nearest[2]) & 0xFF
    return line


def _pixels(line: bytearray, width: int, color: int, depth: int, palette: bytes, transparency: bytes) -> list[Rgba]:
    if color == INDEXED:
        per_byte = 8 // depth
        mask = (1 << depth) - 1
        found: list[Rgba] = []
        for column in range(width):
            byte = line[column // per_byte] if depth < 8 else line[column]
            index = (byte >> (8 - depth * (column % per_byte + 1))) & mask if depth < 8 else byte
            if 3 * index + 3 > len(palette):
                raise ValueError("a pixel points past the end of its palette chunk")
            red, green, blue = palette[3 * index : 3 * index + 3]
            found.append((red, green, blue, transparency[index] if index < len(transparency) else 255))
        return found
    channels = CHANNELS[color]
    # 16 bit channels keep their high byte, which is all the check compares.
    size = depth // 8
    values = [line[index] for index in range(0, len(line), size)]
    found = []
    for column in range(width):
        pixel = values[column * channels : (column + 1) * channels]
        if color == 0:
            found.append((pixel[0], pixel[0], pixel[0], 255))
        elif color == 2:
            found.append((pixel[0], pixel[1], pixel[2], 255))
        elif color == 4:
            found.append((pixel[0], pixel[0], pixel[0], pixel[1]))
        else:
            found.append((pixel[0], pixel[1], pixel[2], pixel[3]))
    return found
