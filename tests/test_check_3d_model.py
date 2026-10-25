from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path

from fakes import run_record
from glbs import Glb, Part, box, cylinder, gray_png, png
import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model.check import check
from modeling_3d.capabilities.create_3d_model.record import write_record
from modeling_3d.cli import app
from modeling_3d.schemas import CHECK_GROUPS, CHECK_NAMES, CheckResult, ModelCheck, Modeling3dError, ModelRecord

runner = CliRunner()
QUARTER_TURN_ABOUT_Y = (0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4))


def made(
    root: Path,
    glb: Glb | bytes | None,
    max_triangles: int | None = None,
    max_draw_calls: int | None = None,
    screen_size: tuple[int, int] | None = None,
    references: list[str] | None = None,
    name: str = "part",
) -> Path:
    """A model as a run leaves it, built to `glb` and to the budgets its prompt was given."""
    target = root / name
    target.mkdir(parents=True)
    run = run_record(
        id="20261017-100000-ab12cd",
        prompt="A part",
        references=references or [],
        max_triangles=max_triangles,
        max_draw_calls=max_draw_calls,
        screen_size=screen_size,
    )
    write_record(target, ModelRecord(id="id", name=name, created=datetime.now(UTC), runs=[run]))
    if glb is not None:
        (target / "model.glb").write_bytes(glb if isinstance(glb, bytes) else glb.bytes())
    return target


def boxes() -> Glb:
    """A body and a lid on it, 1 m wide and 1.5 m tall."""
    glb = Glb()
    glb.node("Body", mesh=glb.mesh(box(center=(0.0, 0.5, 0.0))))
    glb.node("Lid", mesh=glb.mesh(box(size=(1.0, 0.5, 1.0), center=(0.0, 1.25, 0.0))))
    return glb


def result(report: ModelCheck, name: str) -> CheckResult:
    return next(entry for entry in report.checks if entry.name == name)


def test_the_report_measures_the_model_against_its_own_budgets_and_is_kept_beside_it(tmp_path: Path) -> None:
    target = made(tmp_path, boxes(), max_triangles=20, max_draw_calls=1, screen_size=(40, 240))

    report = lib.check_3d_model("part", directory=tmp_path)

    assert [entry.name for entry in report.checks] == list(CHECK_NAMES)
    assert (report.max_triangles, report.max_draw_calls, report.screen_size) == (20, 1, (40, 240))
    assert report.dimensions == (1.0, 1.5, 1.0)
    assert report.bounds == ((-0.5, 0.0, -0.5), (0.5, 1.5, 0.5))
    assert (report.triangles, report.mesh_objects, report.materials) == (24, 2, 1)
    assert report.glb_sha256 == hashlib.sha256((target / "model.glb").read_bytes()).hexdigest()
    assert result(report, "triangles").figures == {"triangles": 24, "budget": 20}
    assert result(report, "triangles").lines == ["Body: 12", "Lid: 12"]
    assert result(report, "draw-calls").figures == {"draw_calls": 2, "materials": 1, "swap_groups": 0, "budget": 1}
    for name in CHECK_GROUPS["color"]:
        assert result(report, name).summary == check.NO_PALETTE
    for name in CHECK_GROUPS["detail"]:
        assert result(report, name).summary == check.NO_DETAIL
    assert ModelCheck.model_validate_json((target / "checks" / "report.json").read_text(encoding="utf-8")) == report
    assert check.covers(target)
    (target / "model.glb").write_bytes(Glb().bytes())
    assert not check.covers(target)


def test_budgets_passed_replace_the_model_s_own_and_a_model_without_is_never_measured_against_the_defaults(
    tmp_path: Path,
) -> None:
    made(tmp_path, boxes(), max_triangles=20, max_draw_calls=1, screen_size=(40, 240))
    made(tmp_path, boxes(), name="plain")

    report = lib.check_3d_model("part", directory=tmp_path, max_triangles=100, max_draw_calls=None, screen_size=None)
    plain = lib.check_3d_model("plain", directory=tmp_path)

    assert (report.max_triangles, report.max_draw_calls, report.screen_size) == (100, None, None)
    assert result(report, "triangles").figures["budget"] == 100
    assert result(report, "draw-calls").figures["budget"] is None
    for name in ("sub-pixel", "round-parts", "on-screen"):
        assert result(report, name).skipped
    assert (plain.max_triangles, plain.max_draw_calls, plain.screen_size) == (None, None, None)
    assert result(plain, "triangles").figures["budget"] is None
    assert result(plain, "sub-pixel").skipped


