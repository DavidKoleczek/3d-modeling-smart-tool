"""Check a model's model.glb: what it measures against its budgets and the workflow, for whoever reads it to judge."""

import asyncio
from collections import defaultdict
from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import shutil
import statistics
import subprocess
import sys
from typing import Any

import yaml

from modeling_3d.capabilities.create_3d_model.budgets import require_budgets, resolved
from modeling_3d.capabilities.create_3d_model.check.detail import (
    Detail,
    Painted,
    Unwrapped,
    overlapping,
    read_detail,
    unwrapped,
)
from modeling_3d.capabilities.create_3d_model.check.glb import (
    IDENTITY,
    Node,
    Scene,
    Vector,
    cross,
    dot,
    length,
    normalized,
    read_scene,
    rotate,
    subtract,
    translation,
)
from modeling_3d.capabilities.create_3d_model.check.palette import (
    CENTER_TEXELS,
    Palette,
    centered,
    hex_color,
    landed,
    read_emission,
    read_palette,
)
from modeling_3d.capabilities.create_3d_model.check.png import Rgba
from modeling_3d.capabilities.create_3d_model.constants import AGENT_SKILL, AGENT_SKILL_DESCRIPTION
from modeling_3d.capabilities.create_3d_model.prompting import template
from modeling_3d.capabilities.create_3d_model.record import (
    DEFAULT_DIRECTORY,
    DETAIL,
    GLB,
    REPORT,
    load_record,
    missing_model,
    model_names,
    read_atomically,
    write_atomically,
)
from modeling_3d.core.skill import skill
from modeling_3d.intelligence.interface import state_root
from modeling_3d.schemas import (
    BPY_REQUIREMENT,
    CHECK_GROUPS,
    CHECK_NAMES,
    NOT_GIVEN,
    CheckName,
    CheckResult,
    ModelCheck,
    Modeling3dError,
    NotGiven,
)

# region: Blender
HERE = Path(__file__).parent
CHECKS = REPORT.parent
BLENDER_SCRIPT = HERE / "blender.py"
# What runs the checks that need Blender, given the path of their request. Tests swap it for one that fakes Blender.
BLENDER_COMMAND = ["uv", "run", "--quiet", "--with", BPY_REQUIREMENT, "--script", str(BLENDER_SCRIPT)]
# The first run downloads bpy, which can take minutes.
BLENDER_TIMEOUT_SECONDS = 1800
BLENDER_REQUEST = CHECKS / "blender-request.json"
BLENDER_RESULT = CHECKS / "blender-result.json"
# How much of what Blender printed a failure keeps.
BLENDER_OUTPUT_LINES = 15
# endregion

# region: Measuring
RAY_DIRECTIONS = 64
SWEEP_STEPS = 9
# Vertices are one when their positions and normals match to this many decimals, which tells a smooth edge.
WELD_DIGITS = 5
# Faces closer to flat than this meet on a plane, not a curve.
FLAT_RADIANS = 1e-4
MOST_INFLUENCES = 4
# endregion

# region: Renders
# The height the renders and references of an on-screen sheet are shown at, the size of each pose, and how many
# references a sheet holds.
SHEET_HEIGHT = 480
POSE_SIZE = 320
SHEET_REFERENCES = 3
RENDER_SAMPLES = 32
# The image types Blender loads, for the references a sheet shows.
SHEET_IMAGES = (".png", ".jpg", ".jpeg", ".webp")
# endregion

# region: Motions and names
MOTION_KINDS = ("slide", "hinge", "spin", "swap", "hide")
# The motions a sweep moves through, and those with a range.
SWEPT = ("slide", "hinge", "spin")
RANGED = ("slide", "hinge")
DEFAULT_BONE = re.compile(r"^Bone(\.\d+)?$")
DEFAULT_EMPTY = re.compile(r"^Empty(\.\d+)?$")
# endregion

# region: Palettes
NO_PALETTE = "No triangle is drawn with a base color texture, so there is no palette."
# How a sampler's filters and wrapping read in the report, by their glTF codes.
FILTERS = {
    9728: "taking the nearest pixel",
    9729: "blending the nearest pixels",
    9984: "taking the nearest pixel of the nearest mipmap",
    9985: "blending pixels of the nearest mipmap",
    9986: "taking the nearest pixel of two mipmaps, blended",
    9987: "blending pixels of two mipmaps",
}
UNMIPMAPPED = (9728, 9729)
REPEAT = 10497
WRAPS = {33071: "clamped", 33648: "mirrored", REPEAT: "repeated"}
# endregion

# region: Detail
NO_DETAIL = "No material declares a detail texture."
COLOR_TYPES = {0: "grayscale", 2: "RGB", 3: "indexed color", 4: "grayscale with alpha", 6: "RGBA"}
GRAYSCALE, INDEXED = 0, 3
# The chunks that tell a loader how to turn a PNG's values into colors, which would change the amounts a detail holds.
COLOR_SPACE_CHUNKS = ("sRGB", "gAMA", "iCCP", "cHRM", "cICP")
# How much sooner than model.glb a texture can be written by the same build.
STALE_SECONDS = 600
# The two 8 bit values either side of mid gray, which a texture stores neutral as.
MID_GRAY = (127, 128)
# How far past full brightness a channel must be pushed to clip, beyond what mid gray stored in 8 bits brightens it.
CLIP_MARGIN = 1.5 / 255
# endregion

# region: The check skill a model's agent gets
# What it runs: this install's Python, since `modeling-3d` may not be on the agent's PATH.
CHECK_COMMAND = [sys.executable, "-m", "modeling_3d.cli", "check-3d-model"]
SKILL_HASH_LENGTH = 16
# endregion


@dataclass
class _Model:
    """The model as the checks measure it."""

    target: Path
    scene: Scene
    max_triangles: int | None
    max_draw_calls: int | None
    screen_size: tuple[int, int] | None
    low: Vector
    high: Vector
    references: list[Path]

    @property
    def longest(self) -> float:
        return max(high - low for low, high in zip(self.low, self.high, strict=True))


@dataclass
class _Measured:
    """What the library measured, and what it asks Blender to."""

    model: _Model
    sha256: str
    names: list[CheckName]
    results: dict[CheckName, CheckResult]
    motions: list[dict[str, Any]] = field(default_factory=list)
    palette: Palette | None = None
    detail: Detail | None = None
    unwraps: list[tuple[Node, Unwrapped]] = field(default_factory=list)
    blender: list[CheckName] = field(default_factory=list)


def check_3d_model(
    name: str,
    directory: Path | None = None,
    checks: list[str] | None = None,
    max_triangles: int | NotGiven | None = NOT_GIVEN,
    max_draw_calls: int | NotGiven | None = NOT_GIVEN,
    screen_size: tuple[int, int] | NotGiven | None = NOT_GIVEN,
) -> ModelCheck:
    """Measure the model's model.glb, write the report into its checks/, and return it."""
    measured = _measure(name, directory, checks, max_triangles, max_draw_calls, screen_size)
    found = _blender(measured) if measured.blender else {}
    return _report(measured, found)


async def check_model(
    name: str,
    directory: Path | None,
    max_triangles: int | None,
    max_draw_calls: int | None,
    screen_size: tuple[int, int] | None,
) -> ModelCheck:
    """Every check of the model, for a run, which can stop it partway and Blender with it."""
    measured = await asyncio.to_thread(_measure, name, directory, None, max_triangles, max_draw_calls, screen_size)
    found = await _blender_async(measured) if measured.blender else {}
    return await asyncio.to_thread(_report, measured, found)


def covers(target: Path) -> bool:
    """Whether the model's latest report is of its model.glb as it is now."""
    try:
        report = ModelCheck.model_validate_json(read_atomically(target / REPORT))
        return report.glb_sha256 == hashlib.sha256((target / GLB).read_bytes()).hexdigest()
    except (OSError, ValueError):
        return False


