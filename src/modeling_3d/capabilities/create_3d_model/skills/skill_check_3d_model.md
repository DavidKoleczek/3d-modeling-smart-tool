`check-3d-model` measures a model's `model.glb` against its budgets and the modeling workflow,
and keeps the report in the model's `checks/report.json`, with its renders beside it. It is
informational: each check reports what it measured, nothing passes or fails, and whoever reads it
decides what is worth acting on. Run it after building a model and before finishing with it.

It reads the exported `model.glb`, not the scene that built it, and never writes `model.json` or
`runs.json`, so it can run while an agent works on the model. The buried faces, sweeps, and renders run Blender
through uv, which downloads bpy the first time, about 340 MB, and take a while.

```bash
# every check, against the model's own budgets
modeling-3d check-3d-model --name bear

# only the shape checks, or two by name
modeling-3d check-3d-model --name bear --check shape
modeling-3d check-3d-model --name bear --check triangles --check draw-calls

# against other budgets than the model's
modeling-3d check-3d-model --name bear --max-triangles 1500 --screen-size 40-240
```

```python
from modeling_3d.lib import check_3d_model

report = check_3d_model("bear", checks=["shape"])
[(check.name, check.summary) for check in report.checks]
```

## Checks

The shape of the model:

- `triangles`: the count, by mesh object, beside the triangle budget.
- `sub-pixel`: triangles that cover less than a pixel at the smallest size on screen, even face
  on, by mesh object.
- `round-parts`: how far smooth shaded curves stray from true ones at the largest size on screen,
  where their faces meet at an angle, with the radius and the sides of a whole turn of that curve
  and where it is. An edge is smooth when the faces on both sides share its normals, so smooth
  shading across a chamfer, as weighted normals give, reads as a curve too.
- `buried-faces`: triangles no ray from outside reaches, cast from a set of directions, with places
  they are. One seen only through a narrow opening, such as deep in a pipe, can count.
- `on-screen`: renders at the smallest and largest sizes on screen, and a sheet of each scaled up
  with its pixels kept, beside the model's image references.

How it is put together to move:

- `draw-calls`: one for each primitive of each mesh object, beside the draw call budget. A swap
  group counts once, as its costliest part, since one of its parts shows at a time.
- `static-parts`: the mesh objects that neither move nor have a skin.
- `moving-parts`: each declared motion, what is wrong with how it is declared, and anything its
  part touches through its range in places it does not at rest. Parts moved by bones are not
  swept.
- `skeleton`: bones, vertices with more than four influences, unweighted vertices, and default
  bone names.
- `markers`: empties with nothing under them, with where each is and where its +Z points.
- `poses`: each motion of an object rendered through its poses; motions on bones are not posed.

How it is colored, from the palette: the base color texture most triangles are drawn with, read as
a column for each role and a row for each scheme:

- `palette`: its size beside the roles and schemes declared, each swatch's color in each scheme,
  swatches that are not one color, roles of the same color, how it is sampled, parts drawn with
  another material, and the swatches that changed since the last check.
- `face-roles`: the role each triangle takes from the swatch its UVs land in: each role's
  triangles, its share of the surface, and the parts with it, then roles with none, triangles
  whose corners land in more than one swatch, off a swatch's center, or outside the palette, and
  the row they land in.
- `emission`: the roles the emission palette lights in each scheme, and how strongly.
- `schemes`: renders in each scheme, side by side, at the smallest and largest sizes on screen,
  lit flat so each face shows its swatch's color as the palette stores it.

How its surface is detailed, from the grayscale texture its material declares, which a renderer
multiplies the base color by twice, on the second set of texture coordinates:

- `detail-texture`: the file, its size, its bit depth and channels, and chunks that would make a
  loader treat it as color.
- `detail-uvs`: where each triangle lands on it: each part's share of the surface with detail and
  its texels a meter, each role's share, the texels a pixel at the largest size on screen and
  across a pixel at the smallest, triangles at one point with none, stretched triangles,
  triangles that share texels, and how much of the texture the islands cover.
- `detail-colors`: the detail's range under the faces that take it, and for each role, the
  darkest and lightest color it shades the role to in each scheme, and how much of it clips at
  full brightness.
