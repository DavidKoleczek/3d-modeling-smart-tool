`add-blender-to-path` makes `blender` run an installed Blender from terminals opened afterward,
for opening a model's `.blend` or `model.glb` in Blender, or running Blender yourself. Building
models does not need it: `model.py` gets Blender from PyPI through uv.

Ask before running it: it changes the user's environment. On Windows it adds Blender's folder to
the user PATH in the registry. On macOS and Linux it links `~/.local/bin/blender` to Blender. It
never installs Blender; without one, it names where to download it.

```bash
# the newest Blender installed in the platform's usual place
modeling-3d add-blender-to-path

# a particular one
modeling-3d add-blender-to-path --blender-path "C:/Program Files/Blender Foundation/Blender 5.2"
```

```python
from modeling_3d.lib import add_blender_to_path

add_blender_to_path().message
```

When `blender` already runs a Blender, it changes nothing.

## Arguments

- `--blender-path PATH`: Blender's executable, or the folder that holds it. The newest found
  where the platform installs Blender when omitted.

## Result

JSON on stdout: `executable`, `changed` (whether anything was changed), and `message`, saying
what changed and that a new terminal is needed.