def agent_skills() -> Path:
    """A directory of skills for a model's agent, holding the check's, with the command that runs it from here.

    Named by its content, so a written skill never changes and runs at once can share it.
    """
    command = " ".join(f'"{part}"' if " " in part or "\\" in part else part for part in CHECK_COMMAND)
    frontmatter = yaml.safe_dump(
        {"name": AGENT_SKILL, "description": AGENT_SKILL_DESCRIPTION}, width=1000, sort_keys=False
    )
    body = template("check_skill.md").format(command=command, skill=skill(AGENT_SKILL))
    text = f"---\n{frontmatter}---\n\n{body}"
    root = state_root() / "skills" / hashlib.sha256(text.encode("utf-8")).hexdigest()[:SKILL_HASH_LENGTH]
    if (root / AGENT_SKILL / "SKILL.md").is_file():
        return root
    # Written aside and renamed, so a run never finds half a skill.
    partial = root.with_name(f"{root.name}.{secrets.token_hex(3)}.tmp")
    (partial / AGENT_SKILL).mkdir(parents=True)
    (partial / AGENT_SKILL / "SKILL.md").write_text(text, encoding="utf-8")
    try:
        partial.rename(root)
    except OSError:
        # Another run wrote the same skill first.
        shutil.rmtree(partial, ignore_errors=True)
        if not (root / AGENT_SKILL / "SKILL.md").is_file():
            raise
    return root


def describe(report: ModelCheck) -> str:
    """The report as text for an agent to read."""
    x, y, z = report.dimensions
    lines = [
        f"The check of {GLB} is kept in {report.directory / REPORT}.",
        (
            f"It is {x:.3f} by {y:.3f} by {z:.3f} m along glTF's x, y, and z, from {_point(report.bounds[0])} to "
            f"{_point(report.bounds[1])}, with {_count(report.triangles, 'triangle')} in "
            f"{_count(report.mesh_objects, 'mesh object')} and {_count(report.materials, 'material')}."
        ),
        "",
    ]
    for result in report.checks:
        lines.append(f"- {result.name}: {result.summary}")
        lines += [f"  - {line}" for line in result.lines]
        lines += [f"  - {report.directory / path}" for path in result.files]
    return "\n".join(lines)


def _measure(
    name: str,
    directory: Path | None,
    checks: list[str] | None,
    max_triangles: int | NotGiven | None,
    max_draw_calls: int | NotGiven | None,
    screen_size: tuple[int, int] | NotGiven | None,
) -> _Measured:
    require_budgets(max_triangles, max_draw_calls, screen_size)
    names = _selected(checks)
    root = (directory or DEFAULT_DIRECTORY).resolve()
    # Compared against the names on disk, since Windows and macOS find `Bear` when only `bear` exists.
    if name not in model_names(root):
        raise missing_model(root, name)
    target = root / name
    record = load_record(target)
    last = record.runs[-1] if record.runs else None
    path = target / GLB
    if not path.is_file():
        raise Modeling3dError(
            f"Model {name} has no {GLB} yet, so there is nothing to check. Build it with its model.py first.",
            "not-built",
            name,
        )
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    scene = read_scene(path)
    points = [point for node in scene.meshes for primitive in node.primitives for point in primitive.positions]
    low = tuple(min((point[axis] for point in points), default=0.0) for axis in range(3))
    high = tuple(max((point[axis] for point in points), default=0.0) for axis in range(3))
    references = list(
        dict.fromkeys(
            target / reference
            for run in record.runs
            for reference in run.references
            if Path(reference).suffix.lower() in SHEET_IMAGES and (target / reference).is_file()
        )
    )
    model = _Model(
        target=target,
        scene=scene,
        max_triangles=resolved(max_triangles, last.max_triangles if last else None),
        max_draw_calls=resolved(max_draw_calls, last.max_draw_calls if last else None),
        screen_size=resolved(screen_size, last.screen_size if last else None),
        low=(low[0], low[1], low[2]),
        high=(high[0], high[1], high[2]),
        references=references[:SHEET_REFERENCES],
    )
    measured = _Measured(model=model, sha256=sha256, names=names, results={})
    measures: dict[CheckName, Callable[[_Model], CheckResult]] = {
        "triangles": _triangles,
        "sub-pixel": _sub_pixel,
        "round-parts": _round_parts,
        "draw-calls": _draw_calls,
        "static-parts": _static_parts,
        "skeleton": _skeleton,
        "markers": _markers,
    }
    for check in names:
        if check in measures:
            measured.results[check] = measures[check](model)
    declared = _declared(scene)
    if "moving-parts" in names:
        measured.results["moving-parts"] = _moving_parts(model, declared)
    measured.motions = [_swept(scene, node, motion) for node, motion in declared if not _problems(motion)]
    # Blender sweeps and poses the parts that are objects; one a bone moves is skinned into a mesh with others.
    objects = [motion for motion in measured.motions if not motion["bone"]]
    blender: list[CheckName] = []
    if "buried-faces" in names:
        if scene.meshes:
            blender.append("buried-faces")
        else:
            measured.results["buried-faces"] = _skipped("buried-faces", "The model has no mesh.")
    if "moving-parts" in names and any(motion["kind"] in SWEPT for motion in objects):
        blender.append("moving-parts")
    if "on-screen" in names:
        reason = _no_size(model, "smallest and largest")
        if reason is None:
            blender.append("on-screen")
        else:
            measured.results["on-screen"] = _skipped("on-screen", reason)
    if "poses" in names:
        if objects:
            blender.append("poses")
        elif measured.motions:
            measured.results["poses"] = _skipped(
                "poses", "Each motion is declared on a bone, which this check does not pose."
            )
        else:
            measured.results["poses"] = _skipped("poses", "Nothing declares a motion that is well formed.")
    if set(CHECK_GROUPS["color"] + CHECK_GROUPS["detail"]) & set(names):
        # The detail checks give each role's share of it, and its colors.
        measured.palette = read_palette(scene)
    if set(CHECK_GROUPS["color"]) & set(names):
        palette = measured.palette
        if "palette" in names:
            measured.results["palette"] = _palette(model, palette)
        if "face-roles" in names:
            measured.results["face-roles"] = _face_roles(model, palette)
        if "emission" in names:
            measured.results["emission"] = _emission(model, palette)
        if "schemes" in names:
            if palette is None:
                measured.results["schemes"] = _skipped("schemes", NO_PALETTE)
            elif not palette.columns:
                measured.results["schemes"] = _skipped("schemes", _unread(palette))
            else:
                # Last, since it changes the materials Blender renders with.
                blender.append("schemes")
    if set(CHECK_GROUPS["detail"]) & set(names):
        detail = measured.detail = read_detail(scene, path)
        if detail is not None and detail.header is not None:
            measured.unwraps = [(node, unwrapped(detail, node, measured.palette)) for node in scene.meshes]
        if "detail-texture" in names:
            measured.results["detail-texture"] = _detail_texture(model, detail)
        if "detail-uvs" in names:
            measured.results["detail-uvs"] = _detail_uvs(model, measured)
        for check in ("detail-colors", "detail-renders"):
            if check not in names:
                continue
            if detail is None:
                measured.results[check] = _skipped(check, _no_detail(model))
            elif detail.header is None:
                measured.results[check] = _skipped(check, _unread_detail(detail))
            else:
                # The renders after the schemes', since each changes the materials Blender renders with.
                blender.append(check)
    measured.blender = blender
    return measured


def _selected(checks: list[str] | None) -> list[CheckName]:
    """The checks named, with each group named as its checks, in the order the report gives them."""
    if checks is None:
        return list(CHECK_NAMES)
    wanted: set[str] = set()
    for check in checks:
        if check in CHECK_GROUPS:
            wanted.update(CHECK_GROUPS[check])
        elif check in CHECK_NAMES:
            wanted.add(check)
        else:
            raise Modeling3dError(
                f"{check!r} is not a check. The checks are {', '.join(CHECK_NAMES)}, and the groups "
                f"{_listed(list(CHECK_GROUPS))} run theirs. Leave them out to run every check.",
                "no-such-check",
            )
    return [check for check in CHECK_NAMES if check in wanted]


