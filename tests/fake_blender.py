"""Blender's half of the check, faked: what it would find, written where the request says, without running Blender.

Set FAKE_BLENDER_FAILS for one that fails the way a broken Blender does.
"""

import json
import os
from pathlib import Path
import sys

request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if os.environ.get("FAKE_BLENDER_FAILS"):
    print("Blender started.")
    print("Error: the GPU went away.", file=sys.stderr)
    raise SystemExit(1)
out = Path(request["out"])
found: dict = {"errors": {}}
if "buried-faces" in request["checks"]:
    found["buried"] = {"Box": {"buried": 2, "triangles": 12, "examples": [[0.0, 0.25, 0.0], [0.0, 0.75, 0.0]]}}
if "moving-parts" in request["checks"]:
    found["sweeps"] = {
        motion["node"]: {"values": motion["range"], "hits": [{"value": motion["range"][1], "touches": ["Box"]}]}
        for motion in request["motions"]
        if motion["kind"] in ("slide", "hinge", "spin")
    }
if "on-screen" in request["checks"]:
    found["on_screen"] = []
    for size in sorted(set(request["screen_size"])):
        for name in (f"on-screen-{size}px.png", f"on-screen-{size}px-sheet.png"):
            (out / name).write_bytes(b"png")
            found["on_screen"].append(name)
if "poses" in request["checks"]:
    found["poses"] = {}
    for motion in request["motions"]:
        (out / f"pose-{motion['node']}.png").write_bytes(b"png")
        found["poses"][motion["node"]] = {"file": f"pose-{motion['node']}.png", "shows": "at 0, 0.5, and 1 m"}
if "schemes" in request["checks"]:
    sizes = sorted(set(request["screen_size"])) if request["screen_size"] else [None]
    found["schemes"] = ["schemes.png" if size is None else f"schemes-{size}px.png" for size in sizes]
    for name in found["schemes"]:
        (out / name).write_bytes(b"png")
if "detail-colors" in request["checks"]:
    # Each role a tenth dark, most of it mid gray, and a tenth light.
    shades = [10 if value in (64, 200) else 80 if value == 128 else 0 for value in range(256)]
    roles = sorted(set(request["detail"]["roles"]))
    found["detail_colors"] = {
        "all": [count * len(roles) for count in shades],
        "roles": {str(role): shades for role in roles},
        "neutral": [len(request["detail"]["points"]) if value == 128 else 0 for value in range(256)],
    }
if "detail-renders" in request["checks"]:
    sizes = sorted(set(request["screen_size"])) if request["screen_size"] else [None]
    found["detail_renders"] = [
        *("detail.png" if size is None else f"detail-{size}px.png" for size in sizes),
        "detail-alone.png" if sizes[-1] is None else f"detail-alone-{sizes[-1]}px.png",
        "detail-texture.png",
    ]
    for name in found["detail_renders"]:
        (out / name).write_bytes(b"png")
Path(request["result"]).write_text(json.dumps(found), encoding="utf-8")
