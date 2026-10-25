"""A glTF binary as the check reads it: the nodes of its scene in model space, their meshes as triangles with their
texture coordinates, extras, and the images it embeds."""

import base64
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import struct
from typing import Any

from modeling_3d.schemas import Modeling3dError

MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
BINARY_CHUNK = 0x004E4942
# Each component type: its struct format, and what a normalized integer of it is divided by.
COMPONENTS: dict[int, tuple[str, float]] = {
    5120: ("b", 127.0),
    5121: ("B", 255.0),
    5122: ("h", 32767.0),
    5123: ("H", 65535.0),
    5125: ("I", 4294967295.0),
    5126: ("f", 1.0),
}
WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
TRIANGLES, TRIANGLE_STRIP, TRIANGLE_FAN = 4, 5, 6
# Compressed geometry needs a decoder this reader does not have.
COMPRESSIONS = ("KHR_draco_mesh_compression", "EXT_meshopt_compression")
IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)

type Vector = tuple[float, float, float]
# Sixteen numbers, column by column, as glTF keeps a matrix.
type Matrix = tuple[float, ...]


@dataclass
class Primitive:
    """One part of a mesh drawn with one material, in model space."""

    material: int | None
    positions: list[Vector]
    # As stored rather than in model space: they only tell a smooth edge from a hard one.
    normals: list[Vector] | None
    triangles: list[tuple[int, int, int]]
    # Each vertex's joints and their weights, across every set of them.
    joints: list[tuple[int, ...]] | None = None
    weights: list[tuple[float, ...]] | None = None
    # Each set of texture coordinates, TEXCOORD_0 first, as glTF keeps them: from the image's top left corner.
    uvs: list[list[tuple[float, float]]] = field(default_factory=list)


@dataclass
class Node:
    index: int
    name: str
    parent: int | None
    world: Matrix
    mesh: int | None
    skin: int | None
    # A camera or a light, which is not a marker.
    other: bool
    extras: dict[str, Any]
    children: list[int] = field(default_factory=list)
    primitives: list[Primitive] = field(default_factory=list)


@dataclass
class Scene:
    document: dict[str, Any]
    # Those in the scene in outline order: each node, then everything under it.
    nodes: list[Node]
    binary: bytes = b""

    def node(self, index: int) -> Node:
        return next(node for node in self.nodes if node.index == index)

    @property
    def meshes(self) -> list[Node]:
        return [node for node in self.nodes if node.mesh is not None]

    @property
    def joints(self) -> set[int]:
        return {joint for skin in self.document.get("skins", []) for joint in skin.get("joints", [])}

    def material_name(self, material: int | None) -> str:
        if material is None:
            return "the default material"
        return self.document.get("materials", [])[material].get("name") or f"material {material}"

    def image(self, index: int) -> bytes:
        """The bytes of an image the GLB embeds, raising ValueError, saying why, for one it does not."""
        images = self.document.get("images", [])
        if not 0 <= index < len(images):
            raise ValueError(f"the GLB has no image {index}")
        image = images[index]
        uri = image.get("uri")
        if isinstance(uri, str) and uri.startswith("data:") and ";base64," in uri:
            return base64.b64decode(uri.split(";base64,", 1)[1])
        if uri is not None:
            raise ValueError(f"it is kept outside the GLB, at {uri}")
        if "bufferView" not in image:
            raise ValueError("it has neither data nor a place it is kept")
        view = self.document["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        if view.get("buffer", 0) != 0 or start + view["byteLength"] > len(self.binary):
            raise ValueError("its data is not in the GLB's binary chunk")
        return self.binary[start : start + view["byteLength"]]


def read_scene(path: Path) -> Scene:
    """The scene in the GLB at `path`, raising Modeling3dError when it is not one this can read."""
    data = path.read_bytes()
    document, binary = _chunks(path, data)
    compressed = [name for name in document.get("extensionsRequired", []) if name in COMPRESSIONS]
    if compressed:
        raise Modeling3dError(
            f"{path} is compressed with {', '.join(compressed)}, which the check cannot read. Export it without "
            "compression.",
            "bad-glb",
        )
    reader = _Reader(document, binary, path)
    nodes = document.get("nodes", [])
    scenes = document.get("scenes", [])
    if scenes:
        roots = scenes[document.get("scene", 0)].get("nodes", [])
    else:
        children = {child for node in nodes for child in node.get("children", [])}
        roots = [index for index in range(len(nodes)) if index not in children]
    found: list[Node] = []
    # Each node's children come right after it, as an outline of the scene lists them.
    pending: list[tuple[int, int | None, Matrix]] = [(index, None, IDENTITY) for index in reversed(roots)]
    while pending:
        index, parent, above = pending.pop()
        entry = nodes[index]
        world = multiply(above, _local(entry))
        extensions = entry.get("extensions", {})
        node = Node(
            index=index,
            name=entry.get("name") or f"node {index}",
            parent=parent,
            world=world,
            mesh=entry.get("mesh"),
            skin=entry.get("skin"),
            other="camera" in entry or "KHR_lights_punctual" in extensions,
            extras=entry.get("extras") if isinstance(entry.get("extras"), dict) else {},
            children=list(entry.get("children", [])),
        )
        if node.mesh is not None:
            node.primitives = [
                reader.primitive(primitive, world) for primitive in document["meshes"][node.mesh]["primitives"]
            ]
        found.append(node)
        pending += [(child, index, world) for child in reversed(node.children)]
    return Scene(document=document, nodes=found, binary=binary)


def multiply(first: Matrix, second: Matrix) -> Matrix:
    return tuple(
        sum(first[k * 4 + row] * second[column * 4 + k] for k in range(4)) for column in range(4) for row in range(4)
    )


def transform(matrix: Matrix, point: Vector) -> Vector:
    x, y, z = point
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    )