def _triangles(model: _Model) -> CheckResult:
    counts = [
        (node.name, sum(len(primitive.triangles) for primitive in node.primitives)) for node in model.scene.meshes
    ]
    total = sum(count for _, count in counts)
    return CheckResult(
        name="triangles",
        summary=f"{_count(total, 'triangle')}, {_against(total, model.max_triangles, 'triangle')}.",
        lines=[f"{name}: {count}" for name, count in counts],
        figures={"triangles": total, "budget": model.max_triangles},
    )


def _sub_pixel(model: _Model) -> CheckResult:
    reason = _no_size(model, "smallest")
    if reason is not None:
        return _skipped("sub-pixel", reason)
    assert model.screen_size is not None
    smallest = model.screen_size[0]
    per_meter = smallest / model.longest
    total = under = flat = 0
    lines: list[str] = []
    for node in model.scene.meshes:
        triangles = small = empty = 0
        for primitive in node.primitives:
            for a, b, c in primitive.triangles:
                area = (
                    length(
                        cross(
                            subtract(primitive.positions[b], primitive.positions[a]),
                            subtract(primitive.positions[c], primitive.positions[a]),
                        )
                    )
                    / 2
                )
                triangles += 1
                empty += area == 0
                small += area * per_meter**2 < 1
        if small:
            lines.append(f"{node.name}: {small} of {triangles}" + (f", {empty} of them with no area" if empty else ""))
        total, under, flat = total + triangles, under + small, flat + empty
    share = f" ({under / total:.0%})" if total else ""
    summary = f"{under} of {_count(total, 'triangle')}{share} cover less than a pixel at {smallest} pixels on screen, even face on."
    if flat:
        summary += f" {flat} of them have no area at all."
    return CheckResult(
        name="sub-pixel",
        summary=summary,
        lines=lines,
        figures={"pixels_per_meter": round(per_meter, 1), "under_a_pixel": under, "no_area": flat, "triangles": total},
    )


def _round_parts(model: _Model) -> CheckResult:
    """How far smooth shaded curves stray from true ones, where their faces meet at an angle, at the largest size."""
    reason = _no_size(model, "largest")
    if reason is not None:
        return _skipped("round-parts", reason)
    assert model.screen_size is not None
    largest = model.screen_size[1]
    per_meter = largest / model.longest
    lines: list[str] = []
    worst = 0.0
    total = 0
    for node in model.scene.meshes:
        edges = 0
        node_worst: tuple[float, float, float, Vector] | None = None
        for primitive in node.primitives:
            for error, sides, radius, where in _curve_edges(
                primitive.positions, primitive.normals, primitive.triangles
            ):
                edges += 1
                pixels = error * per_meter
                if node_worst is None or pixels > node_worst[0]:
                    node_worst = (pixels, sides, radius, where)
        if node_worst is not None:
            pixels, sides, radius, where = node_worst
            lines.append(
                f"{node.name}: up to {pixels:.1f} px off a true curve, where one of about {radius:.3f} m radius would "
                f"have about {sides:.0f} sides, at {_point(where)}; over {_count(edges, 'smooth edge')}."
            )
            worst = max(worst, pixels)
            total += edges
    summary = (
        f"Smooth shaded curves stray up to {worst:.1f} px from true curves at {largest} pixels on screen."
        if total
        else "No smooth shaded curves: every edge between faces at an angle is hard."
    )
    return CheckResult(
        name="round-parts",
        summary=summary,
        lines=lines,
        figures={"pixels_per_meter": round(per_meter, 1), "worst_pixels": round(worst, 2), "smooth_edges": total},
    )


def _curve_edges(
    positions: list[Vector], normals: list[Vector] | None, triangles: list[tuple[int, int, int]]
) -> list[tuple[float, float, float, Vector]]:
    """Each smooth edge between faces at an angle: how far its outline strays from a true curve in meters, the sides
    a whole turn of that curve would have, its radius, and where the edge is.

    An edge is smooth when the faces on both sides share its vertices' normals. Where faces of width w meet at an angle
    a, the curve through them has radius w / (2 sin(a / 2)), and its outline strays w / 2 tan(a / 4) from a true one.
    """
    if normals is None:
        return []
    keys = [
        (*(round(value, WELD_DIGITS) for value in position), *(round(value, WELD_DIGITS) for value in normal))
        for position, normal in zip(positions, normals, strict=True)
    ]
    sides: dict[tuple[Any, Any], list[tuple[int, int, int, int]]] = defaultdict(list)
    for index, (a, b, c) in enumerate(triangles):
        for first, second, opposite in ((a, b, c), (b, c, a), (c, a, b)):
            ends = (keys[first], keys[second])
            sides[min(ends), max(ends)].append((index, first, second, opposite))
    faces: dict[int, Vector | None] = {}

    def facing(index: int) -> Vector | None:
        if index not in faces:
            a, b, c = triangles[index]
            faces[index] = normalized(cross(subtract(positions[b], positions[a]), subtract(positions[c], positions[a])))
        return faces[index]

    found: list[tuple[float, float, float, Vector]] = []
    for shared in sides.values():
        if len(shared) != 2:
            continue
        (one, first, second, opposite), (other, _, _, across) = shared
        first_facing, other_facing = facing(one), facing(other)
        if first_facing is None or other_facing is None:
            continue
        angle = math.acos(max(-1.0, min(1.0, dot(first_facing, other_facing))))
        if angle < FLAT_RADIANS:
            continue
        start, end = positions[first], positions[second]
        along = subtract(end, start)
        span = length(along)
        if span == 0:
            continue
        width = max(length(cross(along, subtract(positions[corner], start))) / span for corner in (opposite, across))
        middle = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, (start[2] + end[2]) / 2)
        found.append((width / 2 * math.tan(angle / 4), 2 * math.pi / angle, width / (2 * math.sin(angle / 2)), middle))
    return found


def _draw_calls(model: _Model) -> CheckResult:
    """The draw calls of the model as it is drawn at once: one for each primitive of each mesh object, and for each swap
    group only those of its costliest part, since one of its parts shows at a time."""
    scene = model.scene
    swaps = {
        node.index: motion["group"]
        for node, motion in _declared(scene)
        if not _problems(motion) and motion["kind"] == "swap"
    }
    lines: list[str] = []
    total = 0
    materials: set[int | None] = set()
    # By swap group, the draw calls of each of its parts.
    groups: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for node in scene.meshes:
        count = len(node.primitives)
        materials.update(primitive.material for primitive in node.primitives)
        names = ", ".join(scene.material_name(primitive.material) for primitive in node.primitives)
        lines.append(f"{node.name}: {count} ({names})")
        member = _swap_member(scene, node, swaps)
        if member is None:
            total += count
        else:
            groups[swaps[member]][member] += count
    for group, members in groups.items():
        costliest = max(members.values())
        total += costliest
        lines.append(f"Swap group {group}: counted as {costliest}, its costliest part, since one part shows at a time.")
    summary = f"{_count(total, 'draw call')}, one for each primitive of each mesh object"
    summary += " and only the costliest part of each swap group" if groups else ""
    summary += f", from {_count(len(materials), 'material')}; {_against(total, model.max_draw_calls, 'draw call')}."
    return CheckResult(
        name="draw-calls",
        summary=summary,
        lines=lines,
        figures={
            "draw_calls": total,
            "materials": len(materials),
            "swap_groups": len(groups),
            "budget": model.max_draw_calls,
        },
    )


def _static_parts(model: _Model) -> CheckResult:
    scene = model.scene
    static = [node for node in scene.meshes if node.skin is None and not _moves(scene, node)]
    moving = sum(1 for node in scene.meshes if _moves(scene, node))
    skinned = sum(1 for node in scene.meshes if node.skin is not None)
    summary = f"{_count(len(static), 'mesh object')} with neither a motion nor a skin"
    summary += f": {', '.join(node.name for node in static)}." if static else "."
    return CheckResult(
        name="static-parts",
        summary=summary,
        lines=[f"{node.name}: {sum(len(p.triangles) for p in node.primitives)} triangles" for node in static],
        figures={"static": len(static), "moving": moving, "skinned": skinned},
    )


