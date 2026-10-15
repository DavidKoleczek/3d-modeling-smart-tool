`manifest` prints the tool's manifest as JSON on stdout: `smart_tool_format`, `name`,
`version`, `description`, `use_cases`, `platforms`, `requires`, and `body`, the Markdown the
tool's skill renders. It takes no arguments and needs no credentials, so it is how to verify
an install: JSON on stdout and exit 0 means the tool is installed and runnable.

```bash
modeling-3d manifest
```

```python
from modeling_3d.lib import load_manifest

manifest = load_manifest()
manifest.name, manifest.version, manifest.use_cases, manifest.body
```

## Failures

Exits 0 with the JSON. A failure the tool can name prints its message to stderr and exits 1;
a bad invocation exits 2. An empty result is never success.
