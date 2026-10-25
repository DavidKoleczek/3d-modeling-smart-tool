"""A model's detail texture as the detail checks read it: the file its materials declare, the PNG's header, and where
each triangle drawn with it lands on it, through the second set of texture coordinates."""

from collections import defaultdict
from dataclasses import dataclass, field
import math
from pathlib import Path, PurePosixPath

from modeling_3d.capabilities.create_3d_model.check.glb import Node, Scene, Vector, cross, length, subtract
from modeling_3d.capabilities.create_3d_model.check.palette import Palette, swatch_of
from modeling_3d.capabilities.create_3d_model.check.png import PngHeader, png_header

UV_SET = 1
# How close a triangle's corners sit on the texture, in its pixels, to be at one point and take no detail, and how long
# an edge must be on it for its texels per meter to be measured past the float error an export leaves.
POINT_TEXELS = 0.01
MEASURED_TEXELS = 1.0
# How many times as many texels a meter one edge of a triangle has as another before the triangle is stretched.
STRETCHED = 1.25
# How far two triangles must reach into each other on the texture, in its pixels, to share texels rather than meet
# along an edge, and how many cells across its longer side the search for them divides it into.
OVERLAP_TEXELS = 0.05
OVERLAP_CELLS = 64
UV_TOLERANCE = 1e-6

type Corners = tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


@dataclass
class Detail:
    """The grayscale texture the materials that declare it multiply their base color by twice."""

    file: str
    materials: list[int]
    problems: list[str] = field(default_factory=list)
    header: PngHeader | None = None
    # Why the texture could not be read, when it could not.
    unreadable: str | None = None
    # How long before model.glb the texture was written, in seconds.
    older: float = 0.0


@dataclass
class Painted:
    """A triangle that takes detail: its corners on the texture in pixels, from its top left, where it is on the model,
    and its role, as the palette's column its other UVs land in."""

    corners: Corners
    center: Vector
    role: int | None


@dataclass
class Unwrapped:
    """Where one part's triangles drawn with a material that declares the detail land on the texture."""

    area: float = 0.0
    painted_area: float = 0.0
    # By role, the area of its triangles and of those that take detail.
    role_area: dict[int | None, float] = field(default_factory=lambda: defaultdict(float))
    role_painted: dict[int | None, float] = field(default_factory=lambda: defaultdict(float))
    painted: list[Painted] = field(default_factory=list)
    # Where each triangle at one point sits on the texture, in pixels.
    points: list[tuple[float, float]] = field(default_factory=list)
    # Texels per meter along each edge long enough to measure, and the area its triangles cover on the texture, in
    # pixels.
    densities: list[float] = field(default_factory=list)
    texels: float = 0.0
    stretched: list[Vector] = field(default_factory=list)
    outside: list[Vector] = field(default_factory=list)
    without_uvs: int = 0
    # Triangles drawn with a material that declares no detail.
    undeclared: int = 0


