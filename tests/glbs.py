"""GLBs written by the tests, from parts given by their triangles, so a check has exactly what a test needs."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import struct
from typing import Any
import zlib

FLOAT, UNSIGNED_BYTE, UNSIGNED_INT = 5126, 5121, 5125
FORMS = {FLOAT: "f", UNSIGNED_BYTE: "B", UNSIGNED_INT: "I"}

type Vector = tuple[float, float, float]
type Rgb = tuple[int, int, int]


@dataclass
class Part:
    positions: list[Vector]
    triangles: list[tuple[int, int, int]]
    normals: list[Vector] | None = None
    material: int | None = None
    joints: list[tuple[int, int, int, int]] | None = None
    weights: list[tuple[float, float, float, float]] | None = None
    uvs: list[tuple[float, float]] | None = None
    second_uvs: list[tuple[float, float]] | None = None


class Glb:
    def __init__(self) -> None:
        self.document: dict[str, Any] = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": []}],
            "nodes": [],
            "meshes": [],
            "materials": [],
            "accessors": [],
            "bufferViews": [],
            "buffers": [{"byteLength": 0}],
        }
        self.binary = bytearray()

    def material(self, name: str, detail: str | None = None) -> int:
        """A plain material, declaring the detail texture given."""
        self.document["materials"].append({"name": name, **({"extras": {"detail": detail}} if detail else {})})
        return len(self.document["materials"]) - 1

    def palette(
        self,
        rows: list[list[Rgb]],
        glow: list[list[Rgb]] | None = None,
        declared: dict[str, Any] | None = None,
        indexed: bool = False,
        detail: str | None = None,
    ) -> int:
        """A material drawn with a palette of these colors, top row first, nearest and clamped, with the emission
        palette given, declaring the palette and the detail texture given."""
        material: dict[str, Any] = {
            "name": "Palette",
            "pbrMetallicRoughness": {"baseColorTexture": {"index": self._texture(rows, indexed)}},
        }
        if glow is not None:
            material["emissiveTexture"] = {"index": self._texture(glow)}
            material["emissiveFactor"] = [1.0, 1.0, 1.0]
        extras = {key: value for key, value in (("palette", declared), ("detail", detail)) if value is not None}
        if extras:
            material["extras"] = extras
        self.document["materials"].append(material)
        return len(self.document["materials"]) - 1

    def _texture(self, rows: list[list[Rgb]], indexed: bool = False) -> int:
        self.document.setdefault("samplers", [{"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}])
        image = png([[(*color, 255) for color in row] for row in rows], indexed)
        self.document.setdefault("images", []).append({"bufferView": self._view(image), "mimeType": "image/png"})
        self.document.setdefault("textures", []).append({"sampler": 0, "source": len(self.document["images"]) - 1})
        return len(self.document["textures"]) - 1

    def _view(self, data: bytes) -> int:
        start = len(self.binary)
        self.binary += data
        self.binary += b"\0" * (-len(self.binary) % 4)
        self.document["bufferViews"].append({"buffer": 0, "byteOffset": start, "byteLength": len(data)})
        return len(self.document["bufferViews"]) - 1

    def mesh(self, *parts: Part) -> int:
        primitives = []
        for part in parts:
            attributes = {"POSITION": self._accessor(part.positions, FLOAT, "VEC3")}
            if part.normals is not None:
                attributes["NORMAL"] = self._accessor(part.normals, FLOAT, "VEC3")
            if part.joints is not None and part.weights is not None:
                attributes["JOINTS_0"] = self._accessor(part.joints, UNSIGNED_BYTE, "VEC4")
                attributes["WEIGHTS_0"] = self._accessor(part.weights, FLOAT, "VEC4")
            if part.uvs is not None:
                attributes["TEXCOORD_0"] = self._accessor(part.uvs, FLOAT, "VEC2")
            if part.second_uvs is not None:
                attributes["TEXCOORD_1"] = self._accessor(part.second_uvs, FLOAT, "VEC2")
            indices = [(index,) for triangle in part.triangles for index in triangle]
            primitive: dict[str, Any] = {
                "attributes": attributes,
                "indices": self._accessor(indices, UNSIGNED_INT, "SCALAR"),
            }
            if part.material is not None:
                primitive["material"] = part.material
            primitives.append(primitive)
        self.document["meshes"].append({"primitives": primitives})
        return len(self.document["meshes"]) - 1

    def node(
        self,
        name: str,
        mesh: int | None = None,
        parent: int | None = None,
        translation: Vector | None = None,
        rotation: tuple[float, float, float, float] | None = None,
        scale: Vector | None = None,
        extras: dict[str, Any] | None = None,
        skin: int | None = None,
    ) -> int:
        entry: dict[str, Any] = {"name": name}
        for key, value in (
            ("mesh", mesh),
            ("translation", translation),
            ("rotation", rotation),
            ("scale", scale),
            ("extras", extras),
            ("skin", skin),
        ):
            if value is not None:
                entry[key] = list(value) if isinstance(value, tuple) else value
        self.document["nodes"].append(entry)
        index = len(self.document["nodes"]) - 1
        if parent is None:
            self.document["scenes"][0]["nodes"].append(index)
        else:
            self.document["nodes"][parent].setdefault("children", []).append(index)
        return index

    def skin(self, joints: list[int]) -> int:
        self.document.setdefault("skins", []).append({"joints": joints})
        return len(self.document["skins"]) - 1

    def bytes(self) -> bytes:
        self.document["buffers"][0]["byteLength"] = len(self.binary)
        text = json.dumps(self.document).encode("utf-8")
        text += b" " * (-len(text) % 4)
        body = struct.pack("<II", len(text), 0x4E4F534A) + text
        body += struct.pack("<II", len(self.binary), 0x004E4942) + bytes(self.binary)
        return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body

    def write(self, path: Path) -> None:
        path.write_bytes(self.bytes())

    def _accessor(self, values: list[Any], component: int, kind: str) -> int:
        start = len(self.binary)
        for value in values:
            self.binary += struct.pack(f"<{len(value)}{FORMS[component]}", *value)
        self.binary += b"\0" * (-len(self.binary) % 4)
        self.document["bufferViews"].append({"buffer": 0, "byteOffset": start, "byteLength": len(self.binary) - start})
        accessor = {
            "bufferView": len(self.document["bufferViews"]) - 1,
            "componentType": component,
            "count": len(values),
            "type": kind,
        }
        self.document["accessors"].append(accessor)
        return len(self.document["accessors"]) - 1


def png(rows: list[list[tuple[int, int, int, int]]], indexed: bool = False) -> bytes:
    """A PNG of these pixels, top row first: RGBA, or indexed into a palette chunk of its colors."""
    if indexed:
        colors = list(dict.fromkeys(pixel for row in rows for pixel in row))
        lines = [bytes(colors.index(pixel) for pixel in row) for row in rows]
        extra = _chunk(b"PLTE", b"".join(bytes(color[:3]) for color in colors))
        extra += _chunk(b"tRNS", bytes(color[3] for color in colors))
    else:
        lines = [bytes(value for pixel in row for value in pixel) for row in rows]
        extra = b""
    header = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 3 if indexed else 6, 0, 0, 0)
    data = zlib.compress(b"".join(b"\0" + line for line in lines))
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + extra + _chunk(b"IDAT", data) + _chunk(b"IEND", b"")


def gray_png(rows: list[list[int]]) -> bytes:
    """An 8 bit grayscale PNG of these values, top row first."""
    header = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 0, 0, 0, 0)
    data = zlib.compress(b"".join(b"\0" + bytes(row) for row in rows))
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", data) + _chunk(b"IEND", b"")


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def box(
    size: Vector = (1.0, 1.0, 1.0),
    center: Vector = (0.0, 0.0, 0.0),
    material: int | None = None,
    uv: tuple[float, float] | None = None,
) -> Part:
    """A flat shaded box: each face its own four vertices, facing out, every one at the `uv` given."""
    half = [value / 2 for value in size]
    positions: list[Vector] = []
    normals: list[Vector] = []
    triangles: list[tuple[int, int, int]] = []
    for axis in range(3):
        for sign in (-1.0, 1.0):
            # The two axes across the face, ordered so its triangles wind counterclockwise seen from outside.
            u, v = ((axis + 1) % 3, (axis + 2) % 3) if sign > 0 else ((axis + 2) % 3, (axis + 1) % 3)
            start = len(positions)
            for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                corner = [0.0, 0.0, 0.0]
                corner[axis] = center[axis] + sign * half[axis]
                corner[u] = center[u] + du * half[u]
                corner[v] = center[v] + dv * half[v]
                positions.append((corner[0], corner[1], corner[2]))
                normal = [0.0, 0.0, 0.0]
                normal[axis] = sign
                normals.append((normal[0], normal[1], normal[2]))
            triangles += [(start, start + 1, start + 2), (start, start + 2, start + 3)]
    uvs = [uv] * len(positions) if uv is not None else None
    return Part(positions=positions, triangles=triangles, normals=normals, material=material, uvs=uvs)


def cylinder(radius: float, height: float, sides: int, smooth: bool = True) -> Part:
    """A cylinder's side along y, without caps: smooth, its sides sharing normals, or flat, each side its own."""
    positions: list[Vector] = []
    normals: list[Vector] = []
    triangles: list[tuple[int, int, int]] = []
    angles = [2 * math.pi * side / sides for side in range(sides)]
    if smooth:
        for angle in angles:
            x, z = math.cos(angle), math.sin(angle)
            positions += [(radius * x, 0.0, radius * z), (radius * x, height, radius * z)]
            normals += [(x, 0.0, z), (x, 0.0, z)]
        for side in range(sides):
            a, b = 2 * side, 2 * ((side + 1) % sides)
            triangles += [(a, a + 1, b + 1), (a, b + 1, b)]
        return Part(positions=positions, triangles=triangles, normals=normals)
    for side, angle in enumerate(angles):
        following = angles[(side + 1) % sides] if side + 1 < sides else 2 * math.pi
        middle = (angle + following) / 2
        start = len(positions)
        for point in (angle, following):
            positions += [
                (radius * math.cos(point), 0.0, radius * math.sin(point)),
                (radius * math.cos(point), height, radius * math.sin(point)),
            ]
        normals += [(math.cos(middle), 0.0, math.sin(middle))] * 4
        triangles += [(start, start + 1, start + 3), (start, start + 3, start + 2)]
    return Part(positions=positions, triangles=triangles, normals=normals)
