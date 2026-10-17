Build a 3D model with Blender's Python API.

{request}

Work only in {directory}, and leave there:

- model.py: one script that builds the whole model from an empty scene and exports model.glb beside itself.
  Blender comes from PyPI: give model.py inline script metadata with requires-python "==3.13.*" and the
  dependency "{bpy}", run it with `uv run --script model.py`, and lock it with `uv lock --script model.py`.
  Give it an optional `--blend <path>` that also saves the built scene, for opening in Blender.
- model.glb: glTF binary, in meters, with its origin at the bottom center.
- renders/: PNGs of the exported model.glb from several angles.

Run every Python script through `uv run --script` with inline dependencies: `python` on PATH may be missing or a
stub. Change files with your file editing tools, not with scripts.

Build the model from named parts, each in its own function, with its dimensions as named constants at the top of
model.py, so a later request can change one part without touching the rest or losing quality.

After each build, render the exported model.glb, look at the renders, and fix what does not match the request.
{references}{existing}
Finish by saying what you built and anything you were unsure of.
