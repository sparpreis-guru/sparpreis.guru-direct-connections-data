#!/usr/bin/env python3
"""Record a verified data publication in the README's managed status section."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path


START_MARKER = "<!-- publication-status:start -->"
END_MARKER = "<!-- publication-status:end -->"


def update_publication_status(
    readme: Path,
    published_at: str,
    station_count: int,
    connection_count: int,
    release_url: str,
) -> None:
    timestamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Publication timestamp must include a timezone")
    if station_count <= 0 or connection_count <= 0:
        raise ValueError("Publication counts must be positive")

    # Read bytes so edits preserve the surrounding text and its line endings.
    original = readme.read_bytes().decode("utf-8")
    if original.count(START_MARKER) != 1 or original.count(END_MARKER) != 1:
        raise ValueError("README must contain exactly one pair of publication status markers")
    before, _, remainder = original.partition(START_MARKER)
    if END_MARKER not in remainder:
        raise ValueError("Publication status markers are out of order")
    _, _, after = remainder.partition(END_MARKER)
    newline = "\r\n" if "\r\n" in original else "\n"
    published_utc = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    status = newline.join(
        [
            START_MARKER,
            f"- Last successful publication: **{published_utc}**",
            f"- Stations: **{station_count:,}**",
            f"- Direct connections: **{connection_count:,}**",
            f"- [Download the latest databases]({release_url})",
            END_MARKER,
        ]
    )
    updated = before + status + after
    if updated != original:
        readme.write_bytes(updated.encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("readme", type=Path)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--station-count", type=int, required=True)
    parser.add_argument("--connection-count", type=int, required=True)
    parser.add_argument("--release-url", required=True)
    args = parser.parse_args()
    update_publication_status(
        args.readme,
        args.published_at,
        args.station_count,
        args.connection_count,
        args.release_url,
    )


if __name__ == "__main__":
    main()