def _moving_parts(model: _Model, declared: list[tuple[Node, Any]]) -> CheckResult:
    if not declared:
        return _skipped("moving-parts", "Nothing declares a motion.")
    lines: list[str] = []
    wrong = 0
    for node, motion in declared:
        problems = _problems(motion)
        if problems:
            wrong += 1
            lines.append(f"{node.name}: {'; '.join(problems)}.")
        else:
            lines.append(_motion_line(model.scene, node, motion))
    groups: dict[str, list[str]] = defaultdict(list)
    for node, motion in declared:
        if not _problems(motion) and motion["kind"] == "swap":
            groups[motion["group"]].append(node.name)
    lines += [f"Swap group {group}: {', '.join(members)}." for group, members in groups.items()]
    summary = f"{_count(len(declared), 'declared motion')}"
    summary += f", {wrong} of them not well formed." if wrong else ", each well formed."
    return CheckResult(
        name="moving-parts", summary=summary, lines=lines, figures={"motions": len(declared), "not_well_formed": wrong}
    )


def _skeleton(model: _Model) -> CheckResult:
    scene = model.scene
    skins = scene.document.get("skins", [])
    if not skins:
        return _skipped("skeleton", "No skeleton.")
    nodes = scene.document.get("nodes", [])
    lines: list[str] = []
    bones = 0
    for index, skin in enumerate(skins):
        joints = skin.get("joints", [])
        bones += len(joints)
        names = [nodes[joint].get("name") or f"node {joint}" for joint in joints]
        users = [node for node in scene.meshes if node.skin == index]
        over = unweighted = 0
        for node in users:
            for primitive in node.primitives:
                if primitive.weights is None:
                    unweighted += len(primitive.positions)
                    continue
                over += sum(1 for weights in primitive.weights if sum(1 for w in weights if w > 0) > MOST_INFLUENCES)
                unweighted += sum(1 for weights in primitive.weights if sum(weights) <= 0)
        line = (
            f"{skin.get('name') or f'Skin {index}'}: {_count(len(joints), 'bone')} over "
            f"{', '.join(node.name for node in users) or 'no mesh'}; {_count(over, 'vertex', 'vertices')} with more "
            f"than {MOST_INFLUENCES} influences; {_count(unweighted, 'vertex', 'vertices')} unweighted"
        )
        defaults = [name for name in names if DEFAULT_BONE.match(name)]
        if defaults:
            line += f"; default bone names: {', '.join(defaults)}"
        lines.append(line + ".")
    return CheckResult(
        name="skeleton",
        summary=f"{_count(len(skins), 'skeleton')}, with {_count(bones, 'bone')}.",
        lines=lines,
        figures={"skeletons": len(skins), "bones": bones},
    )


def _markers(model: _Model) -> CheckResult:
    scene = model.scene
    joints = scene.joints
    markers = [
        node
        for node in scene.nodes
        if node.mesh is None and not node.children and not node.other and node.skin is None and node.index not in joints
    ]
    lines = []
    for node in markers:
        facing = normalized(rotate(node.world, (0.0, 0.0, 1.0)))
        line = f"{node.name} at {_point(translation(node.world))} m"
        line += f", its +Z toward {_point(facing)}" if facing is not None else ""
        lines.append(line + (", a default name." if DEFAULT_EMPTY.match(node.name) else "."))
    summary = (
        f"{_count(len(markers), 'marker')}: {', '.join(node.name for node in markers)}." if markers else "No markers."
    )
    return CheckResult(name="markers", summary=summary, lines=lines, figures={"markers": len(markers)})


def _palette(model: _Model, palette: Palette | None) -> CheckResult:
    if palette is None:
        return _skipped("palette", NO_PALETTE)
    scene = model.scene
    material = scene.material_name(palette.materials[0])
    lines = list(palette.problems)
    off_palette = _off_palette(scene, palette)
    figures: dict[str, Any] = {
        "width": palette.width,
        "height": palette.height,
        "roles": palette.columns,
        "schemes": palette.rows,
        "declared": palette.declared,
        "other_materials": len(off_palette),
    }
    others = [
        f"Drawn with {scene.material_name(index)} rather than the palette: {', '.join(parts)}."
        for index, parts in off_palette.items()
    ]
    if palette.png is None:
        return CheckResult(
            name="palette",
            summary=f"{_unread(palette)} It is drawn with {material}.",
            lines=lines + others,
            figures=figures,
        )
    swatches = {
        scheme: {role: hex_color(palette.swatch(column, row)) for column, role in enumerate(palette.roles)}
        for row, scheme in enumerate(palette.schemes)
    }
    figures["swatches"] = swatches
    for row, (scheme, colors) in enumerate(swatches.items()):
        lines.append(f"{scheme}: " + ", ".join(f"{role} {color}" for role, color in colors.items()) + ".")
        lines += [
            f"{role} in {scheme} is not one color across its swatch."
            for column, role in enumerate(palette.roles)
            if not palette.uniform(column, row)
        ]
        alike: dict[str, list[str]] = defaultdict(list)
        for role, color in colors.items():
            alike[color].append(role)
        lines += [
            f"In {scheme}, {_listed(roles)} are the same color, {color}."
            for color, roles in alike.items()
            if len(roles) > 1
        ]
    lines += _sampler(scene, palette)
    lines += others
    lines += _changed(_last_swatches(model.target), swatches)
    summary = (
        f"{_count(palette.columns, 'role')} by {_count(palette.rows, 'scheme')} in a {palette.width} by "
        f"{palette.height} pixel palette, drawn with {material}."
    )
    if not palette.declared:
        summary += " No material declares its roles and schemes, so each is named by its place."
    return CheckResult(name="palette", summary=summary, lines=lines, figures=figures)


def _face_roles(model: _Model, palette: Palette | None) -> CheckResult:
    """The role each triangle drawn with the palette takes from the swatch its UVs land in, and those that land in
    none or more than one."""
    if palette is None:
        return _skipped("face-roles", NO_PALETTE)
    if not palette.columns:
        return _skipped("face-roles", _unread(palette))
    triangles: dict[int, int] = defaultdict(int)
    area: dict[int, float] = defaultdict(float)
    parts: dict[int, list[str]] = defaultdict(list)
    rows: dict[int, int] = defaultdict(int)
    problems: list[str] = []
    across = off_center = outside = without = 0
    for node in model.scene.meshes:
        found = landed(palette, node)
        for (column, row), count in found.triangles.items():
            triangles[column] += count
            area[column] += found.area[column, row]
            rows[row] += count
            if node.name not in parts[column]:
                parts[column].append(node.name)
        for points, what in (
            (found.across, "land across more than one swatch"),
            (found.off_center, f"sit more than {CENTER_TEXELS:g} of a pixel off their swatch's center"),
            (found.outside, "land outside the palette"),
        ):
            if points:
                problems.append(
                    f"{node.name}: {_count(len(points), 'triangle')} {what}, such as at {_point(points[0])}."
                )
        if found.without_uvs:
            problems.append(
                f"{node.name}: {_count(found.without_uvs, 'triangle')} drawn with the palette have no "
                f"TEXCOORD_{palette.uv_set} to land on it with."
            )
        across += len(found.across)
        off_center += len(found.off_center)
        outside += len(found.outside)
        without += found.without_uvs
    total = sum(triangles.values())
    surface = sum(area.values())
    lines = [
        f"{role}: {_count(triangles[column], 'triangle')}, {_share(area[column], surface)} of their surface, on "
        f"{', '.join(parts[column])}."
        for column, role in enumerate(palette.roles)
        if triangles[column]
    ]
    unused = [role for column, role in enumerate(palette.roles) if not triangles[column]]
    if unused:
        lines.append(f"No triangles: {', '.join(unused)}.")
    if len(rows) > 1:
        lines.append(
            "By the row they land in: "
            + ", ".join(f"{palette.schemes[row]} {count}" for row, count in sorted(rows.items()))
            + "."
        )
    lines += problems
    used = sum(1 for count in triangles.values() if count)
    summary = (
        f"{_count(total, 'triangle')} land in a swatch, in {used} of the palette's {_count(palette.columns, 'role')}"
    )
    if len(rows) == 1:
        summary += f", all in one row, {palette.schemes[next(iter(rows))]}"
    summary += "."
    stray = [
        f"{count} {what}"
        for count, what in (
            (across, "land across swatches"),
            (outside, "land outside the palette"),
            (without, "have no UVs"),
            (off_center, "sit off their swatch's center"),
        )
        if count
    ]
    if stray:
        summary += f" Of those drawn with it, {_listed(stray)}."
    return CheckResult(
        name="face-roles",
        summary=summary,
        lines=lines,
        figures={
            "triangles": total,
            "roles": {role: triangles[column] for column, role in enumerate(palette.roles) if triangles[column]},
            "rows": {palette.schemes[row]: count for row, count in sorted(rows.items())},
            "across_swatches": across,
            "off_center": off_center,
            "outside": outside,
            "without_uvs": without,
        },
    )


