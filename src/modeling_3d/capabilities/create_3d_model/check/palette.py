"""A model's palette as the color checks read it: the image its faces take their colors from as a grid of swatches,
what its material declares of it, the swatch each triangle lands on, and the emission palette beside it."""

from collections import defaultdict
import contextlib
from dataclasses import dataclass, field
import json
from typing import Any

from modeling_3d.capabilities.create_3d_model.check.glb import Node, Scene, Vector, cross, length, subtract
from modeling_3d.capabilities.create_3d_model.check.png import Png, Rgba, png_size, read_png

# The most pixels read of an image in plain Python, and the most swatches read as a palette. A palette is small, and
# an image far larger is a texture painted across the model.
MOST_PIXELS = 1 << 18
MOST_SWATCHES = 1 << 12
# How far a UV may sit from its swatch's center, in the image's pixels, before it is off center, and how far outside
# the image, for the float error an export leaves.
CENTER_TEXELS = 0.25
UV_TOLERANCE = 1e-6


@dataclass
class Palette:
    """The base color image most of the model's triangles are drawn with, read as a grid of swatches."""

    image: int
    # The materials drawn with it, the texture the first reads it through, and the set of texture coordinates it uses.
    materials: list[int]
    texture: int
    uv_set: int
    width: int = 0
    height: int = 0
    columns: int = 0
    rows: int = 0
    # A name for each column and row: as declared, or by its place where nothing declares them or they do not fit.
    roles: list[str] = field(default_factory=list)
    schemes: list[str] = field(default_factory=list)
    declared: bool = False
    problems: list[str] = field(default_factory=list)
    png: Png | None = None
    # Why the image could not be read, when it could not.
    unreadable: str | None = None

    def swatch(self, column: int, row: int) -> Rgba:
        """The color at the center of a swatch."""
        assert self.png is not None
        return centered(self.png, column, row, self.columns, self.rows)

    def uniform(self, column: int, row: int) -> bool:
        """Whether a swatch is one color all across."""
        assert self.png is not None
        center = self.swatch(column, row)
        across, down = self.width // self.columns, self.height // self.rows
        return all(
            self.png.rows[y][x] == center
            for y in range(row * down, (row + 1) * down)
            for x in range(column * across, (column + 1) * across)
        )

    def cell(self, uv: tuple[float, float]) -> tuple[int, int, float] | None:
        """The swatch a UV lands in, by column and row, and how far it is from the swatch's center in pixels; None
        outside the image."""
        u, v = uv
        if not (-UV_TOLERANCE <= u <= 1 + UV_TOLERANCE and -UV_TOLERANCE <= v <= 1 + UV_TOLERANCE):
            return None
        across, down = self.width / self.columns, self.height / self.rows
        x, y = u * self.width, v * self.height
        column = min(max(int(x // across), 0), self.columns - 1)
        row = min(max(int(y // down), 0), self.rows - 1)
        return column, row, max(abs(x - (column + 0.5) * across), abs(y - (row + 0.5) * down))


@dataclass
class Landed:
    """Where one part's triangles drawn with the palette land on it."""

    # By swatch, as a column and a row, its triangles and their area.
    triangles: dict[tuple[int, int], int] = field(default_factory=lambda: defaultdict(int))
    area: dict[tuple[int, int], float] = field(default_factory=lambda: defaultdict(float))
    # The centers of the triangles whose corners land in more than one swatch, off their swatch's center, or outside
    # the image.
    across: list[Vector] = field(default_factory=list)
    off_center: list[Vector] = field(default_factory=list)
    outside: list[Vector] = field(default_factory=list)
    without_uvs: int = 0


@dataclass
class Emission:
    """The emission palette of the palette's material, and how strongly it glows."""

    image: int | None
    factor: tuple[float, float, float]
    strength: float
    png: Png | None = None
    unreadable: str | None = None


def read_palette(scene: Scene) -> Palette | None:
    """The model's palette; None when no triangle is drawn with a base color texture."""
    triangles: dict[int, int] = defaultdict(int)
    for node in scene.meshes:
        for primitive in node.primitives:
            found = base_color(scene, primitive.material)
            if found is not None:
                triangles[found[0]] += len(primitive.triangles)
    if not triangles:
        return None
    image = max(triangles, key=lambda index: triangles[index])
    materials = [
        index
        for index in range(len(scene.document.get("materials", [])))
        if (base_color(scene, index) or (None,))[0] == image
    ]
    _, texture, uv_set = base_color(scene, materials[0]) or (image, 0, 0)
    palette = Palette(image=image, materials=materials, texture=texture, uv_set=uv_set)
    extras = [scene.document["materials"][index].get("extras") for index in materials]
    declarations = [each["palette"] for each in extras if isinstance(each, dict) and "palette" in each]
    roles, schemes = _declared(declarations[0], palette.problems) if declarations else (None, None)
    palette.declared = bool(declarations)
    try:
        data = scene.image(image)
        palette.width, palette.height = png_size(data)
    except ValueError as error:
        palette.unreadable = str(error)
        return palette
    if not palette.width or not palette.height:
        palette.unreadable = "it has no pixels"
        return palette
    palette.columns, palette.roles = _fitted(roles, palette.width, "role", "column", "across", palette.problems)
    palette.rows, palette.schemes = _fitted(schemes, palette.height, "scheme", "row", "down", palette.problems)
    if palette.columns * palette.rows > MOST_SWATCHES:
        palette.unreadable = (
            f"as {palette.columns} by {palette.rows} swatches it has far more than a palette, so it is likely a "
            "texture painted across the model instead"
        )
        palette.columns = palette.rows = 0
        return palette
    try:
        palette.png = read_png(data, MOST_PIXELS)
    except ValueError as error:
        palette.unreadable = str(error)
    return palette


def base_color(scene: Scene, material: int | None) -> tuple[int, int, int] | None:
    """The image a material's base color texture shows, that texture, and the set of texture coordinates it uses."""
    materials = scene.document.get("materials", [])
    if material is None or not 0 <= material < len(materials):
        return None
    info = materials[material].get("pbrMetallicRoughness", {}).get("baseColorTexture")
    if not isinstance(info, dict):
        return None
    image = _source(scene, info.get("index"))
    return None if image is None else (image, info["index"], info.get("texCoord", 0))


def landed(palette: Palette, node: Node) -> Landed:
    """Where the node's triangles drawn with the palette land on it."""
    found = Landed()
    for primitive in node.primitives:
        if primitive.material not in palette.materials:
            continue
        if len(primitive.uvs) <= palette.uv_set:
            found.without_uvs += len(primitive.triangles)
            continue
        uvs = primitive.uvs[palette.uv_set]
        for triangle in primitive.triangles:
            corners = [primitive.positions[index] for index in triangle]
            center = (
                sum(corner[0] for corner in corners) / 3,
                sum(corner[1] for corner in corners) / 3,
                sum(corner[2] for corner in corners) / 3,
            )
            cells = [palette.cell(uvs[index]) for index in triangle]
            if any(cell is None for cell in cells):
                found.outside.append(center)
                continue
            swatches = {(cell[0], cell[1]) for cell in cells if cell is not None}
            if len(swatches) > 1:
                found.across.append(center)
                continue
            if max(cell[2] for cell in cells if cell is not None) > CENTER_TEXELS:
                found.off_center.append(center)
            swatch = swatches.pop()
            found.triangles[swatch] += 1
            found.area[swatch] += length(cross(subtract(corners[1], corners[0]), subtract(corners[2], corners[0]))) / 2
    return found


def swatch_of(
    palette: Palette, uvs: list[tuple[float, float]], triangle: tuple[int, int, int]
) -> tuple[int, int] | None:
    """The swatch every corner of a triangle lands in, as a column and a row; None when they land in none or several."""
    if not palette.columns:
        return None
    cells = [palette.cell(uvs[index]) for index in triangle]
    swatches = {(cell[0], cell[1]) for cell in cells if cell is not None}
    return swatches.pop() if len(swatches) == 1 and None not in cells else None


def read_emission(scene: Scene, palette: Palette) -> Emission:
    """The emission palette of the palette's first material, read when it is one this reads."""
    material = scene.document["materials"][palette.materials[0]]
    factor = material.get("emissiveFactor", [0.0, 0.0, 0.0])
    strength = material.get("extensions", {}).get("KHR_materials_emissive_strength", {}).get("emissiveStrength", 1.0)
    info = material.get("emissiveTexture")
    image = _source(scene, info.get("index")) if isinstance(info, dict) else None
    emission = Emission(image=image, factor=(factor[0], factor[1], factor[2]), strength=float(strength))
    if image is not None:
        try:
            emission.png = read_png(scene.image(image), MOST_PIXELS)
        except ValueError as error:
            emission.unreadable = str(error)
    return emission


def centered(png: Png, column: int, row: int, columns: int, rows: int) -> Rgba:
    """The pixel at the center of a swatch of an image read as `columns` by `rows` of them."""
    return png.rows[int((row + 0.5) * png.height / rows)][int((column + 0.5) * png.width / columns)]


def hex_color(pixel: Rgba) -> str:
    return f"#{pixel[0]:02X}{pixel[1]:02X}{pixel[2]:02X}"


def _source(scene: Scene, texture: Any) -> int | None:
    """The image a texture shows, its WebP one where it names only that."""
    textures = scene.document.get("textures", [])
    if not isinstance(texture, int) or not 0 <= texture < len(textures):
        return None
    entry = textures[texture]
    source = entry.get("source", entry.get("extensions", {}).get("EXT_texture_webp", {}).get("source"))
    return source if isinstance(source, int) else None


def _declared(value: Any, problems: list[str]) -> tuple[list[str] | None, list[str] | None]:
    """The roles and schemes a palette declaration names, adding what is wrong with it to `problems`."""
    if isinstance(value, str):
        # Left as the text it is when it is not JSON, which is then wrong.
        with contextlib.suppress(ValueError):
            value = json.loads(value)
    if not isinstance(value, dict):
        problems.append(
            'Its palette is not declared as an object with roles and schemes, such as {"roles": ["body", "trim"], '
            '"schemes": ["default"]}.'
        )
        return None, None
    found: list[list[str] | None] = []
    for key in ("roles", "schemes"):
        names = value.get(key)
        if isinstance(names, list) and names and all(isinstance(name, str) and name for name in names):
            found.append(names)
        else:
            problems.append(f"Its palette declares no {key} as a list of names.")
            found.append(None)
    return found[0], found[1]


def _fitted(
    names: list[str] | None, pixels: int, noun: str, place: str, way: str, problems: list[str]
) -> tuple[int, list[str]]:
    """How many swatches the image has one way, and a name for each: as declared when they divide its pixels evenly,
    otherwise one for each pixel, named by its place."""
    if names is not None and pixels % len(names) == 0:
        return len(names), names
    if names is not None:
        problems.append(
            f"Its {len(names)} declared {noun}s do not divide its {pixels} pixels {way} evenly, so each pixel {way} is "
            f"read as a swatch."
        )
    return pixels, [f"{place} {index + 1}" for index in range(pixels)]