def test_checks_are_chosen_by_name_or_group_in_one_order_and_unknown_ones_and_models_name_those_there_are(
    tmp_path: Path,
) -> None:
    made(tmp_path, boxes())

    report = lib.check_3d_model("part", directory=tmp_path, checks=["triangles", "rig"])
    with pytest.raises(Modeling3dError) as unknown:
        lib.check_3d_model("part", directory=tmp_path, checks=["tris"])
    with pytest.raises(Modeling3dError) as missing:
        lib.check_3d_model("other", directory=tmp_path)

    assert [entry.name for entry in report.checks] == ["triangles", *CHECK_GROUPS["rig"]]
    assert unknown.value.reason == "no-such-check"
    for name in (*CHECK_NAMES, *CHECK_GROUPS):
        assert name in str(unknown.value)
    assert missing.value.reason == "no-such-model"
    assert "part" in str(missing.value)


@pytest.mark.parametrize(
    ("glb", "reason"),
    [(None, "not-built"), (b"glTF", "bad-glb"), (b"not a model", "bad-glb")],
)
def test_a_model_that_cannot_be_checked_says_why(tmp_path: Path, glb: bytes | None, reason: str) -> None:
    made(tmp_path, glb)

    with pytest.raises(Modeling3dError) as failure:
        lib.check_3d_model("part", directory=tmp_path)

    assert failure.value.reason == reason


def test_triangles_under_a_pixel_at_the_smallest_size_are_counted_by_part(tmp_path: Path) -> None:
    glb = Glb()
    glb.node("Body", mesh=glb.mesh(box(center=(0.0, 0.5, 0.0))))
    glb.node("Rivet", mesh=glb.mesh(box(size=(0.01, 0.01, 0.01), center=(0.0, 0.5, 0.5))))
    made(tmp_path, glb, screen_size=(10, 100))

    report = lib.check_3d_model("part", directory=tmp_path, checks=["sub-pixel"])

    [found] = report.checks
    assert found.figures == {"pixels_per_meter": 10.0, "under_a_pixel": 12, "no_area": 0, "triangles": 24}
    assert found.lines == ["Rivet: 12 of 12"]


def test_round_parts_measure_how_far_a_smooth_curve_strays_at_the_largest_size_and_flat_ones_have_none(
    tmp_path: Path,
) -> None:
    glb = Glb()
    glb.node("Piston", mesh=glb.mesh(cylinder(radius=0.5, height=1.0, sides=8)))
    glb.node("Box", mesh=glb.mesh(box(size=(0.2, 0.2, 0.2), center=(0.0, 0.5, 0.0))))
    made(tmp_path, glb, screen_size=(10, 100))
    flat = Glb()
    flat.node("Piston", mesh=flat.mesh(cylinder(radius=0.5, height=1.0, sides=8, smooth=False)))
    made(tmp_path, flat, screen_size=(10, 100), name="flat")

    [found] = lib.check_3d_model("part", directory=tmp_path, checks=["round-parts"]).checks
    [unsmoothed] = lib.check_3d_model("flat", directory=tmp_path, checks=["round-parts"]).checks

    # A regular polygon of n sides strays r (1 - cos(pi / n)) from its circle.
    strays = 0.5 * (1 - math.cos(math.pi / 8)) * 100
    assert found.figures == {"pixels_per_meter": 100.0, "worst_pixels": round(strays, 2), "smooth_edges": 8}
    [line] = found.lines
    assert line.startswith("Piston:")
    assert all(figure in line for figure in (f"{strays:.1f} px", "0.500 m", "8 sides"))
    assert unsmoothed.figures["smooth_edges"] == 0


