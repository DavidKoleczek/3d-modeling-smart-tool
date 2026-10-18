Build a 3D model with Blender's Python API.

{request}

The model's directory is {directory}. Your working directory is where you were started, usually the project the
model is for. Explore whatever helps there, such as the project's docs, conventions, and the assets the model sits
beside. Write files only in the model's directory and run commands from it. Make an exception only where the work
needs one, and say what it was when you finish.

Leave in the model's directory:

- model.py: one script that builds the whole model from an empty scene and exports model.glb beside itself.
  Blender comes from PyPI: give model.py inline script metadata with requires-python "==3.13.*" and the
  dependency "{bpy}", run it with `uv run --script model.py`, and lock it with `uv lock --script model.py`.
  Give it an optional `--blend <path>` that also saves the built scene, for opening in Blender.
- model.glb: glTF binary, in meters, with its origin at the bottom center, facing glTF's front, +Z, which is -Y in
  Blender.
- renders/: PNGs of the exported model.glb from several angles.

Run every Python script through `uv run --script` with inline dependencies: `python` on PATH may be missing or a
stub. Change files with your file editing tools, not with scripts.

Build the model from named parts, each in its own function, with its dimensions as named constants at the top of
model.py, so a later request can change one part without touching the rest or losing quality.

Unless the request says otherwise, make the model ready to rig and animate:

- Give what bends, such as a body or a tail, a skeleton: an armature with clearly named bones, the mesh weighted to
  it with at most four bones a vertex, and enough geometry at each joint to bend cleanly. Build it in a neutral rest
  pose and export the skeleton in model.glb.
- Make what moves rigidly, such as a door, a lid, or a wheel, its own named object, with its origin at its pivot.
- Pose it the ways it would move and render those poses too, to check that it deforms and clears itself.

A model with nothing that would move stays a static mesh.

After each build, render the exported model.glb, look at the renders, and fix what does not match the request.
{references}{existing}
Finish by saying what you built and anything you were unsure of.