def read_detail(scene: Scene, glb: Path) -> Detail | None:
    """The detail texture the model's materials declare; None when none declares one."""
    materials = scene.document.get("materials", [])
    declared = {
        index: material["extras"]["detail"]
        for index, material in enumerate(materials)
        if isinstance(material.get("extras"), dict) and "detail" in material["extras"]
    }
    if not declared:
        return None
    named = {index: value for index, value in declared.items() if isinstance(value, str) and value}
    detail = Detail(file=next(iter(named.values()), ""), materials=list(declared))
    if len(named) < len(declared):
        detail.problems.append(
            'A material declares its detail as something other than the name of its file, such as "model-detail.png".'
        )
    if len(set(named.values())) > 1:
        detail.problems.append(
            f"Its materials name different files, {', '.join(sorted(set(named.values())))}, so only {detail.file} "
            "is read."
        )
    if not detail.file:
        detail.unreadable = "no material names its file"
        return detail
    relative = PurePosixPath(detail.file.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or ":" in detail.file:
        detail.unreadable = f"{detail.file} is outside the model's directory"
        return detail
    path = glb.parent / relative
    if not path.is_file():
        detail.unreadable = f"there is no {detail.file} beside {glb.name}"
        return detail
    detail.older = max(0.0, glb.stat().st_mtime - path.stat().st_mtime)
    try:
        detail.header = png_header(path.read_bytes())
    except ValueError as error:
        detail.unreadable = str(error)
        return detail
    if not detail.header.width or not detail.header.height:
        detail.header = None
        detail.unreadable = "it has no pixels"
    return detail


def unwrapped(detail: Detail, node: Node, palette: Palette | None) -> Unwrapped:
    """Where the node's triangles land on the detail texture."""
    assert detail.header is not None
    width, height = detail.header.width, detail.header.height
    found = Unwrapped()
    for primitive in node.primitives:
        if primitive.material not in detail.materials:
            found.undeclared += len(primitive.triangles)
            continue
        if len(primitive.uvs) <= UV_SET:
            found.without_uvs += len(primitive.triangles)
            continue
        uvs = primitive.uvs[UV_SET]
        roles = primitive.uvs[palette.uv_set] if palette is not None and len(primitive.uvs) > palette.uv_set else None
        for triangle in primitive.triangles:
            positions = [primitive.positions[index] for index in triangle]
            center = (
                sum(position[0] for position in positions) / 3,
                sum(position[1] for position in positions) / 3,
                sum(position[2] for position in positions) / 3,
            )
            area = length(cross(subtract(positions[1], positions[0]), subtract(positions[2], positions[0]))) / 2
            swatch = swatch_of(palette, roles, triangle) if palette is not None and roles is not None else None
            role = swatch[0] if swatch is not None else None
            found.area += area
            found.role_area[role] += area
            if any(
                not (-UV_TOLERANCE <= uvs[index][axis] <= 1 + UV_TOLERANCE) for index in triangle for axis in (0, 1)
            ):
                found.outside.append(center)
                continue
            first, second, third = ((uvs[index][0] * width, uvs[index][1] * height) for index in triangle)
            corners: Corners = (first, second, third)
            if max(math.dist(corner, first) for corner in corners) <= POINT_TEXELS:
                found.points.append(first)
                continue
            found.painted_area += area
            found.role_painted[role] += area
            found.painted.append(Painted(corners=corners, center=center, role=role))
            found.texels += (
                abs((second[0] - first[0]) * (third[1] - first[1]) - (third[0] - first[0]) * (second[1] - first[1])) / 2
            )
            measured: list[float] = []
            for edge in range(3):
                texels = math.dist(corners[edge], corners[edge - 1])
                meters = length(subtract(positions[edge], positions[edge - 1]))
                if texels >= MEASURED_TEXELS and meters > 0:
                    measured.append(texels / meters)
            found.densities += measured
            if len(measured) > 1 and max(measured) > STRETCHED * min(measured):
                found.stretched.append(center)
    return found


def overlapping(triangles: list[tuple[str, Painted]], width: int, height: int) -> dict[str, list[Vector]]:
    """By part, where its triangles share texels with another triangle's."""
    cell = max(width, height) / OVERLAP_CELLS
    cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, (_, painted) in enumerate(triangles):
        xs = [corner[0] for corner in painted.corners]
        ys = [corner[1] for corner in painted.corners]
        for x in range(int(min(xs) // cell), int(max(xs) // cell) + 1):
            for y in range(int(min(ys) // cell), int(max(ys) // cell) + 1):
                cells[x, y].append(index)
    tested: set[tuple[int, int]] = set()
    shared: set[int] = set()
    for members in cells.values():
        for position, first in enumerate(members):
            for second in members[position + 1 :]:
                if (first, second) in tested:
                    continue
                tested.add((first, second))
                if _overlap(triangles[first][1].corners, triangles[second][1].corners):
                    shared.update((first, second))
    found: dict[str, list[Vector]] = defaultdict(list)
    for index in sorted(shared):
        name, painted = triangles[index]
        found[name].append(painted.center)
    return found


def _overlap(first: Corners, second: Corners) -> bool:
    """Whether two triangles reach into each other, with no edge of either between them."""
    for triangle in (first, second):
        for edge in range(3):
            (x0, y0), (x1, y1) = triangle[edge - 1], triangle[edge]
            size = math.hypot(x1 - x0, y1 - y0)
            if size == 0:
                continue
            across, down = (y1 - y0) / size, (x0 - x1) / size
            ours = [x * across + y * down for x, y in first]
            theirs = [x * across + y * down for x, y in second]
            if min(max(ours), max(theirs)) - max(min(ours), min(theirs)) <= OVERLAP_TEXELS:
                return False
    return True