def _emission(model: _Model, palette: Palette | None) -> CheckResult:
    if palette is None:
        return _skipped("emission", NO_PALETTE)
    emission = read_emission(model.scene, palette)
    material = model.scene.material_name(palette.materials[0])
    figures: dict[str, Any] = {"factor": list(emission.factor), "strength": emission.strength}
    if emission.image is None:
        if any(emission.factor):
            return CheckResult(
                name="emission",
                summary=f"{material} glows all over, with an emissive factor of {_point(emission.factor)} and no "
                "emission palette.",
                figures=figures,
            )
        return _skipped("emission", "No emission palette, so nothing glows.")
    if emission.png is None:
        return CheckResult(
            name="emission", summary=f"The emission palette could not be read: {emission.unreadable}.", figures=figures
        )
    figures["same_layout"] = same = (emission.png.width, emission.png.height) == (palette.width, palette.height)
    if not same or not palette.columns:
        return CheckResult(
            name="emission",
            summary=f"The emission palette is {emission.png.width} by {emission.png.height} pixels and the palette "
            f"{palette.width} by {palette.height}, so their swatches do not line up.",
            figures=figures,
        )
    lit: dict[str, list[str]] = {}
    for column, role in enumerate(palette.roles):
        for row, scheme in enumerate(palette.schemes):
            pixel = centered(emission.png, column, row, palette.columns, palette.rows)
            if any(pixel[:3]):
                lit.setdefault(role, []).append(f"{hex_color(pixel)} in {scheme}")
    figures["glowing"] = list(lit)
    lines = [f"{role}: {', '.join(colors)}." for role, colors in lit.items()]
    if not lit:
        summary = "Nothing glows: the emission palette is black at every swatch."
    elif not any(emission.factor):
        summary = f"The emission palette lights {_listed(list(lit))}, but the emissive factor is 0, so nothing glows."
    else:
        summary = (
            f"{_listed(list(lit))} {'glows' if len(lit) == 1 else 'glow'}, with an emissive factor of "
            f"{_point(emission.factor)} and a strength of {emission.strength:g}."
        )
    return CheckResult(name="emission", summary=summary, lines=lines, figures=figures)


def _detail_texture(model: _Model, detail: Detail | None) -> CheckResult:
    if detail is None:
        return _skipped("detail-texture", _no_detail(model))
    names = [model.scene.material_name(index) for index in detail.materials]
    lines = list(detail.problems)
    figures: dict[str, Any] = {"file": detail.file, "materials": names}
    header = detail.header
    if header is None:
        return CheckResult(
            name="detail-texture",
            summary=f"The detail texture declared on {_listed(names)} could not be read: {detail.unreadable}.",
            lines=lines,
            figures=figures,
        )
    kind = COLOR_TYPES.get(header.color_type, f"color type {header.color_type}")
    power_of_two = all(size & (size - 1) == 0 for size in (header.width, header.height))
    chunks = [chunk for chunk in COLOR_SPACE_CHUNKS if chunk in header.chunks]
    figures.update(
        width=header.width,
        height=header.height,
        bit_depth=header.bit_depth,
        color_type=kind,
        power_of_two=power_of_two,
        color_space_chunks=chunks,
    )
    if header.color_type != GRAYSCALE:
        lines.append(f"It is stored as {kind} rather than grayscale, and a renderer reads the detail from one channel.")
    if header.bit_depth > 8:
        lines.append(f"Its {header.bit_depth} bits a channel are more than most engines keep, which load 8.")
    elif header.bit_depth < 8 and header.color_type != INDEXED:
        lines.append(f"Its {header.bit_depth} bits a channel hold only {2**header.bit_depth} shades of gray.")
    if chunks:
        lines.append(
            f"It has {_listed(chunks)} {'chunks' if len(chunks) > 1 else 'chunk'}, which can make a loader treat it "
            "as color and change its values, though it holds amounts."
        )
    if not power_of_two:
        lines.append("Its size is not a power of two, which some engines resize or make no mipmaps for.")
    if detail.older > STALE_SECONDS:
        lines.append(
            f"It was written {round(detail.older / 60)} minutes before {GLB}, so it may be left from an earlier build."
        )
    if detail.file != DETAIL:
        lines.append(f"It is named {detail.file} rather than {DETAIL}, the name the app shows.")
    return CheckResult(
        name="detail-texture",
        summary=f"{detail.file}, declared on {_listed(names)}, is a {header.width} by {header.height} pixel "
        f"{header.bit_depth} bit {kind} PNG.",
        lines=lines,
        figures=figures,
    )


def _detail_uvs(model: _Model, measured: _Measured) -> CheckResult:
    """Where each triangle drawn with a material that declares the detail lands on its texture, and at how many texels
    a meter."""
    detail, palette = measured.detail, measured.palette
    if detail is None:
        return _skipped("detail-uvs", _no_detail(model))
    if detail.header is None:
        return _skipped("detail-uvs", _unread_detail(detail))
    width, height = detail.header.width, detail.header.height
    lines: list[str] = []
    problems: list[str] = []
    painted: list[tuple[str, Painted]] = []
    role_area: dict[int | None, float] = defaultdict(float)
    role_painted: dict[int | None, float] = defaultdict(float)
    for node, found in measured.unwraps:
        painted += [(node.name, triangle) for triangle in found.painted]
        for role, area in found.role_area.items():
            role_area[role] += area
            role_painted[role] += found.role_painted[role]
        if found.area:
            line = f"{node.name}: detail on {_share(found.painted_area, found.area)} of its surface"
            if found.densities:
                low, high = f"{min(found.densities):.0f}", f"{max(found.densities):.0f}"
                line += f", at {low} texels a meter" if low == high else f", at {low} to {high} texels a meter"
            if found.points:
                line += f"; {_count(len(found.points), 'triangle')} at one point, with none"
            lines.append(line + ".")
        if found.undeclared:
            lines.append(
                f"{node.name}: {_count(found.undeclared, 'triangle')} drawn with a material that declares no detail."
            )
        for points, what in (
            (found.outside, "land outside the texture"),
            (found.stretched, "are stretched, with more texels a meter one way across them than another"),
        ):
            if points:
                problems.append(
                    f"{node.name}: {_count(len(points), 'triangle')} {what}, such as at {_point(points[0])}."
                )
        if found.without_uvs:
            problems.append(
                f"{node.name}: {_count(found.without_uvs, 'triangle')} drawn with the detail have no TEXCOORD_1 to "
                "land on it with."
            )
    shared = overlapping(painted, width, height)
    problems += [
        f"{name}: {_count(len(points), 'triangle')} share texels with others, so those places show the same marks, "
        f"such as at {_point(points[0])}."
        for name, points in shared.items()
    ]
    if palette is not None and palette.columns and len(role_area) > 1:
        lines.append(
            "By role, the share with detail: "
            + ", ".join(
                f"{palette.roles[role] if role is not None else 'no role'} "
                f"{_share(role_painted[role], area) if role_painted[role] else 'none'}"
                for role, area in sorted(role_area.items(), key=lambda item: -1 if item[0] is None else item[0])
                if area
            )
            + "."
        )
    densities = [density for _, found in measured.unwraps for density in found.densities]
    points = sum(len(found.points) for _, found in measured.unwraps)
    texels = sum(found.texels for _, found in measured.unwraps)
    middle = statistics.median(densities) if densities else None
    per_pixel = None
    summary = f"{_count(len(painted), 'triangle')} land on the {width} by {height} pixel texture"
    if middle is not None:
        summary += f" at {middle:.0f} texels a meter"
        if _no_size(model, "largest") is None:
            assert model.screen_size is not None
            smallest, largest = model.screen_size
            per_pixel = middle * model.longest / largest
            summary += f", {per_pixel:.1f} texels a pixel at {largest} pixels on screen"
            lines.append(
                f"At {smallest} pixels on screen, each pixel spans about {middle * model.longest / smallest:.0f} "
                "texels, so marks narrower than that blend into their color there."
            )
    summary += f", covering {_share(texels, width * height)} of it."
    if points:
        summary += f" {_count(points, 'triangle')} sit at one point and take no detail."
    return CheckResult(
        name="detail-uvs",
        summary=summary,
        lines=lines + problems,
        figures={
            "triangles": len(painted),
            "at_one_point": points,
            "texels_per_meter": round(middle, 1) if middle is not None else None,
            "texels_per_meter_range": [round(min(densities), 1), round(max(densities), 1)] if densities else None,
            "texels_per_pixel": round(per_pixel, 2) if per_pixel is not None else None,
            "coverage": round(texels / (width * height), 3),
            "stretched": sum(len(found.stretched) for _, found in measured.unwraps),
            "overlapping": sum(len(points) for points in shared.values()),
            "outside": sum(len(found.outside) for _, found in measured.unwraps),
            "without_uvs": sum(found.without_uvs for _, found in measured.unwraps),
        },
    )