def rotate(matrix: Matrix, direction: Vector) -> Vector:
    """A direction carried by the matrix, without its translation."""
    x, y, z = direction
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z,
        matrix[1] * x + matrix[5] * y + matrix[9] * z,
        matrix[2] * x + matrix[6] * y + matrix[10] * z,
    )


def translation(matrix: Matrix) -> Vector:
    return matrix[12], matrix[13], matrix[14]


def subtract(first: Vector, second: Vector) -> Vector:
    return first[0] - second[0], first[1] - second[1], first[2] - second[2]


def cross(first: Vector, second: Vector) -> Vector:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def dot(first: Vector, second: Vector) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def length(vector: Vector) -> float:
    return math.sqrt(dot(vector, vector))


def normalized(vector: Vector) -> Vector | None:
    size = length(vector)
    if size == 0:
        return None
    return vector[0] / size, vector[1] / size, vector[2] / size


def _chunks(path: Path, data: bytes) -> tuple[dict[str, Any], bytes]:
    """The GLB's JSON and its binary chunk."""
    if len(data) < 20 or data[:4] != MAGIC:
        raise Modeling3dError(f"{path} is not a glTF binary. Rebuild it with model.py.", "bad-glb")
    offset = 12
    document: dict[str, Any] | None = None
    binary = b""
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8 : offset + 8 + size]
        if kind == JSON_CHUNK and document is None:
            try:
                document = json.loads(chunk)
            except ValueError as error:
                raise Modeling3dError(
                    f"{path} holds JSON that does not parse: {error}. Rebuild it.", "bad-glb"
                ) from None
        elif kind == BINARY_CHUNK and not binary:
            binary = chunk
        offset += 8 + size
    if not isinstance(document, dict):
        raise Modeling3dError(f"{path} has no glTF JSON. Rebuild it with model.py.", "bad-glb")
    return document, binary


def _local(entry: dict[str, Any]) -> Matrix:
    """A node's transform within its parent: its matrix, or its translation, rotation, and scale."""
    if "matrix" in entry:
        return tuple(float(value) for value in entry["matrix"])
    x, y, z, w = entry.get("rotation", (0.0, 0.0, 0.0, 1.0))
    sx, sy, sz = entry.get("scale", (1.0, 1.0, 1.0))
    tx, ty, tz = entry.get("translation", (0.0, 0.0, 0.0))
    return (
        (1 - 2 * (y * y + z * z)) * sx,
        (2 * (x * y + w * z)) * sx,
        (2 * (x * z - w * y)) * sx,
        0.0,
        (2 * (x * y - w * z)) * sy,
        (1 - 2 * (x * x + z * z)) * sy,
        (2 * (y * z + w * x)) * sy,
        0.0,
        (2 * (x * z + w * y)) * sz,
        (2 * (y * z - w * x)) * sz,
        (1 - 2 * (x * x + y * y)) * sz,
        0.0,
        tx,
        ty,
        tz,
        1.0,
    )


