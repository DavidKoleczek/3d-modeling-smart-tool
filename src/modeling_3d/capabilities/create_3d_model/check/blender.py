# /// script
# requires-python = "==3.13.*"
# ///
"""The checks of check_3d_model that need Blender: buried faces, sweeps of moving parts, the detail under each role,
and renders, of the model on screen, of its poses, in each of its palette's schemes, and with its detail.

check.py runs it through uv with bpy, given the path of its request, and reads what it found from the path the request
names. It imports model.glb, so it checks what was exported rather than the scene that built it.
"""

from collections.abc import Callable
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
import numpy as np

# Where the renders are seen from, in Blender's axes, where the front is -Y: in front, to one side, and above.
VIEW = (-1.0, -1.0, 0.8)
SUN_ROTATION = (math.radians(50), 0.0, math.radians(-30))
SUN_ENERGY = 3.0
WORLD_COLOR = (0.6, 0.6, 0.6, 1.0)
# What a sheet's renders are set on, as stored in the PNG.
BACKGROUND = (0.5, 0.5, 0.5)
# Pixels around the model in a render, and between the images of a sheet.
MARGIN = 2
GAP = 8
# How far off its face a ray starts, as a share of the model's size, so it never hits the face it leaves.
RAY_OFFSET = 1e-5
# How many places buried faces are named at for each object, spread as far apart as they go.
BURIED_EXAMPLES = 5
SPIN_POSES = (0.0, 120.0, 240.0)
# What the detail is shown alone on: mid gray as stored, as the light an emission shader gives off.
DETAIL_GRAY = 0.2140
# What the edges of the detail texture's islands are drawn in on it, and the points faces with no detail sit at.
ISLAND_EDGE = (1.0, 0.45, 0.0)
NO_DETAIL_POINT = (0.0, 0.75, 1.0)
# How far outside a triangle the center of a texel can be, as a share of the triangle, and still be under it.
INSIDE_TOLERANCE = 1e-6


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(request["out"])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # Without disable_bone_shape, a skinned model comes in with a sphere of 1 m to draw its bones with, which would
    # hide every face from the rays and frame the renders around itself.
    bpy.ops.import_scene.gltf(filepath=request["glb"], disable_bone_shape=True)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    camera = prepare(request) if {"on-screen", "poses", "schemes", "detail-renders"} & set(request["checks"]) else None
    steps = {
        "buried-faces": ("buried", lambda: buried(meshes, request)),
        "moving-parts": ("sweeps", lambda: sweeps(meshes, request)),
        "on-screen": ("on_screen", lambda: on_screen(meshes, request, out, camera)),
        "poses": ("poses", lambda: poses(request, out, camera)),
        "schemes": ("schemes", lambda: schemes(meshes, request, out, camera)),
        "detail-colors": ("detail_colors", lambda: detail_colors(request)),
        "detail-renders": ("detail_renders", lambda: detail_renders(meshes, request, out, camera)),
    }
    found: dict[str, Any] = {"errors": {}}
    for check in request["checks"]:
        key, step = steps[check]
        try:
            found[key] = step()
        except Exception as error:  # one check failing still leaves what the others found
            found["errors"][check] = f"{type(error).__name__}: {error}"
    Path(request["result"]).write_text(json.dumps(found), encoding="utf-8")


def to_blender(vector: list[float]) -> Vector:
    """A glTF direction or point in Blender's axes: glTF's y is up and its z the front, Blender's z up and -y front."""
    x, y, z = vector
    return Vector((x, -z, y))


def to_gltf(vector: Vector) -> list[float]:
    return [vector.x, vector.z, -vector.y]


def spread(points: list[Vector], count: int) -> list[Vector]:
    """Up to `count` of the points, each as far from those picked before it as it can be."""
    picked = points[:1]
    while points and len(picked) < count:
        farthest = max(points, key=lambda point: min((point - each).length for each in picked))
        if any((farthest - each).length == 0 for each in picked):
            break
        picked.append(farthest)
    return picked


def world_mesh(obj: Any) -> tuple[list[Vector], list[tuple[int, int, int]]]:
    """The object's triangles where they are in the scene."""
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    vertices = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    evaluated.to_mesh_clear()
    return vertices, triangles