def _off_palette(scene: Scene, palette: Palette) -> dict[int | None, list[str]]:
    """By material, the parts drawn with one that is not the palette's."""
    found: dict[int | None, list[str]] = defaultdict(list)
    for node in scene.meshes:
        for primitive in node.primitives:
            if primitive.material not in palette.materials and node.name not in found[primitive.material]:
                found[primitive.material].append(node.name)
    return found


def _sampler(scene: Scene, palette: Palette) -> list[str]:
    """How the palette's texture is sampled, and whether its UVs are moved by a transform the check does not apply."""
    texture = scene.document["textures"][palette.texture]
    samplers = scene.document.get("samplers", [])
    sampler = samplers[texture["sampler"]] if isinstance(texture.get("sampler"), int) else {}
    unset = "as the viewer chooses"
    across, down = (WRAPS.get(sampler.get(key, REPEAT), "wrapped") for key in ("wrapS", "wrapT"))
    edges = across if across == down else f"{across} across and {down} down"
    line = (
        f"Its texture is magnified {FILTERS.get(sampler.get('magFilter'), unset)} and shrunk "
        f"{FILTERS.get(sampler.get('minFilter'), unset)}, and its edges are {edges}."
    )
    if sampler.get("minFilter") not in UNMIPMAPPED:
        line += " A viewer that makes mipmaps of it averages neighboring swatches together where the model is small."
    lines = [line]
    info = scene.document["materials"][palette.materials[0]]["pbrMetallicRoughness"]["baseColorTexture"]
    if "KHR_texture_transform" in info.get("extensions", {}):
        lines.append("Its texture is moved with KHR_texture_transform, which the check does not apply to the UVs.")
    return lines


def _last_swatches(target: Path) -> dict[str, dict[str, str]] | None:
    """Each swatch's color in the model's last report, by scheme and role, when it reported its palette."""
    try:
        report = ModelCheck.model_validate_json(read_atomically(target / REPORT))
    except (OSError, ValueError):
        return None
    found = next((entry for entry in report.checks if entry.name == "palette"), None)
    swatches = found.figures.get("swatches") if found is not None else None
    return swatches if isinstance(swatches, dict) else None


def _changed(last: dict[str, dict[str, str]] | None, swatches: dict[str, dict[str, str]]) -> list[str]:
    """The swatches that changed since the last report, so a change nobody asked for shows."""
    if last is None:
        return []
    lines: list[str] = []
    for scheme, colors in swatches.items():
        if scheme not in last:
            lines.append(f"{scheme} is a new scheme since the last check.")
            continue
        for role, color in colors.items():
            before = last[scheme].get(role)
            if before is None:
                lines.append(f"{role} in {scheme} is new since the last check, {color}.")
            elif before != color:
                lines.append(f"{role} in {scheme} changed from {before} to {color} since the last check.")
        lines += [
            f"{role} in {scheme}, {color}, is gone since the last check."
            for role, color in last[scheme].items()
            if role not in colors
        ]
    lines += [f"{scheme} is gone since the last check." for scheme in last if scheme not in swatches]
    return lines


def _unread(palette: Palette) -> str:
    return f"Its base color image could not be read as a palette: {palette.unreadable}."


def _no_detail(model: _Model) -> str:
    if (model.target / DETAIL).is_file():
        return f"{NO_DETAIL} {DETAIL} beside {GLB} is not read without one."
    return NO_DETAIL


def _unread_detail(detail: Detail) -> str:
    return f"Its detail texture could not be read: {detail.unreadable}."


def _declared(scene: Scene) -> list[tuple[Node, Any]]:
    """Each node that declares a motion, with it as declared: an object, or JSON text of one."""
    declared: list[tuple[Node, Any]] = []
    for node in scene.nodes:
        motion = node.extras.get("motion")
        if isinstance(motion, str):
            # Left as the text it is when it is not JSON, so the report can say so.
            with contextlib.suppress(ValueError):
                motion = json.loads(motion)
        if motion is not None:
            declared.append((node, motion))
    return declared


def _problems(motion: Any) -> list[str]:
    """What is wrong with how a motion is declared, if anything."""
    if isinstance(motion, str):
        return [f'its motion is the text {motion!r} rather than an object with a kind, such as {{"kind": "slide"}}']
    if not isinstance(motion, dict):
        return ['its motion is not an object with a kind, such as {"kind": "slide"}']
    kind = motion.get("kind")
    if kind not in MOTION_KINDS:
        return [f"its motion's kind is {kind!r}, not one of {', '.join(MOTION_KINDS)}"]
    problems: list[str] = []
    if kind in SWEPT:
        axis = motion.get("axis")
        if not _numbers(axis, 3) or not any(axis):
            problems.append(f"a {kind} needs an axis of three numbers, not all 0")
    if kind in RANGED:
        span = motion.get("range")
        if not _numbers(span, 2):
            problems.append(f"a {kind} needs a range of two numbers")
        elif span[0] > span[1]:
            problems.append("its range starts higher than it ends")
    if kind == "swap" and not (isinstance(motion.get("group"), str) and motion["group"]):
        problems.append("a swap needs the group it swaps within")
    return problems


def _numbers(value: Any, count: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == count
        and all(isinstance(each, int | float) and not isinstance(each, bool) for each in value)
    )


def _motion_line(scene: Scene, node: Node, motion: dict[str, Any]) -> str:
    kind = motion["kind"]
    pivot = _point(translation(node.world))
    bone = " It is a bone, so it is not swept or posed." if node.index in scene.joints else ""
    if kind == "slide":
        low, high = motion["range"]
        line = f"{node.name} slides from {low:g} to {high:g} m along {_point(motion['axis'])} in its parent's space, from its pivot at {pivot}."
    elif kind == "hinge":
        low, high = motion["range"]
        line = f"{node.name} turns from {low:g} to {high:g} degrees about {_point(motion['axis'])} in its parent's space, through its pivot at {pivot}."
    elif kind == "spin":
        line = f"{node.name} spins about {_point(motion['axis'])} in its parent's space, through its pivot at {pivot}."
    elif kind == "swap":
        line = f"{node.name} swaps with the rest of group {motion['group']}."
    else:
        line = f"{node.name} can be hidden."
    return line + bone


