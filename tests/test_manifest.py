from importlib.metadata import version
import json
from pathlib import Path

import yaml

from modeling_3d.core.manifest import MANIFEST_PATH
from modeling_3d.lib import load_manifest

DISTRIBUTION_ROOT = Path(__file__).parents[1]


def test_manifest_matches_the_descriptor_and_package() -> None:
    manifest = load_manifest()
    descriptor = json.loads((DISTRIBUTION_ROOT / "smart-tool.json").read_text(encoding="utf-8"))

    assert DISTRIBUTION_ROOT / descriptor["manifest"] == MANIFEST_PATH
    assert manifest.name == descriptor["cli_argv"][0]
    assert manifest.version == version("modeling-3d")


def test_the_installable_skill_carries_the_package_version() -> None:
    _, frontmatter, _ = (
        (DISTRIBUTION_ROOT / "skills" / "modeling-3d" / "SKILL.md").read_text(encoding="utf-8").split("---", 2)
    )

    assert yaml.safe_load(frontmatter)["metadata"]["version"] == version("modeling-3d")