- `detail-renders`: renders lit flat without the detail and with it at the smallest and largest
  sizes on screen, the detail alone on mid gray, and the texture with its islands outlined.

A check is skipped, saying why, when what it measures is absent: a budget, a motion, a skeleton, a
palette, a detail texture. `--check shape`, `--check rig`, `--check color`, and `--check detail`
run each group.

## Declaring motion

A part that moves is its own object, with its origin at its pivot, and declares its motion as a
`motion` custom property exported as glTF extras (`export_extras=True`). For a bone it goes on the
bone, not the pose bone. It is a JSON object, or text of one:

```python
drawer["motion"] = {"kind": "slide", "axis": [0, 0, -1], "range": [0, 0.04]}
lid["motion"] = {"kind": "hinge", "axis": [1, 0, 0], "range": [0, 110]}
wheel["motion"] = {"kind": "spin", "axis": [1, 0, 0]}
crate["motion"] = {"kind": "swap", "group": "cargo"}
antenna["motion"] = {"kind": "hide"}
```

A `slide` moves along its axis over its range in meters, a `hinge` turns about its axis through
its pivot over its range in degrees, and a `spin` turns all the way around. Parts of one `swap`
group show one at a time, and a `hide` part can be hidden on its own. Axes are in glTF's axes, in
the parent's space: y up and z toward the front, which is -Y in Blender. Blender exports custom
properties as written, without turning them into glTF's axes. Everything under a moving part moves
with it.

## Declaring a palette

The palette's material names its roles, its columns from the left, and its schemes, its rows from
the top, as a `palette` custom property exported as glTF extras. It is a JSON object, or text of
one:

```python
material["palette"] = {"roles": ["body", "trim", "dark", "glow"], "schemes": ["day", "night"]}
```

Each swatch is the image's width over the roles by its height over the schemes. The scheme the
model shows is the row its UVs land in, and the roles that glow are those the emission palette
lights, so neither is declared. Without a declaration, each pixel is a swatch, named by its place.

## Declaring a detail texture

glTF has no place for a detail texture, so it is saved beside `model.glb` as `model-detail.png`,
and each material it shades names it as a `detail` custom property exported as glTF extras:

```python
material["detail"] = "model-detail.png"
```

It is read from the second set of texture coordinates, `TEXCOORD_1`, as amounts from 0 to 1, and
a renderer multiplies the base color by twice it, so mid gray leaves a color as it is. A texture no
material declares is not read.

## Arguments

- `--name NAME`: the model to check.
- `--check CHECK`: a check above, or `shape`, `rig`, `color`, or `detail`, repeatable; every
  check when omitted.
- `--max-triangles N|none`, `--max-draw-calls N|none`, `--screen-size SMALLEST-LARGEST|none`:
  the budgets to measure against. Each one omitted is the model's own, from its last run, and
  `none` is no budget. The defaults a new model is given are never used.
- `--directory DIR`: where models are kept; `.modeling-3d` in the working directory when omitted.

## Result

The report as JSON on stdout, also kept in `checks/report.json`:

```json
{
  "name": "bear",
  "directory": "/work/.modeling-3d/bear",
  "checked": "2026-10-17T10:30:00Z",
  "glb_sha256": "9c1e...",
  "max_triangles": 2000,
  "max_draw_calls": 2,
  "screen_size": [40, 240],
  "dimensions": [0.42, 0.61, 0.95],
  "bounds": [[-0.21, 0.0, -0.475], [0.21, 0.61, 0.475]],
  "triangles": 1840,
  "mesh_objects": 1,
  "materials": 1,
  "checks": [
    {
      "name": "triangles",
      "summary": "1840 triangles, 160 under the budget of 2000.",
      "skipped": false,
      "lines": ["Bear: 1840"],
      "figures": {"triangles": 1840, "budget": 2000},
      "files": []
    }
  ]
}
```

`dimensions` and `bounds` are in meters along glTF's axes; the bounds show where the origin sits.
`glb_sha256` is of the `model.glb` checked, so a later reader can tell whether it changed since.
Each check's `files` are its renders, relative to the model's directory. Exits 0 once it has
checked, whatever it found, and 1 with what to do when it cannot check.