def _swept(scene: Scene, node: Node, motion: dict[str, Any]) -> dict[str, Any]:
    """A well formed motion as Blender moves through it: in model space, with how far a unit along its axis goes."""
    swept: dict[str, Any] = {"node": node.name, "kind": motion["kind"], "bone": node.index in scene.joints}
    if motion["kind"] in SWEPT:
        parent = scene.node(node.parent).world if node.parent is not None else IDENTITY
        given = (float(motion["axis"][0]), float(motion["axis"][1]), float(motion["axis"][2]))
        axis = rotate(parent, given)
        swept["axis"] = normalized(axis)
        # A slide's range is in its parent's units, which a scale above it stretches.
        swept["unit"] = length(axis) / length(given)
        swept["pivot"] = translation(node.world)
        swept["range"] = [float(value) for value in motion["range"]] if motion["kind"] in RANGED else [0.0, 360.0]
    if motion["kind"] == "swap":
        swept["group"] = motion["group"]
    return swept


def _swap_member(scene: Scene, node: Node, swaps: dict[int, str]) -> int | None:
    """The part of a swap group the node is, or hangs from; None when it is in none."""
    current: Node | None = node
    while current is not None:
        if current.index in swaps:
            return current.index
        current = scene.node(current.parent) if current.parent is not None else None
    return None


def _moves(scene: Scene, node: Node) -> bool:
    """Whether the node or anything it hangs from declares a motion."""
    current: Node | None = node
    while current is not None:
        if "motion" in current.extras:
            return True
        current = scene.node(current.parent) if current.parent is not None else None
    return False


def _no_size(model: _Model, which: str) -> str | None:
    """Why a check that measures at a size on screen cannot, if it cannot."""
    if model.screen_size is None:
        return f"No screen size budget, so no {which} size on screen to measure at."
    if model.longest == 0:
        return "The model has no size."
    return None


def _blender(measured: _Measured) -> dict[str, Any]:
    command = _blender_request(measured)
    try:
        finished = subprocess.run(command, capture_output=True, timeout=BLENDER_TIMEOUT_SECONDS, check=False)
    except FileNotFoundError:
        return {"error": "uv is not on PATH, and the checks that need Blender run through it."}
    except subprocess.TimeoutExpired:
        return {"error": f"Blender did not finish within {BLENDER_TIMEOUT_SECONDS} seconds."}
    return _blender_result(measured, finished.returncode, finished.stdout + finished.stderr)


async def _blender_async(measured: _Measured) -> dict[str, Any]:
    command = await asyncio.to_thread(_blender_request, measured)
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
    except FileNotFoundError:
        return {"error": "uv is not on PATH, and the checks that need Blender run through it."}
    try:
        async with asyncio.timeout(BLENDER_TIMEOUT_SECONDS):
            output, _ = await process.communicate()
    except BaseException as error:
        process.kill()
        await process.wait()
        if isinstance(error, TimeoutError):
            return {"error": f"Blender did not finish within {BLENDER_TIMEOUT_SECONDS} seconds."}
        raise
    return await asyncio.to_thread(_blender_result, measured, process.returncode or 0, output)


def _blender_request(measured: _Measured) -> list[str]:
    """Write what Blender is asked to check, clearing the renders of the last check, and return the command."""
    model = measured.model
    checks = model.target / CHECKS
    checks.mkdir(exist_ok=True)
    for render in checks.glob("*.png"):
        render.unlink()
    (model.target / BLENDER_RESULT).unlink(missing_ok=True)
    request = {
        "glb": str(model.target / GLB),
        "out": str(checks),
        "result": str(model.target / BLENDER_RESULT),
        "checks": measured.blender,
        "screen_size": model.screen_size,
        "longest": model.longest,
        "references": [str(path) for path in model.references],
        "motions": measured.motions,
        "palette": _palette_request(measured.palette),
        "detail": _detail_request(measured),
        "ray_directions": RAY_DIRECTIONS,
        "sweep_steps": SWEEP_STEPS,
        "sheet_height": SHEET_HEIGHT,
        "pose_size": POSE_SIZE,
        "samples": RENDER_SAMPLES,
    }
    write_atomically(model.target / BLENDER_REQUEST, json.dumps(request, indent=2))
    return [*BLENDER_COMMAND, str(model.target / BLENDER_REQUEST)]


def _palette_request(palette: Palette | None) -> dict[str, Any] | None:
    """What Blender needs to render each scheme: the palette's size, which finds it among the images, and its rows."""
    if palette is None or not palette.columns:
        return None
    return {"size": [palette.width, palette.height], "rows": palette.rows, "schemes": palette.schemes}


def _detail_request(measured: _Measured) -> dict[str, Any] | None:
    """What Blender needs to read the detail under each role and render with it: the texture, the materials that
    declare it, and where each triangle lands on it, in pixels from its top left."""
    detail = measured.detail
    if detail is None or detail.header is None:
        return None
    painted = [triangle for _, found in measured.unwraps for triangle in found.painted]
    points = dict.fromkeys((round(x, 2), round(y, 2)) for _, found in measured.unwraps for x, y in found.points)
    return {
        "path": str(measured.model.target / detail.file),
        "size": [detail.header.width, detail.header.height],
        "materials": [measured.model.scene.material_name(index) for index in detail.materials],
        "triangles": [[value for corner in triangle.corners for value in corner] for triangle in painted],
        "roles": [-1 if triangle.role is None else triangle.role for triangle in painted],
        "points": [list(point) for point in points],
    }


def _blender_result(measured: _Measured, code: int, output: bytes) -> dict[str, Any]:
    path = measured.model.target / BLENDER_RESULT
    if code == 0 and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    tail = "\n".join(output.decode("utf-8", errors="replace").strip().splitlines()[-BLENDER_OUTPUT_LINES:])
    return {"error": f"Blender failed with exit code {code}: {tail}"}


def _report(measured: _Measured, found: dict[str, Any]) -> ModelCheck:
    model = measured.model
    results = measured.results
    error = found.get("error")
    errors: dict[str, str] = found.get("errors", {})
    for check in measured.blender:
        why = error or errors.get(check)
        if why is not None and check != "moving-parts":
            results[check] = _skipped(check, why)
    if "buried-faces" in measured.blender and "buried-faces" not in results:
        results["buried-faces"] = _buried(found["buried"])
    if "moving-parts" in measured.blender:
        moving = results["moving-parts"]
        why = error or errors.get("moving-parts")
        moving.lines += [f"Not swept: {why}"] if why is not None else _sweep_lines(found["sweeps"])
    if "on-screen" in measured.blender and "on-screen" not in results:
        assert model.screen_size is not None
        smallest, largest = model.screen_size
        shown = f", beside {_count(len(model.references), 'reference')}" if model.references else ""
        results["on-screen"] = CheckResult(
            name="on-screen",
            summary=f"Rendered at {smallest} and {largest} pixels on screen, each also scaled up with its pixels "
            f"kept{shown}.",
            files=[(CHECKS / name).as_posix() for name in found["on_screen"]],
        )
    if "poses" in measured.blender and "poses" not in results:
        results["poses"] = _poses(found["poses"])
    if "schemes" in measured.blender and "schemes" not in results:
        results["schemes"] = _schemes(model, measured.palette, found["schemes"])
    if "detail-colors" in measured.blender and "detail-colors" not in results:
        results["detail-colors"] = _detail_colors(measured.palette, found["detail_colors"])
    if "detail-renders" in measured.blender and "detail-renders" not in results:
        results["detail-renders"] = _detail_renders(model, found["detail_renders"])
    scene = model.scene
    report = ModelCheck(
        name=model.target.name,
        directory=model.target,
        checked=datetime.now(UTC),
        glb_sha256=measured.sha256,
        max_triangles=model.max_triangles,
        max_draw_calls=model.max_draw_calls,
        screen_size=model.screen_size,
        dimensions=(model.high[0] - model.low[0], model.high[1] - model.low[1], model.high[2] - model.low[2]),
        bounds=(model.low, model.high),
        triangles=sum(len(primitive.triangles) for node in scene.meshes for primitive in node.primitives),
        mesh_objects=len(scene.meshes),
        materials=len({primitive.material for node in scene.meshes for primitive in node.primitives}),
        checks=[results[check] for check in measured.names],
    )
    (model.target / CHECKS).mkdir(exist_ok=True)
    write_atomically(model.target / REPORT, report.model_dump_json(indent=2))
    return report


