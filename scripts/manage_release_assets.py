#!/usr/bin/env python3
"""Verify a rolling release upload and remove superseded database assets."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
ASSET_PATTERN = re.compile(r"^direct-connections-(\d{8})\.db(?:\.sha256)?$")


class ReleaseError(RuntimeError):
    """Raised when a release upload is missing or inconsistent."""


def github_request(path: str, token: str, method: str = "GET") -> object | None:
    request = Request(
        f"{API_ROOT}{path}",
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "sparpreis.guru direct-connections publisher",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urlopen(request, timeout=60) as response:
            body = response.read()
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise ReleaseError(f"GitHub API returned HTTP {error.code}: {error_body}") from error

    return json.loads(body) if body else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--keep", type=int, required=True)
    parser.add_argument("--required-database", required=True)
    parser.add_argument("--expected-size", type=int, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()

    if args.keep < 2:
        raise ReleaseError("At least two database versions must be retained")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise ReleaseError("Invalid repository name")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.tag):
        raise ReleaseError("Invalid release tag")

    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ReleaseError("GH_TOKEN is required")

    release = github_request(
        f"/repos/{args.repository}/releases/tags/{quote(args.tag, safe='')}",
        token,
    )
    if not isinstance(release, dict):
        raise ReleaseError("Invalid release response")

    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleaseError("Release assets are missing")

    database_asset = next(
        (asset for asset in assets if asset.get("name") == args.required_database),
        None,
    )
    if not database_asset:
        raise ReleaseError(f"Uploaded database is missing: {args.required_database}")
    if database_asset.get("size") != args.expected_size:
        raise ReleaseError("Uploaded database size does not match the local file")

    remote_digest = database_asset.get("digest")
    expected_digest = f"sha256:{args.expected_sha256.lower()}"
    if remote_digest and remote_digest.lower() != expected_digest:
        raise ReleaseError("Uploaded database digest does not match the local file")

    checksum_name = f"{args.required_database}.sha256"
    if not any(asset.get("name") == checksum_name for asset in assets):
        raise ReleaseError(f"Uploaded checksum is missing: {checksum_name}")

    assets_by_version: dict[str, list[dict]] = defaultdict(list)
    for asset in assets:
        match = ASSET_PATTERN.fullmatch(str(asset.get("name", "")))
        if match:
            assets_by_version[match.group(1)].append(asset)

    versions = sorted(assets_by_version, reverse=True)
    if args.required_database not in {
        asset.get("name") for asset in assets_by_version.get(versions[0], [])
    }:
        raise ReleaseError("The uploaded database is not the newest release version")

    stale_versions = versions[args.keep :]
    for version in stale_versions:
        for asset in assets_by_version[version]:
            asset_id = asset.get("id")
            if not isinstance(asset_id, int):
                raise ReleaseError(f"Invalid asset id for {asset.get('name')}")
            github_request(
                f"/repos/{args.repository}/releases/assets/{asset_id}",
                token,
                method="DELETE",
            )
            print(f"Deleted stale asset: {asset.get('name')}")

    print(
        f"Verified {args.required_database}; retained versions: "
        f"{', '.join(versions[: args.keep])}"
    )


if __name__ == "__main__":
    main()