def test_draw_calls_count_each_primitive_of_each_mesh_object(tmp_path: Path) -> None:
    glb = Glb()
    paint, metal = glb.material("Paint"), glb.material("Metal")
    glb.node("Body", mesh=glb.mesh(box(material=paint), box(center=(0.0, 1.0, 0.0), material=metal)))
    wheel = glb.mesh(box(size=(0.2, 0.2, 0.2), material=paint))
    glb.node("Wheel_L", mesh=wheel)
    glb.node("Wheel_R", mesh=wheel)
    made(tmp_path, glb, max_draw_calls=2)

    [found] = lib.check_3d_model("part", directory=tmp_path, checks=["draw-calls"]).checks

    assert found.figures == {"draw_calls": 4, "materials": 2, "swap_groups": 0, "budget": 2}
    assert found.lines == ["Body: 2 (Paint, Metal)", "Wheel_L: 1 (Paint)", "Wheel_R: 1 (Paint)"]


def test_a_swap_group_counts_the_draw_calls_of_its_costliest_part_since_one_shows_at_a_time(tmp_path: Path) -> None:
    glb = Glb()
    paint, glass = glb.material("Paint"), glb.material("Glass")
    glb.node("Body", mesh=glb.mesh(box(material=paint)))
    swap = {"motion": {"kind": "swap", "group": "shade"}}
    glb.node("Cone", mesh=glb.mesh(box(material=paint)), extras=swap)
    dome = glb.node("Dome", mesh=glb.mesh(box(material=paint)), extras=swap)
    glb.node("Lens", mesh=glb.mesh(box(material=glass)), parent=dome)
    made(tmp_path, glb, max_draw_calls=3)

    [found] = lib.check_3d_model("part", directory=tmp_path, checks=["draw-calls"]).checks

    assert found.figures == {"draw_calls": 3, "materials": 2, "swap_groups": 1, "budget": 3}
    assert "shade" in found.lines[-1]


def test_motions_on_bones_are_described_but_not_swept_or_posed(tmp_path: Path) -> None:
    glb = Glb()
    arm = glb.node("Arm", extras={"motion": {"kind": "hinge", "axis": [0, 0, 1], "range": [0, 45]}})
    glb.node("Lamp", mesh=glb.mesh(box()), skin=glb.skin([arm]))
    target = made(tmp_path, glb)

    moving, poses = lib.check_3d_model("part", directory=tmp_path, checks=["moving-parts", "poses"]).checks

    assert moving.lines[0].startswith("Arm")
    assert poses.skipped
    assert not (target / "checks" / "blender-request.json").exists()


def test_static_parts_are_the_mesh_objects_that_neither_move_nor_have_a_skin(tmp_path: Path) -> None:
    glb = Glb()
    glb.node("Body", mesh=glb.mesh(box()))
    glb.node("Trim", mesh=glb.mesh(box(size=(0.1, 0.1, 0.1))))
    lid = glb.node(
        "Lid", mesh=glb.mesh(box()), extras={"motion": {"kind": "hinge", "axis": [1, 0, 0], "range": [0, 90]}}
    )
    glb.node("Knob", mesh=glb.mesh(box()), parent=lid)
    bone = glb.node("Arm")
    glb.node("Tail", mesh=glb.mesh(box()), skin=glb.skin([bone]))
    made(tmp_path, glb)

    [found] = lib.check_3d_model("part", directory=tmp_path, checks=["static-parts"]).checks

    assert found.figures == {"static": 2, "moving": 2, "skinned": 1}
    assert found.summary.endswith("Body, Trim.")


