`manifest` prints the tool's manifest as JSON on stdout.
It is how to verify an install: JSON on stdout and exit 0 means the tool is installed and runnable.

```bash
modeling-3d manifest
```

```python
from modeling_3d.lib import load_manifest

manifest = load_manifest()
manifest.name, manifest.version, manifest.use_cases, manifest.body
```
