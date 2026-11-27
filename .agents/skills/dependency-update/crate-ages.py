"""
List the crates in a Cargo.lock that are inside the cooldown, with the command that steps each one back.

Cargo has no cooldown of its own, so this reads when each locked version was published from the crates.io index.

Usage: uv run crate-ages.py <Cargo.lock> <days>
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tomllib
from typing import Any
import urllib.request

# The index cargo itself resolves from: one file per crate, with a line for each version. It is served from a CDN for
# reading in bulk, where the crates.io API allows one request a second.
INDEX = "https://index.crates.io"
USER_AGENT = "crate-age-check"
REQUESTS_AT_ONCE = 16


def index_path(name: str) -> str:
    """Returns where the index keeps a crate, which goes by the length of its name."""
    name = name.lower()
    if len(name) <= 2:
        return f"{len(name)}/{name}"
    if len(name) == 3:
        return f"3/{name[0]}/{name}"
    return f"{name[:2]}/{name[2:4]}/{name}"


def read_versions(name: str) -> list[dict[str, Any]]:
    """Returns every version of a crate, oldest first, as the index lists them."""
    request = urllib.request.Request(f"{INDEX}/{index_path(name)}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        return [json.loads(line) for line in response.read().decode("utf-8").splitlines() if line]


def age_in_days(version: dict[str, Any], now: datetime) -> int | None:
    """Returns how long ago a version was published, or None for one from before the index kept the time."""
    published = version.get("pubtime")
    return (now - datetime.fromisoformat(published)).days if published else None


def is_old_enough(version: dict[str, Any], now: datetime, days: int) -> bool:
    age = age_in_days(version, now)
    return age is None or age >= days


def release(version: str) -> tuple[int, ...] | None:
    """Returns a version's numbers for comparing, or None for a pre-release, which is never stepped back to."""
    numbers = version.split("+")[0]
    return None if "-" in numbers else tuple(int(number) for number in numbers.split("."))


def newest_before(listed: list[dict[str, Any]], locked: str, now: datetime, days: int) -> str | None:
    """Returns the newest release under the locked one that is old enough and still published."""
    ceiling = release(locked.split("-")[0])
    older: list[tuple[tuple[int, ...], str]] = []
    for version in listed:
        numbers = release(version["vers"])
        if version["yanked"] or not is_old_enough(version, now, days) or numbers is None or ceiling is None:
            continue
        if numbers < ceiling:
            older.append((numbers, version["vers"]))
    return max(older)[1] if older else None


def main() -> None:
    lock = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    days = int(sys.argv[2])
    now = datetime.now(UTC)
    packages = [package for package in lock["package"] if package.get("source", "").startswith("registry+")]
    names = sorted({package["name"] for package in packages})
    with ThreadPoolExecutor(max_workers=REQUESTS_AT_ONCE) as pool:
        versions = dict(zip(names, pool.map(read_versions, names), strict=True))
    young = 0
    for package in packages:
        name, locked = package["name"], package["version"]
        listed = versions[name]
        version = next(version for version in listed if version["vers"] == locked)
        if is_old_enough(version, now, days):
            continue
        young += 1
        older = newest_before(listed, locked, now, days)
        step_back = f"cargo update -p {name}@{locked} --precise {older}" if older else "no release is old enough"
        print(f"{name} {locked} is {age_in_days(version, now)} days old: {step_back}")
    print(f"{len(packages)} crates checked, {young} inside the {days} day cooldown.")


if __name__ == "__main__":
    main()