def test_moving_parts_describe_each_motion_and_what_is_wrong_with_how_it_is_declared(tmp_path: Path) -> None:
    glb = Glb()
    glb.node("Box", mesh=glb.mesh(box()))
    # Turned a quarter about y and doubled, so the piston's -z is the model's -x, twice as far.
    mount = glb.node("Mount", rotation=QUARTER_TURN_ABOUT_Y, scale=(2.0, 2.0, 2.0))
    piston = {"kind": "slide", "axis": [0, 0, -1], "range": [0, 0.04]}
    glb.node("Piston", mesh=glb.mesh(box()), parent=mount, translation=(0.0, 1.0, 0.0), extras={"motion": piston})
    glb.node("Door", mesh=glb.mesh(box()), extras={"motion": {"kind": "hinge", "axis": [0, 1, 0]}})
    glb.node("Rod", mesh=glb.mesh(box()), extras={"motion": "Slides out to extend."})
    glb.node("Wheel", mesh=glb.mesh(box()), extras={"motion": json.dumps({"kind": "spin", "axis": [1, 0, 0]})})
    glb.node("Crate", mesh=glb.mesh(box()), extras={"motion": {"kind": "swap", "group": "cargo"}})
    glb.node("Sack", mesh=glb.mesh(box()), extras={"motion": {"kind": "swap", "group": "cargo"}})
    glb.node("Fin", mesh=glb.mesh(box()), extras={"motion": {"kind": "wiggle"}})
    target = made(tmp_path, glb)

    [found] = lib.check_3d_model("part", directory=tmp_path, checks=["moving-parts"]).checks

    assert found.figures == {"motions": 7, "not_well_formed": 3}
    described, (group, *touching) = found.lines[:7], found.lines[7:]
    assert [line.split()[0].removesuffix(":") for line in described] == [
        "Piston",
        "Door",
        "Rod",
        "Wheel",
        "Crate",
        "Sack",
        "Fin",
    ]
    piston, door, rod, wheel, _, _, fin = described
    # The axis as declared, in the parent's space, and the pivot in the model's.
    assert "(0.000, 0.000, -1.000)" in piston
    assert "(0.000, 2.000, 0.000)" in piston
    assert "range" in door
    assert "'Slides out to extend.'" in rod
    assert "(1.000, 0.000, 0.000)" in wheel
    assert "'wiggle'" in fin
    assert group.endswith("Crate, Sack.")
    assert [(line.split()[0], "Box" in line) for line in touching] == [("Piston", True), ("Wheel", True)]
    request = json.loads((target / "checks" / "blender-request.json").read_text(encoding="utf-8"))
    swept = {motion["node"]: motion for motion in request["motions"]}
    assert set(swept) == {"Piston", "Wheel", "Crate", "Sack"}
    assert swept["Piston"]["axis"] == pytest.approx([-1.0, 0.0, 0.0])
    assert swept["Piston"]["unit"] == pytest.approx(2.0)
    assert swept["Piston"]["pivot"] == pytest.approx([0.0, 2.0, 0.0])
    assert swept["Wheel"]["range"] == [0.0, 360.0]


def test_skeletons_report_their_bones_influences_and_unweighted_vertices(tmp_path: Path) -> None:
    glb = Glb()
    root = glb.node("Bone")
    arm = glb.node("Arm", parent=root)
    tail = box()
    tail.joints = [(0, 1, 0, 0)] * len(tail.positions)
    tail.weights = [(0.0, 0.0, 0.0, 0.0)] * 4 + [(0.5, 0.5, 0.0, 0.0)] * (len(tail.positions) - 4)
    glb.node("Tail", mesh=glb.mesh(tail), skin=glb.skin([root, arm]))
    made(tmp_path, glb)

    [found] = lib.check_3d_model("part", directory=tmp_path, checks=["skeleton"]).checks

    assert found.figures == {"skeletons": 1, "bones": 2}
    [line] = found.lines
    assert line.startswith("Skin 0")
    assert all(figure in line for figure in ("Tail", "0 vertices", "4 vertices", "Bone."))


def test_markers_are_empties_with_nothing_under_them_and_say_where_they_point(tmp_path: Path) -> None:
    glb = Glb()
    holder = glb.node("Holder")
    glb.node("Body", mesh=glb.mesh(box()), parent=holder)
    glb.node("Hitch", translation=(0.0, 0.5, 1.0), rotation=QUARTER_TURN_ABOUT_Y)
    glb.node("Empty.001")
    made(tmp_path, glb)

    [found] = lib.check_3d_model("part", directory=tmp_path, checks=["markers"]).checks

    assert found.figures == {"markers": 2}
    hitch, empty = found.lines
    assert hitch.startswith("Hitch")
    assert "(0.000, 0.500, 1.000)" in hitch
    assert "(1.000, 0.000, 0.000)" in hitch
    assert empty.startswith("Empty.001")
    assert "default name" in empty
    assert "default name" not in hitch


