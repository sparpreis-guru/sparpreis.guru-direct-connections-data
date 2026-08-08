#!/usr/bin/env python3
"""Validate a generated direct-connections SQLite database before publishing."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
from pathlib import Path


MIN_DATABASE_BYTES = 10 * 1024 * 1024
MAX_DATABASE_BYTES = 180 * 1024 * 1024
REQUIRED_TABLES = {"metadata", "main_data", "origin_details"}
VERSION_PATTERN = re.compile(r"^\d{8}$")


class ValidationError(RuntimeError):
    """Raised when the generated database is incomplete or inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def validate_database(database_path: Path) -> dict[str, str | int]:
    database_path = database_path.resolve()
    require(database_path.is_file(), f"Database does not exist: {database_path}")

    database_size = database_path.stat().st_size
    require(
        MIN_DATABASE_BYTES <= database_size <= MAX_DATABASE_BYTES,
        f"Unexpected database size: {database_size:,} bytes",
    )

    digest = hashlib.sha256()
    with database_path.open("rb") as database_file:
        for chunk in iter(lambda: database_file.read(1024 * 1024), b""):
            digest.update(chunk)

    connection = sqlite3.connect(
        f"file:{database_path.as_posix()}?mode=ro",
        uri=True,
    )

    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        require(quick_check == ("ok",), f"SQLite quick_check failed: {quick_check}")

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        require(
            REQUIRED_TABLES <= tables,
            f"Missing tables: {', '.join(sorted(REQUIRED_TABLES - tables))}",
        )

        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        require(metadata.get("schemaVersion") == "1", "Unsupported metadata schema")

        version = metadata.get("version", "")
        require(VERSION_PATTERN.fullmatch(version) is not None, f"Invalid version: {version}")
        require(bool(metadata.get("generatedAt")), "generatedAt metadata is missing")

        service_dates = json.loads(metadata.get("serviceDates", "[]"))
        require(isinstance(service_dates, list) and service_dates, "No service dates found")
        require(service_dates == sorted(set(service_dates)), "Service dates are not sorted and unique")

        main_row = connection.execute(
            "SELECT data_compressed FROM main_data WHERE id = 1"
        ).fetchone()
        require(main_row is not None, "Main overview payload is missing")
        overview = json.loads(gzip.decompress(main_row[0]))

        require(overview.get("schemaVersion") == 2, "Unsupported overview schema")
        require(overview.get("version") == version, "Overview and metadata versions differ")

        stations = overview.get("stations")
        edges = overview.get("edges")
        require(isinstance(stations, list) and len(stations) >= 1_000, "Too few stations")
        require(isinstance(edges, list) and len(edges) == len(stations), "Invalid overview edges")

        overview_edge_count = sum(len(station_edges) for station_edges in edges)
        require(overview_edge_count >= 10_000, "Too few overview connections")

        station_ids = {station["id"] for station in stations}
        detail_origin_count = 0
        detail_connection_count = 0
        detail_pattern_count = 0

        for origin_id, compressed_payload in connection.execute(
            "SELECT origin_id, data_compressed FROM origin_details"
        ):
            payload = json.loads(gzip.decompress(compressed_payload))
            require(payload.get("originId") == origin_id, f"Origin mismatch for {origin_id}")
            require(origin_id in station_ids, f"Unknown detail origin: {origin_id}")

            connections = payload.get("connections")
            require(isinstance(connections, dict) and connections, f"No connections for {origin_id}")
            require(
                set(connections) <= station_ids,
                f"Unknown detail destination for {origin_id}",
            )

            for patterns in connections.values():
                require(isinstance(patterns, list) and patterns, f"Empty pattern list for {origin_id}")
                detail_pattern_count += len(patterns)

            detail_origin_count += 1
            detail_connection_count += len(connections)

        require(detail_origin_count >= 1_000, "Too few detail origins")
        require(
            detail_connection_count == overview_edge_count,
            "Overview and detail connection counts differ",
        )
        require(detail_pattern_count >= 100_000, "Too few departure patterns")

        return {
            "version": version,
            "generated_at": metadata["generatedAt"],
            "sha256": digest.hexdigest(),
            "database_bytes": database_size,
            "station_count": len(stations),
            "connection_count": detail_connection_count,
            "pattern_count": detail_pattern_count,
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    result = validate_database(args.database)
    print(json.dumps(result, indent=2, sort_keys=True))

    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output_file:
            for key, value in result.items():
                output_file.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