def _buried(found: dict[str, dict[str, Any]]) -> CheckResult:
    buried = sum(counts["buried"] for counts in found.values())
    total = sum(counts["triangles"] for counts in found.values())
    return CheckResult(
        name="buried-faces",
        summary=f"{buried} of {_count(total, 'triangle')} are reached by no ray from outside the model, cast from "
        f"{RAY_DIRECTIONS} directions. One seen only through a narrow opening, such as deep in a pipe, can count.",
        lines=[
            f"{name}: {counts['buried']} of {counts['triangles']}, such as at "
            + ", ".join(_point(point) for point in counts["examples"])
            for name, counts in found.items()
            if counts["buried"]
        ],
        figures={"buried": buried, "triangles": total},
    )


def _sweep_lines(sweeps: dict[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for name, sweep in sweeps.items():
        if sweep.get("missing"):
            lines.append(f"{name} is not an object Blender imported, so it was not swept.")
            continue
        hits = sweep["hits"]
        if not hits:
            lines.append(f"{name} touches nothing across its range that it does not touch at rest.")
            continue
        touched: dict[str, list[str]] = defaultdict(list)
        for hit in hits:
            for other in hit["touches"]:
                touched[other].append(f"{hit['value']:g}")
        for other, values in touched.items():
            lines.append(f"{name} touches {other} in places it does not at rest, at {', '.join(values)} of its range.")
    return lines


def _poses(found: dict[str, dict[str, Any]]) -> CheckResult:
    lines = []
    for name, pose in found.items():
        lines.append(f"{name}: {pose['shows']}, left to right.")
    return CheckResult(
        name="poses",
        summary=f"Rendered {_count(len(found), 'motion')} through its poses.",
        lines=lines,
        files=[(CHECKS / pose["file"]).as_posix() for pose in found.values()],
    )


def _schemes(model: _Model, palette: Palette | None, files: list[str]) -> CheckResult:
    assert palette is not None
    if model.screen_size is not None:
        sizes = f"at {' and '.join(str(size) for size in sorted(set(model.screen_size)))} pixels on screen, each scaled up with its pixels kept"
    else:
        sizes = f"at {POSE_SIZE} pixels, with no screen size budget to render at"
    return CheckResult(
        name="schemes",
        summary=f"Rendered in each of its {_count(palette.rows, 'scheme')}, lit flat so each face shows its "
        f"swatch's color as the palette stores it, {sizes}; left to right, {_listed(palette.schemes)}.",
        files=[(CHECKS / name).as_posix() for name in files],
    )


def _detail_colors(palette: Palette | None, found: dict[str, Any]) -> CheckResult:
    """The detail under the faces that take it, as Blender counts each 8 bit value of it, and the colors it shades each
    role to in each scheme."""
    under: list[int] = found["all"]
    total = sum(under)
    if not total:
        return CheckResult(name="detail-colors", summary="No texel lies under a triangle with detail.")
    low, high = _range(under)
    away = total - sum(under[value] for value in MID_GRAY)
    lines: list[str] = []
    figures: dict[str, Any] = {"low": round(low / 255, 3), "high": round(high / 255, 3), "away": round(away / total, 3)}
    roles: dict[str, Any] = {}
    clipping: list[str] = []
    colored = palette is not None and palette.png is not None and palette.columns > 0
    for column, counts in sorted(found["roles"].items(), key=lambda item: int(item[0])):
        texels = sum(counts)
        if not texels:
            continue
        role_low, role_high = _range(counts)
        role = int(column)
        name = palette.roles[role] if palette is not None and 0 <= role < len(palette.roles) else "no role"
        line = (
            f"{name}: from {role_low / 255:.2f} to {role_high / 255:.2f}, "
            f"{_share(texels - sum(counts[value] for value in MID_GRAY), texels)} away from mid gray"
        )
        entry: dict[str, Any] = {"low": round(role_low / 255, 3), "high": round(role_high / 255, 3)}
        if colored and palette is not None and 0 <= role < palette.columns:
            schemes: dict[str, Any] = {}
            shades = []
            for row, scheme in enumerate(palette.schemes):
                color = palette.swatch(role, row)
                brightest = max(_linear(channel) for channel in color[:3])
                clipped = sum(
                    count for value, count in enumerate(counts) if brightest * 2 * value / 255 > 1 + CLIP_MARGIN
                )
                darkest, lightest = hex_color(_shaded(color, role_low)), hex_color(_shaded(color, role_high))
                schemes[scheme] = {"darkest": darkest, "lightest": lightest, "clipped": round(clipped / texels, 3)}
                shade = f"{scheme} {hex_color(color)} from {darkest} to {lightest}"
                if clipped:
                    shade += f", {_share(clipped, texels)} of it clipped at full brightness"
                    if name not in clipping:
                        clipping.append(name)
                shades.append(shade)
            entry["schemes"] = schemes
            line += "; " + "; ".join(shades)
        roles[name] = entry
        lines.append(line + ".")
    figures["roles"] = roles
    neutral = [value for value, count in enumerate(found["neutral"]) if count and value not in MID_GRAY]
    if neutral:
        lines.append(
            "Triangles at one point sit on texels of "
            + ", ".join(f"{value / 255:.2f}" for value in neutral)
            + " rather than mid gray, so they are shaded too."
        )
    summary = (
        f"Under the faces with detail it runs from {low / 255:.2f} to {high / 255:.2f}, with {_share(away, total)} of "
        "its texels away from mid gray."
    )
    if clipping:
        summary += f" It clips {_listed(clipping)} at full brightness in places."
    if not colored:
        summary += " With no palette to read, it gives no colors."
    return CheckResult(name="detail-colors", summary=summary, lines=lines, figures=figures)


def _detail_renders(model: _Model, files: list[str]) -> CheckResult:
    if model.screen_size is not None:
        sizes = (
            f"at {' and '.join(str(size) for size in sorted(set(model.screen_size)))} pixels on screen, each scaled up "
            f"with its pixels kept, then the detail alone on mid gray at {model.screen_size[1]}"
        )
    else:
        sizes = f"at {POSE_SIZE} pixels, with no screen size budget to render at, then the detail alone on mid gray"
    return CheckResult(
        name="detail-renders",
        summary="Rendered lit flat without its detail and with it, shading the base color as a renderer does, "
        f"{sizes}, and the texture with the edges of its islands drawn on it.",
        files=[(CHECKS / name).as_posix() for name in files],
    )


def _range(counts: list[int]) -> tuple[int, int]:
    """The lowest and highest 8 bit values with a count."""
    values = [value for value, count in enumerate(counts) if count]
    return values[0], values[-1]


def _linear(channel: int) -> float:
    """An sRGB channel's light, from 0 to 1."""
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _shaded(color: Rgba, detail: int) -> Rgba:
    """The color a renderer draws a fully lit face of, shaded by the detail's 8 bit value, as an sRGB color."""
    shaded = []
    for channel in color[:3]:
        light = min(1.0, _linear(channel) * 2 * detail / 255)
        value = light * 12.92 if light <= 0.0031308 else 1.055 * light ** (1 / 2.4) - 0.055
        shaded.append(round(value * 255))
    return shaded[0], shaded[1], shaded[2], color[3]


def _skipped(name: CheckName, why: str) -> CheckResult:
    return CheckResult(name=name, summary=why, skipped=True)


def _against(count: int, budget: int | None, noun: str) -> str:
    if budget is None:
        return f"with no {noun} budget"
    if count <= budget:
        return f"{budget - count} under the budget of {budget}"
    return f"{count - budget} over the budget of {budget}"


def _count(count: int, noun: str, plural: str | None = None) -> str:
    return f"{count} {noun if count == 1 else plural or noun + 's'}"


def _share(part: float, whole: float) -> str:
    share = part / whole if whole else 0.0
    return "under 1%" if 0 < share < 0.01 else f"{share:.0%}"


def _listed(items: list[str]) -> str:
    if len(items) < 3:
        return " and ".join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _point(point: Any) -> str:
    # Rounded before it is written, so a value a hair under 0 reads as 0.000 rather than -0.000.
    return "(" + ", ".join(f"{round(float(value), 3) + 0.0:.3f}" for value in point) + ")"