def test_the_color_checks_read_the_declared_palette_the_role_each_triangle_lands_on_and_what_glows(
    tmp_path: Path,
) -> None:
    glb = Glb()
    palette = glb.palette(
        [[(240, 160, 104), (200, 204, 206), (255, 176, 64)], [(60, 110, 70), (200, 204, 206), (120, 255, 120)]],
        glow=[[(0, 0, 0), (0, 0, 0), (255, 176, 64)], [(0, 0, 0), (0, 0, 0), (120, 255, 120)]],
        declared={"roles": ["body", "trim", "glow"], "schemes": ["day", "night"]},
    )
    # Each box's UVs at the center of its role's swatch in the first row, but the trim's, which is off its center.
    glb.node("Body", mesh=glb.mesh(box(material=palette, uv=(1 / 6, 0.25))))
    glb.node("Trim", mesh=glb.mesh(box(center=(0.0, 1.0, 0.0), material=palette, uv=(0.4, 0.25))))
    glb.node(
        "Lamp", mesh=glb.mesh(box(size=(0.1, 0.1, 0.1), center=(0.0, 1.0, 0.5), material=palette, uv=(5 / 6, 0.25)))
    )
    seam = Part([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1, 2)], material=palette)
    seam.uvs = [(1 / 6, 0.25), (0.5, 0.25), (0.5, 0.25)]
    glb.node("Seam", mesh=glb.mesh(seam))
    glb.node("Stand", mesh=glb.mesh(box(center=(0.0, -1.0, 0.0))))
    target = made(tmp_path, glb, screen_size=(40, 240))

    found, roles, emission, schemes = lib.check_3d_model("part", directory=tmp_path, checks=["color"]).checks

    assert found.figures["swatches"] == {
        "day": {"body": "#F0A068", "trim": "#C8CCCE", "glow": "#FFB040"},
        "night": {"body": "#3C6E46", "trim": "#C8CCCE", "glow": "#78FF78"},
    }
    assert "Drawn with the default material rather than the palette: Stand." in found.lines
    assert roles.figures == {
        "triangles": 36,
        "roles": {"body": 12, "trim": 12, "glow": 12},
        "rows": {"day": 36},
        "across_swatches": 1,
        "off_center": 12,
        "outside": 0,
        "without_uvs": 0,
    }
    assert roles.lines[0].startswith("body: 12 triangles")
    assert emission.figures["glowing"] == ["glow"]
    assert emission.lines == ["glow: #FFB040 in day, #78FF78 in night."]
    assert schemes.files == ["checks/schemes-40px.png", "checks/schemes-240px.png"]
    request = json.loads((target / "checks" / "blender-request.json").read_text(encoding="utf-8"))
    assert request["palette"] == {"size": [3, 2], "rows": 2, "schemes": ["day", "night"]}


def test_a_palette_no_material_declares_is_read_a_swatch_a_pixel_and_names_what_changed_since_the_last_check(
    tmp_path: Path,
) -> None:
    def colored(second: tuple[int, int, int]) -> Glb:
        glb = Glb()
        palette = glb.palette([[(10, 20, 30), second]], indexed=True)
        glb.node("Body", mesh=glb.mesh(box(material=palette, uv=(0.25, 0.5))))
        return glb

    target = made(tmp_path, colored((40, 50, 60)))
    before = lib.check_3d_model("part", directory=tmp_path, checks=["palette"]).checks[0]
    (target / "model.glb").write_bytes(colored((99, 50, 60)).bytes())
    after = lib.check_3d_model("part", directory=tmp_path, checks=["palette", "emission"]).checks

    assert before.figures["swatches"] == {"row 1": {"column 1": "#0A141E", "column 2": "#28323C"}}
    assert "No material declares" in before.summary
    assert "column 2 in row 1 changed from #28323C to #63323C since the last check." in after[0].lines
    assert after[1].skipped


