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
ASSET_PATTERN = re.compile(
    r"^direct-connections-(?:"
    r"(?P<timestamp>\d{8}T\d{6}Z)-(?P<digest>[0-9a-f]{12})"
    r"|(?P<legacy_date>\d{8})"
    r")\.db(?:\.sha256)?$"
)


class ReleaseError(RuntimeError):
    """Raised when a release upload is missing or inconsistent."""


def asset_build_id(asset_name: str) -> str | None:
    match = ASSET_PATTERN.fullmatch(asset_name)
    if not match:
        return None
    if match.group("timestamp") and match.group("digest"):
        return f"{match.group('timestamp')}-{match.group('digest')}"
    return f"{match.group('legacy_date')}T000000Z-legacy"


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
    if not isinstance(remote_digest, str):
        raise ReleaseError("Uploaded database digest is missing")
    if remote_digest.lower() != expected_digest:
        raise ReleaseError("Uploaded database digest does not match the local file")

    expected_prefix = args.expected_sha256[:12].lower()
    if not args.required_database.endswith(f"-{expected_prefix}.db"):
        raise ReleaseError("Database asset name does not contain the digest prefix")

    checksum_name = f"{args.required_database}.sha256"
    if not any(asset.get("name") == checksum_name for asset in assets):
        raise ReleaseError(f"Uploaded checksum is missing: {checksum_name}")

    assets_by_version: dict[str, list[dict]] = defaultdict(list)
    for asset in assets:
        build_id = asset_build_id(str(asset.get("name", "")))
        if build_id:
            assets_by_version[build_id].append(asset)

    versions = sorted(assets_by_version, reverse=True)
    if not versions:
        raise ReleaseError("Release contains no recognized database assets")
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