def joined(
    parts: list[tuple[list[Vector], list[tuple[int, int, int]]]],
) -> tuple[list[Vector], list[tuple[int, int, int]]]:
    vertices: list[Vector] = []
    triangles: list[tuple[int, int, int]] = []
    for part_vertices, part_triangles in parts:
        start = len(vertices)
        vertices += part_vertices
        triangles += [(a + start, b + start, c + start) for a, b, c in part_triangles]
    return vertices, triangles


def sphere(count: int) -> list[Vector]:
    """Directions spread evenly over a sphere."""
    golden = math.pi * (3 - math.sqrt(5))
    directions = []
    for index in range(count):
        z = 1 - 2 * (index + 0.5) / count
        radius = math.sqrt(1 - z * z)
        directions.append(Vector((math.cos(golden * index) * radius, math.sin(golden * index) * radius, z)))
    return directions


def buried(meshes: list[Any], request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """For each object, its triangles no ray from outside reaches: none cast off their front escapes the model."""
    parts = {obj.name: world_mesh(obj) for obj in meshes}
    vertices, triangles = joined(list(parts.values()))
    tree = BVHTree.FromPolygons(vertices, triangles)
    size = max((max(v[axis] for v in vertices) - min(v[axis] for v in vertices) for axis in range(3)), default=0.0)
    offset = size * RAY_OFFSET
    directions = sphere(request["ray_directions"])
    found: dict[str, dict[str, Any]] = {}
    for name, (part_vertices, part_triangles) in parts.items():
        centers: list[Vector] = []
        for a, b, c in part_triangles:
            normal = (part_vertices[b] - part_vertices[a]).cross(part_vertices[c] - part_vertices[a])
            if normal.length == 0:
                continue
            normal.normalize()
            origin = (part_vertices[a] + part_vertices[b] + part_vertices[c]) / 3 + normal * offset
            # Straight out first, which most faces escape by.
            facing = sorted((d for d in directions if d.dot(normal) > 0), key=lambda d: -d.dot(normal))
            if not any(tree.ray_cast(origin, direction)[0] is None for direction in (normal, *facing)):
                centers.append(origin)
        found[name] = {
            "buried": len(centers),
            "triangles": len(part_triangles),
            "examples": [to_gltf(point) for point in spread(centers, BURIED_EXAMPLES)],
        }
    return found


def place(motion: dict[str, Any], value: float) -> Matrix:
    """How a motion moves its part from where it rests, at `value` along it, in Blender's axes."""
    axis = to_blender(motion["axis"])
    if motion["kind"] == "slide":
        return Matrix.Translation(axis * (value * motion["unit"]))
    pivot = to_blender(motion["pivot"])
    return Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(value), 4, axis) @ Matrix.Translation(-pivot)


def values(motion: dict[str, Any], count: int) -> list[float]:
    low, high = motion["range"]
    return [low + (high - low) * index / (count - 1) for index in range(count)]