def test_the_detail_checks_read_the_declared_texture_where_each_triangle_lands_on_it_and_the_colors_it_shades(
    tmp_path: Path,
) -> None:
    glb = Glb()
    palette = glb.palette(
        [[(240, 160, 104), (255, 176, 64)]],
        declared={"roles": ["body", "glow"], "schemes": ["day"]},
        detail="model-detail.png",
    )
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    # A square meter across half of a 16 pixel texture each way, and another across the same texels but half as many
    # of them up it as across.
    body = Part([(x, y, 0.0) for x, y in square], [(0, 1, 2), (0, 2, 3)], material=palette, uvs=[(0.25, 0.5)] * 4)
    body.second_uvs = [(x / 2, y / 2) for x, y in square]
    copy = Part([(x, y, 1.0) for x, y in square], [(0, 1, 2), (0, 2, 3)], material=palette, uvs=[(0.25, 0.5)] * 4)
    copy.second_uvs = [(x / 2, y / 4) for x, y in square]
    lamp = box(size=(0.1, 0.1, 0.1), center=(0.5, 0.5, 0.5), material=palette, uv=(0.75, 0.5))
    lamp.second_uvs = [(0.9, 0.9)] * len(lamp.positions)
    for name, part in (("Body", body), ("Copy", copy), ("Lamp", lamp)):
        glb.node(name, mesh=glb.mesh(part))
    glb.node("Stand", mesh=glb.mesh(box(size=(0.2, 0.2, 0.2), center=(0.5, 0.1, 0.5))))
    target = made(tmp_path, glb, screen_size=(40, 240))
    (target / "model-detail.png").write_bytes(gray_png([[128] * 16] * 16))

    texture, uvs, colors, renders = lib.check_3d_model("part", directory=tmp_path, checks=["detail"]).checks

    assert texture.summary == "model-detail.png, declared on Palette, is a 16 by 16 pixel 8 bit grayscale PNG."
    assert texture.lines == []
    assert uvs.figures == {
        "triangles": 4,
        "at_one_point": 12,
        "texels_per_meter": 8.0,
        "texels_per_meter_range": [4.0, 8.0],
        "texels_per_pixel": 0.03,
        "coverage": 0.375,
        "stretched": 2,
        "overlapping": 4,
        "outside": 0,
        "without_uvs": 0,
    }
    assert uvs.lines[:5] == [
        "Body: detail on 100% of its surface, at 8 texels a meter.",
        "Copy: detail on 100% of its surface, at 4 to 8 texels a meter.",
        "Lamp: detail on 0% of its surface; 12 triangles at one point, with none.",
        "Stand: 12 triangles drawn with a material that declares no detail.",
        "By role, the share with detail: body 100%, glow none.",
    ]
    assert colors.figures["roles"]["body"]["schemes"]["day"]["clipped"] == 0.1
    assert colors.summary.endswith("It clips body at full brightness in places.")
    assert renders.files == [
        "checks/detail-40px.png",
        "checks/detail-240px.png",
        "checks/detail-alone-240px.png",
        "checks/detail-texture.png",
    ]
    request = json.loads((target / "checks" / "blender-request.json").read_text(encoding="utf-8"))
    assert (request["detail"]["size"], request["detail"]["materials"]) == ([16, 16], ["Palette"])
    assert (request["detail"]["roles"], request["detail"]["points"]) == ([0, 0, 0, 0], [[14.4, 14.4]])


def test_a_detail_texture_is_read_only_once_declared_and_the_report_says_what_a_renderer_would_get_wrong(
    tmp_path: Path,
) -> None:
    glb = Glb()
    glb.node("Body", mesh=glb.mesh(box()))
    target = made(tmp_path, glb)
    (target / "model-detail.png").write_bytes(gray_png([[128] * 4] * 4))
    undeclared = lib.check_3d_model("part", directory=tmp_path, checks=["detail"]).checks
    declared = Glb()
    declared.node("Body", mesh=declared.mesh(box(material=declared.material("Plain", detail="detail.png"))))
    (target / "model.glb").write_bytes(declared.bytes())
    (target / "detail.png").write_bytes(png([[(128, 128, 128, 255)] * 3] * 3))

    texture, uvs, *_ = lib.check_3d_model("part", directory=tmp_path, checks=["detail"]).checks

    assert all(entry.skipped for entry in undeclared)
    assert undeclared[0].summary == f"{check.NO_DETAIL} model-detail.png beside model.glb is not read without one."
    assert texture.summary == "detail.png, declared on Plain, is a 3 by 3 pixel 8 bit RGBA PNG."
    assert texture.lines == [
        "It is stored as RGBA rather than grayscale, and a renderer reads the detail from one channel.",
        "Its size is not a power of two, which some engines resize or make no mipmaps for.",
        "It is named detail.png rather than model-detail.png, the name the app shows.",
    ]
    assert uvs.lines[-1] == "Body: 12 triangles drawn with the detail have no TEXCOORD_1 to land on it with."