class _Reader:
    """Reads accessors out of the binary chunk."""

    def __init__(self, document: dict[str, Any], binary: bytes, path: Path) -> None:
        self._document = document
        self._binary = binary
        self._path = path

    def primitive(self, entry: dict[str, Any], world: Matrix) -> Primitive:
        attributes = entry.get("attributes", {})
        if "POSITION" not in attributes:
            raise Modeling3dError(f"{self._path} has a mesh primitive without positions. Rebuild it.", "bad-glb")
        positions = [
            transform(world, (values[0], values[1], values[2])) for values in self.read(attributes["POSITION"])
        ]
        normals = None
        if "NORMAL" in attributes:
            normals = [(values[0], values[1], values[2]) for values in self.read(attributes["NORMAL"])]
        indices = (
            [int(values[0]) for values in self.read(entry["indices"])]
            if "indices" in entry
            else list(range(len(positions)))
        )
        joints: list[tuple[int, ...]] | None = None
        weights: list[tuple[float, ...]] | None = None
        sets = 0
        while f"JOINTS_{sets}" in attributes and f"WEIGHTS_{sets}" in attributes:
            sets += 1
        if sets:
            joint_sets = [self.read(attributes[f"JOINTS_{index}"]) for index in range(sets)]
            weight_sets = [self.read(attributes[f"WEIGHTS_{index}"]) for index in range(sets)]
            joints = [
                tuple(int(value) for values in each for value in values) for each in zip(*joint_sets, strict=True)
            ]
            weights = [
                tuple(float(value) for values in each for value in values) for each in zip(*weight_sets, strict=True)
            ]
        uvs: list[list[tuple[float, float]]] = []
        while f"TEXCOORD_{len(uvs)}" in attributes:
            uvs.append([(values[0], values[1]) for values in self.read(attributes[f"TEXCOORD_{len(uvs)}"])])
        return Primitive(
            material=entry.get("material"),
            positions=positions,
            normals=normals,
            triangles=_triangles(entry.get("mode", TRIANGLES), indices),
            joints=joints,
            weights=weights,
            uvs=uvs,
        )

    def read(self, index: int) -> list[tuple[float, ...]]:
        """An accessor's elements, normalized integers as fractions."""
        accessor = self._document["accessors"][index]
        form, scale = COMPONENTS[accessor["componentType"]]
        width = WIDTHS[accessor["type"]]
        count = accessor["count"]
        element = struct.Struct(f"<{width}{form}")
        values: list[tuple[float, ...]]
        if "bufferView" in accessor:
            view = self._document["bufferViews"][accessor["bufferView"]]
            if view.get("buffer", 0) != 0:
                raise Modeling3dError(
                    f"{self._path} keeps geometry in a buffer outside the file, which the check cannot read. Export "
                    "it as one GLB.",
                    "bad-glb",
                )
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            stride = view.get("byteStride") or element.size
            if start + stride * (count - 1) + element.size > len(self._binary):
                raise Modeling3dError(
                    f"{self._path} is cut short: an accessor runs past its data. Rebuild it.", "bad-glb"
                )
            if stride == element.size:
                values = list(element.iter_unpack(self._binary[start : start + count * element.size]))
            else:
                values = [element.unpack_from(self._binary, start + stride * item) for item in range(count)]
        else:
            values = [(0.0,) * width] * count
        if "sparse" in accessor:
            values = self._sparse(accessor["sparse"], values, element)
        if accessor.get("normalized") and form != "f":
            values = [tuple(max(value / scale, -1.0) for value in each) for each in values]
        return values

    def _sparse(
        self, sparse: dict[str, Any], values: list[tuple[float, ...]], element: struct.Struct
    ) -> list[tuple[float, ...]]:
        count = sparse["count"]
        indices, given = sparse["indices"], sparse["values"]
        form = COMPONENTS[indices["componentType"]][0]
        index_view = self._document["bufferViews"][indices["bufferView"]]
        value_view = self._document["bufferViews"][given["bufferView"]]
        index_start = index_view.get("byteOffset", 0) + indices.get("byteOffset", 0)
        value_start = value_view.get("byteOffset", 0) + given.get("byteOffset", 0)
        replaced = list(values)
        for item in range(count):
            (target,) = struct.unpack_from(f"<{form}", self._binary, index_start + item * struct.calcsize(form))
            replaced[target] = element.unpack_from(self._binary, value_start + item * element.size)
        return replaced


def _triangles(mode: int, indices: list[int]) -> list[tuple[int, int, int]]:
    """The primitive's triangles, from a list, a strip, or a fan; none for points and lines."""
    if mode == TRIANGLES:
        return [(indices[i], indices[i + 1], indices[i + 2]) for i in range(0, len(indices) - 2, 3)]
    if mode == TRIANGLE_STRIP:
        return [
            (indices[i], indices[i + 1], indices[i + 2]) if i % 2 == 0 else (indices[i + 1], indices[i], indices[i + 2])
            for i in range(len(indices) - 2)
        ]
    if mode == TRIANGLE_FAN:
        return [(indices[0], indices[i], indices[i + 1]) for i in range(1, len(indices) - 1)]
    return []