def sweeps(meshes: list[Any], request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """For each part that moves, where along its range it touches another object in places it does not at rest."""
    objects = {obj.name: obj for obj in bpy.context.scene.objects}
    found: dict[str, dict[str, Any]] = {}
    for motion in request["motions"]:
        if motion["kind"] not in ("slide", "hinge", "spin") or motion["bone"]:
            continue
        obj = objects.get(motion["node"])
        if obj is None:
            found[motion["node"]] = {"missing": True}
            continue
        moving = [part for part in (obj, *obj.children_recursive) if part.type == "MESH"]
        vertices, triangles = joined([world_mesh(part) for part in moving])
        others = {other.name: BVHTree.FromPolygons(*world_mesh(other)) for other in meshes if other not in moving}
        rest = BVHTree.FromPolygons(vertices, triangles)
        touching = {name: set(rest.overlap(tree)) for name, tree in others.items()}
        hits = []
        steps = values(motion, request["sweep_steps"])
        for value in steps:
            moved = place(motion, value)
            tree = BVHTree.FromPolygons([moved @ vertex for vertex in vertices], triangles)
            touches = [name for name, other in others.items() if set(tree.overlap(other)) - touching[name]]
            if touches:
                hits.append({"value": value, "touches": touches})
        found[motion["node"]] = {"values": steps, "hits": hits}
    return found


def prepare(request: dict[str, Any]) -> Any:
    """Set the scene up to render, and return its camera."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = request["samples"]
    scene.cycles.use_denoising = True
    scene.render.film_transparent = True
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    world = bpy.data.worlds.new("Check_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = WORLD_COLOR
    scene.world = world
    sun = bpy.data.objects.new("Check_sun", bpy.data.lights.new("Check_sun", "SUN"))
    sun.data.energy = SUN_ENERGY
    sun.rotation_euler = SUN_ROTATION
    scene.collection.objects.link(sun)
    camera = bpy.data.objects.new("Check_camera", bpy.data.cameras.new("Check_camera"))
    camera.data.type = "ORTHO"
    scene.collection.objects.link(camera)
    scene.camera = camera
    return camera


def corners(objects: list[Any]) -> list[Vector]:
    return [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box if not obj.hide_render]


def aim(camera: Any, points: list[Vector], pixels_per_meter: float | None = None, size: int | None = None) -> None:
    """Look at the points from VIEW, rendering them at `pixels_per_meter`, or to fit `size` pixels."""
    direction = Vector(VIEW).normalized()
    rotation = direction.to_track_quat("Z", "Y")
    right, up = rotation @ Vector((1.0, 0.0, 0.0)), rotation @ Vector((0.0, 1.0, 0.0))
    across = [point.dot(right) for point in points]
    upward = [point.dot(up) for point in points]
    depth = [point.dot(direction) for point in points]
    width, height = max(across) - min(across), max(upward) - min(upward)
    reach = max(width, height, max(depth) - min(depth), 1e-6)
    if pixels_per_meter is None:
        assert size is not None
        pixels_per_meter = (size - 2 * MARGIN) / max(width, height, 1e-6)
    columns = math.ceil(width * pixels_per_meter) + 2 * MARGIN
    rows = math.ceil(height * pixels_per_meter) + 2 * MARGIN
    middle = right * (max(across) + min(across)) / 2 + up * (max(upward) + min(upward)) / 2
    camera.location = middle + direction * (max(depth) + reach)
    camera.rotation_euler = rotation.to_euler()
    camera.data.clip_start = reach * 1e-3
    camera.data.clip_end = reach * 4
    # An orthographic camera's scale spans the image's longer side.
    camera.data.ortho_scale = max(columns, rows) / pixels_per_meter
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = columns, rows


def render(path: Path) -> np.ndarray:
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return flattened(pixels(path))


def pixels(path: Path) -> np.ndarray:
    """The image's pixels as stored, top row first."""
    image = bpy.data.images.load(str(path))
    width, height = image.size
    stored = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(stored)
    bpy.data.images.remove(image)
    # Blender keeps an image's rows bottom up.
    return stored.reshape(height, width, 4)[::-1]


def save(image: np.ndarray, path: Path) -> None:
    rows, columns = image.shape[:2]
    saved = bpy.data.images.new(path.stem, columns, rows, alpha=True)
    saved.pixels.foreach_set(np.ascontiguousarray(image[::-1], dtype=np.float32).ravel())
    saved.filepath_raw = str(path)
    saved.file_format = "PNG"
    saved.save()
    bpy.data.images.remove(saved)


def flattened(image: np.ndarray) -> np.ndarray:
    """The image over the background."""
    alpha = image[..., 3:4]
    color = image[..., :3] * alpha + np.array(BACKGROUND, dtype=np.float32) * (1 - alpha)
    return np.concatenate([color, np.ones_like(alpha)], axis=2)


def scaled(image: np.ndarray, rows: int) -> np.ndarray:
    """The image at `rows` tall, each pixel taken from the nearest."""
    columns = max(1, round(image.shape[1] * rows / image.shape[0]))
    picked_rows = (np.arange(rows) * image.shape[0] / rows).astype(int)
    picked_columns = (np.arange(columns) * image.shape[1] / columns).astype(int)
    return image[picked_rows][:, picked_columns]


def side_by_side(images: list[np.ndarray]) -> np.ndarray:
    rows = max(image.shape[0] for image in images)
    columns = sum(image.shape[1] for image in images) + GAP * (len(images) - 1)
    sheet = np.ones((rows, columns, 4), dtype=np.float32)
    sheet[..., :3] = BACKGROUND
    left = 0
    for image in images:
        top = (rows - image.shape[0]) // 2
        sheet[top : top + image.shape[0], left : left + image.shape[1]] = image
        left += image.shape[1] + GAP
    return sheet


def on_screen(meshes: list[Any], request: dict[str, Any], out: Path, camera: Any) -> list[str]:
    """Render the model at each size on screen, and a sheet of it scaled up beside the references."""
    references = [flattened(pixels(Path(path))) for path in request["references"]]
    points = corners(meshes)
    files: list[str] = []
    for size in sorted(set(request["screen_size"])):
        aim(camera, points, pixels_per_meter=size / request["longest"])
        name = f"on-screen-{size}px.png"
        shot = render(out / name)
        # Whole pixels, so each pixel of the render shows as a square.
        factor = max(1, request["sheet_height"] // shot.shape[0])
        enlarged = np.repeat(np.repeat(shot, factor, axis=0), factor, axis=1)
        rows = max(request["sheet_height"], enlarged.shape[0])
        sheet = f"on-screen-{size}px-sheet.png"
        save(side_by_side([*(scaled(reference, rows) for reference in references), enlarged]), out / sheet)
        files += [name, sheet]
    return files


def schemes(meshes: list[Any], request: dict[str, Any], out: Path, camera: Any) -> list[str]:
    """Render the model in each of its palette's schemes, side by side at each size on screen, lit flat so each face
    shows its swatch's color as the palette stores it."""
    width, height = request["palette"]["size"]
    rows = request["palette"]["rows"]
    lit = flat_lit()
    # The palette is every base color image its size. Each scheme shows by repeating its row down the whole image,
    # so whichever row the UVs point at shows that scheme.
    palettes = {
        texture.image
        for texture, _, _ in lit.values()
        if texture.image is not None and tuple(texture.image.size) == (width, height)
    }
    stored = {image: image_pixels(image) for image in palettes}
    # Light that no surface scatters has no noise to remove, and denoising would shift the colors a step.
    bpy.context.scene.cycles.use_denoising = False
    points = corners(meshes)
    sizes = sorted(set(request["screen_size"])) if request["screen_size"] else [None]
    files: list[str] = []
    for size in sizes:
        shots = []
        for row in range(rows):
            for image, pixels_of in stored.items():
                band = pixels_of[row * height // rows : (row + 1) * height // rows]
                set_image_pixels(image, np.tile(band, (rows, 1, 1)))
            if size is None:
                aim(camera, points, size=request["pose_size"])
            else:
                aim(camera, points, pixels_per_meter=size / request["longest"])
            path = out / f"scheme-frame-{row}.png"
            shot = render(path)
            path.unlink()
            # Whole pixels, so each pixel of the render shows as a square.
            factor = max(1, request["sheet_height"] // shot.shape[0])
            shots.append(np.repeat(np.repeat(shot, factor, axis=0), factor, axis=1))
        name = "schemes.png" if size is None else f"schemes-{size}px.png"
        save(side_by_side(shots), out / name)
        files.append(name)
    bpy.context.scene.cycles.use_denoising = True
    for image, pixels_of in stored.items():
        set_image_pixels(image, pixels_of)
    for material, (_, emission, surface) in lit.items():
        tree = material.node_tree
        output = next(node for node in tree.nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output)
        tree.nodes.remove(emission)
        if surface is not None:
            tree.links.new(surface, output.inputs["Surface"])
    return files


def flat_lit() -> dict[Any, tuple[Any, Any, Any]]:
    """Draw each material as its base color texture alone, through an emission shader no light changes. By material,
    its texture node, the emission node, and the socket the surface came from, to put back."""
    found: dict[Any, tuple[Any, Any, Any]] = {}
    for material in bpy.data.materials:
        tree = material.node_tree
        if tree is None:
            continue
        output = next((node for node in tree.nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output), None)
        principled = next((node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
        texture = upstream_image(principled.inputs["Base Color"]) if principled is not None else None
        if output is None or texture is None:
            continue
        links = output.inputs["Surface"].links
        surface = links[0].from_socket if links else None
        emission = tree.nodes.new("ShaderNodeEmission")
        tree.links.new(texture.outputs["Color"], emission.inputs["Color"])
        tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
        found[material] = (texture, emission, surface)
    return found


def upstream_image(socket: Any) -> Any:
    """The first image texture node that feeds a socket, through whatever nodes sit between."""
    pending = [link.from_node for link in socket.links]
    seen = set()
    while pending:
        node = pending.pop(0)
        if node.name in seen:
            continue
        seen.add(node.name)
        if node.type == "TEX_IMAGE":
            return node
        pending += [link.from_node for put in node.inputs for link in put.links]
    return None


def image_pixels(image: Any) -> np.ndarray:
    """An image's pixels as it keeps them, top row first."""
    width, height = image.size
    stored = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(stored)
    return stored.reshape(height, width, 4)[::-1].copy()


def set_image_pixels(image: Any, pixels_of: np.ndarray) -> None:
    image.pixels.foreach_set(np.ascontiguousarray(pixels_of[::-1], dtype=np.float32).ravel())
    image.update()


def detail_colors(request: dict[str, Any]) -> dict[str, Any]:
    """Count each 8 bit value of the detail under the triangles that take it, for each role, and under the points the
    triangles with none sit at."""
    detail = request["detail"]
    values = np.rint(gray(Path(detail["path"])) * 255).clip(0, 255).astype(np.int64)
    height, width = values.shape
    under = np.zeros(256, dtype=np.int64)
    roles: dict[str, np.ndarray] = {}
    for corners, role in zip(detail["triangles"], detail["roles"], strict=True):
        rows, columns = covered(corners, width, height)
        counts = np.bincount(values[rows, columns], minlength=256)
        under += counts
        roles[str(role)] = roles.get(str(role), np.zeros(256, dtype=np.int64)) + counts
    neutral = np.zeros(256, dtype=np.int64)
    for x, y in detail["points"]:
        neutral[values[min(height - 1, max(0, int(y))), min(width - 1, max(0, int(x)))]] += 1
    return {
        "all": under.tolist(),
        "roles": {role: counts.tolist() for role, counts in roles.items()},
        "neutral": neutral.tolist(),
    }


def gray(path: Path) -> np.ndarray:
    """A texture's first channel as stored, top row first, from 0 to 1."""
    image = bpy.data.images.load(str(path), check_existing=True)
    image.colorspace_settings.name = "Non-Color"
    return image_pixels(image)[..., 0]


def covered(corners: list[float], width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """The rows and columns of the texels whose centers a triangle covers, given its corners in pixels from the top
    left, or of the one under its middle when it is too thin to cover any."""
    xs, ys = np.array(corners[0::2]), np.array(corners[1::2])
    left, right = max(0, math.floor(xs.min())), min(width, math.ceil(xs.max()))
    top, bottom = max(0, math.floor(ys.min())), min(height, math.ceil(ys.max()))
    columns, rows = np.meshgrid(np.arange(left, right), np.arange(top, bottom))
    x, y = columns + 0.5, rows + 0.5
    (x0, x1, x2), (y0, y1, y2) = xs, ys
    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if area:
        first = ((x1 - x) * (y2 - y) - (x2 - x) * (y1 - y)) / area
        second = ((x2 - x) * (y0 - y) - (x0 - x) * (y2 - y)) / area
        inside = (first >= -INSIDE_TOLERANCE) & (second >= -INSIDE_TOLERANCE) & (first + second <= 1 + INSIDE_TOLERANCE)
        if inside.any():
            return rows[inside], columns[inside]
    row = min(height - 1, max(0, int(ys.mean())))
    column = min(width - 1, max(0, int(xs.mean())))
    return np.array([row]), np.array([column])


def detail_renders(meshes: list[Any], request: dict[str, Any], out: Path, camera: Any) -> list[str]:
    """Render the model lit flat without its detail and with it, side by side at each size on screen, then the detail
    alone on mid gray at the largest, and the texture with the edges of its islands drawn on it."""
    detail = request["detail"]
    uv_map = next((obj.data.uv_layers[1].name for obj in meshes if len(obj.data.uv_layers) > 1), None)
    if uv_map is None:
        raise ValueError("no mesh Blender imported has a second set of texture coordinates")
    image = bpy.data.images.load(detail["path"], check_existing=True)
    image.colorspace_settings.name = "Non-Color"
    lit = detail_lit(image, detail["materials"], uv_map)
    if not lit:
        raise ValueError("no material Blender imported declares the detail")
    # Light that no surface scatters has no noise to remove, and denoising would blur the detail.
    bpy.context.scene.cycles.use_denoising = False
    points = corners(meshes)
    sizes = sorted(set(request["screen_size"])) if request["screen_size"] else [None]
    files: list[str] = []

    def shot(size: int | None, showing: str) -> np.ndarray:
        for material, nodes in lit.items():
            material.node_tree.links.new(nodes[showing], nodes["emission"].inputs["Color"])
        if size is None:
            aim(camera, points, size=request["pose_size"])
        else:
            aim(camera, points, pixels_per_meter=size / request["longest"])
        path = out / "detail-frame.png"
        taken = render(path)
        path.unlink()
        # Whole pixels, so each pixel of the render shows as a square.
        factor = max(1, request["sheet_height"] // taken.shape[0])
        return np.repeat(np.repeat(taken, factor, axis=0), factor, axis=1)

    for size in sizes:
        name = "detail.png" if size is None else f"detail-{size}px.png"
        save(side_by_side([shot(size, "colors"), shot(size, "shaded")]), out / name)
        files.append(name)
    name = "detail-alone.png" if sizes[-1] is None else f"detail-alone-{sizes[-1]}px.png"
    save(shot(sizes[-1], "alone"), out / name)
    files.append(name)
    save(islands(detail, request["sheet_height"]), out / "detail-texture.png")
    files.append("detail-texture.png")
    bpy.context.scene.cycles.use_denoising = True
    for material, nodes in lit.items():
        tree = material.node_tree
        output = next(node for node in tree.nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output)
        for node in nodes["added"]:
            tree.nodes.remove(node)
        if nodes["surface"] is not None:
            tree.links.new(nodes["surface"], output.inputs["Surface"])
    return files


def detail_lit(image: Any, names: list[str], uv_map: str) -> dict[Any, dict[str, Any]]:
    """Draw each material that declares the detail through an emission shader no light changes. By material, the
    sockets to show: its base color, that multiplied by twice the detail on the second UV set as a renderer shades it, and
    the detail alone on mid gray; then the emission node, the nodes added, and the socket the surface came from."""
    found: dict[Any, dict[str, Any]] = {}
    for material in bpy.data.materials:
        tree = material.node_tree
        if tree is None or not ("detail" in material or material.name in names):
            continue
        output = next((node for node in tree.nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output), None)
        principled = next((node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
        if output is None or principled is None:
            continue
        nodes = tree.nodes
        added = []
        base = principled.inputs["Base Color"]
        if base.links:
            color = base.links[0].from_socket
        else:
            constant = nodes.new("ShaderNodeRGB")
            constant.outputs[0].default_value = base.default_value
            added.append(constant)
            color = constant.outputs[0]
        coordinates = nodes.new("ShaderNodeUVMap")
        coordinates.uv_map = uv_map
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.interpolation = "Linear"
        texture.extension = "EXTEND"
        doubled = nodes.new("ShaderNodeVectorMath")
        doubled.operation = "SCALE"
        doubled.inputs["Scale"].default_value = 2.0
        shaded = nodes.new("ShaderNodeVectorMath")
        shaded.operation = "MULTIPLY"
        middle = nodes.new("ShaderNodeRGB")
        middle.outputs[0].default_value = (DETAIL_GRAY, DETAIL_GRAY, DETAIL_GRAY, 1.0)
        alone = nodes.new("ShaderNodeVectorMath")
        alone.operation = "MULTIPLY"
        emission = nodes.new("ShaderNodeEmission")
        added += [coordinates, texture, doubled, shaded, middle, alone, emission]
        links = tree.links
        links.new(coordinates.outputs["UV"], texture.inputs["Vector"])
        links.new(texture.outputs["Color"], doubled.inputs[0])
        links.new(color, shaded.inputs[0])
        links.new(doubled.outputs["Vector"], shaded.inputs[1])
        links.new(middle.outputs[0], alone.inputs[0])
        links.new(doubled.outputs["Vector"], alone.inputs[1])
        surface = output.inputs["Surface"].links
        found[material] = {
            "colors": color,
            "shaded": shaded.outputs["Vector"],
            "alone": alone.outputs["Vector"],
            "emission": emission,
            "added": added,
            "surface": surface[0].from_socket if surface else None,
        }
        links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return found


def islands(detail: dict[str, Any], least: int) -> np.ndarray:
    """The detail texture with the edges of its islands drawn on it, the edges only one triangle has, and the points
    faces with no detail sit at, scaled up with its pixels kept to at least `least` tall."""
    values = gray(Path(detail["path"]))
    height, width = values.shape
    sheet = np.ones((height, width, 4), dtype=np.float32)
    sheet[..., :3] = values[..., None]
    edges: dict[tuple[tuple[float, float], tuple[float, float]], int] = {}
    for corners in detail["triangles"]:
        ends = [(round(corners[2 * index], 3), round(corners[2 * index + 1], 3)) for index in range(3)]
        for index in range(3):
            first, second = ends[index - 1], ends[index]
            edge = (first, second) if first <= second else (second, first)
            edges[edge] = edges.get(edge, 0) + 1
    for (start, end), count in edges.items():
        if count > 1:
            continue
        steps = math.ceil(2 * math.dist(start, end)) + 1
        along = np.linspace(0.0, 1.0, steps)
        columns = np.clip(np.floor(start[0] + along * (end[0] - start[0])).astype(int), 0, width - 1)
        rows = np.clip(np.floor(start[1] + along * (end[1] - start[1])).astype(int), 0, height - 1)
        sheet[rows, columns, :3] = ISLAND_EDGE
    for x, y in detail["points"]:
        sheet[min(height - 1, max(0, int(y))), min(width - 1, max(0, int(x))), :3] = NO_DETAIL_POINT
    factor = max(1, math.ceil(least / height))
    return np.repeat(np.repeat(sheet, factor, axis=0), factor, axis=1)


def poses(request: dict[str, Any], out: Path, camera: Any) -> dict[str, dict[str, Any]]:
    """Render each motion through its poses, side by side: a range's ends and middle, a spin's thirds, a part shown
    and hidden, and each part of a swap group alone."""
    objects = {obj.name: obj for obj in bpy.context.scene.objects}
    meshes = [obj for obj in objects.values() if obj.type == "MESH"]
    found: dict[str, dict[str, Any]] = {}
    groups: dict[str, list[Any]] = {}
    for motion in request["motions"]:
        obj = objects.get(motion["node"])
        if obj is None or motion["bone"]:
            continue
        kind = motion["kind"]
        if kind == "swap":
            groups.setdefault(motion["group"], []).append(obj)
            continue
        rest = obj.matrix_world.copy()
        if kind == "hide":
            frames = [showing([obj], True), showing([obj], False)]
            shows = "shown, then hidden"
        else:
            steps = list(SPIN_POSES) if kind == "spin" else values(motion, 3)
            frames = [moving(obj, place(motion, value) @ rest) for value in steps]
            unit = "degrees" if kind != "slide" else "m"
            shows = f"at {', '.join(f'{value:g}' for value in steps)} {unit}"
        found[motion["node"]] = {"file": posed(camera, meshes, frames, out, motion["node"], request), "shows": shows}
        move(obj, rest)
        show([obj], True)
    for group, members in groups.items():
        frames = [alone(members, member) for member in members]
        found[f"Swap group {group}"] = {
            "file": posed(camera, meshes, frames, out, f"group-{group}", request),
            "shows": f"each of {', '.join(member.name for member in members)} alone",
        }
        show(members, True)
    return found


def move(obj: Any, matrix: Matrix) -> None:
    obj.matrix_world = matrix
    bpy.context.view_layer.update()


def show(objects: list[Any], shown: bool) -> None:
    for obj in objects:
        for part in (obj, *obj.children_recursive):
            part.hide_render = not shown


def moving(obj: Any, matrix: Matrix) -> Callable[[], None]:
    return lambda: move(obj, matrix)


def showing(objects: list[Any], shown: bool) -> Callable[[], None]:
    return lambda: show(objects, shown)


def alone(members: list[Any], member: Any) -> Callable[[], None]:
    def frame() -> None:
        show(members, False)
        show([member], True)

    return frame


def posed(
    camera: Any, meshes: list[Any], frames: list[Callable[[], None]], out: Path, name: str, request: dict[str, Any]
) -> str:
    """Render each frame with one framing that holds them all, side by side in one image."""
    points: list[Vector] = []
    for frame in frames:
        frame()
        points += corners(meshes)
    aim(camera, points, size=request["pose_size"])
    shots = []
    for index, frame in enumerate(frames):
        frame()
        path = out / f"pose-frame-{index}.png"
        shots.append(render(path))
        path.unlink()
    file = "pose-" + re.sub(r"[^A-Za-z0-9._-]", "_", name) + ".png"
    save(side_by_side(shots), out / file)
    return file


if __name__ == "__main__":
    main()