def test_the_blender_checks_report_what_blender_found_and_the_renders_it_left(tmp_path: Path) -> None:
    glb = boxes()
    glb.node(
        "Hatch", mesh=glb.mesh(box(size=(0.2, 0.2, 0.2), center=(0.0, 0.5, 0.0))), extras={"motion": {"kind": "hide"}}
    )
    target = made(tmp_path, glb, screen_size=(40, 240), references=["references/concept.png", "references/notes.txt"])
    (target / "references").mkdir()
    (target / "references" / "concept.png").write_bytes(b"png")
    (target / "references" / "notes.txt").write_text("notes", encoding="utf-8")
    (target / "checks").mkdir()
    (target / "checks" / "pose-Old.png").write_bytes(b"png")

    report = lib.check_3d_model("part", directory=tmp_path, checks=["buried-faces", "on-screen", "poses"])

    buried, on_screen, poses = report.checks
    assert buried.figures == {"buried": 2, "triangles": 12}
    assert buried.lines == ["Box: 2 of 12, such as at (0.000, 0.250, 0.000), (0.000, 0.750, 0.000)"]
    assert on_screen.files == [
        "checks/on-screen-40px.png",
        "checks/on-screen-40px-sheet.png",
        "checks/on-screen-240px.png",
        "checks/on-screen-240px-sheet.png",
    ]
    assert poses.files == ["checks/pose-Hatch.png"]
    assert poses.lines == ["Hatch: at 0, 0.5, and 1 m, left to right."]
    assert not (target / "checks" / "pose-Old.png").exists()
    request = json.loads((target / "checks" / "blender-request.json").read_text(encoding="utf-8"))
    assert request["references"] == [str(target / "references" / "concept.png")]
    assert request["longest"] == 1.5


def test_when_blender_cannot_run_its_checks_say_why_and_the_rest_still_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BLENDER_FAILS", "1")
    glb = boxes()
    glb.node("Arm", mesh=glb.mesh(box()), extras={"motion": {"kind": "hinge", "axis": [1, 0, 0], "range": [0, 45]}})
    made(tmp_path, glb, screen_size=(40, 240))

    report = lib.check_3d_model("part", directory=tmp_path)

    for name in ("buried-faces", "on-screen", "poses"):
        assert result(report, name).skipped
        assert "the GPU went away" in result(report, name).summary
    moving = result(report, "moving-parts")
    assert not moving.skipped
    assert "the GPU went away" in moving.lines[-1]
    assert not result(report, "triangles").skipped


def test_describe_gives_the_report_as_text_for_an_agent(tmp_path: Path) -> None:
    target = made(tmp_path, boxes(), max_triangles=20, screen_size=(40, 240))

    text = check.describe(lib.check_3d_model("part", directory=tmp_path, checks=["triangles", "on-screen"]))

    assert f"The check of model.glb is kept in {target / 'checks' / 'report.json'}." in text
    assert "It is 1.000 by 1.500 by 1.000 m along glTF's x, y, and z" in text
    assert "- triangles: 24 triangles, 4 over the budget of 20.\n  - Body: 12\n  - Lid: 12" in text
    assert f"  - {target / 'checks/on-screen-40px.png'}" in text


def test_the_cli_prints_the_report_and_takes_checks_and_budgets(tmp_path: Path) -> None:
    made(tmp_path, boxes(), max_triangles=20, screen_size=(40, 240))

    printed = runner.invoke(
        app,
        [
            "check-3d-model",
            "--name",
            "part",
            "--directory",
            str(tmp_path),
            "--check",
            "triangles",
            "--check",
            "sub-pixel",
            "--max-triangles",
            "none",
            "--screen-size",
            "none",
        ],
    )

    assert printed.exit_code == 0, printed.output
    report = ModelCheck.model_validate_json(printed.stdout)
    assert [entry.name for entry in report.checks] == ["triangles", "sub-pixel"]
    assert report.checks[0].figures == {"triangles": 24, "budget": None}
    assert report.checks[1].skipped
