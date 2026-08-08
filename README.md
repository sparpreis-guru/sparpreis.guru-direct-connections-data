# sparpreis.guru direct-connections data

This repository publishes the generated direct-connections database used by
[sparpreis.guru](https://github.com/sparpreis-guru/sparpreis.guru). The database is
distributed as release assets and is intentionally not committed to Git.

## Rolling release

The scheduled workflow maintains one release with the fixed tag
`direct-connections-data`. Each successful build uploads two versioned assets:

- `direct-connections-YYYYMMDD.db`
- `direct-connections-YYYYMMDD.db.sha256`

Only the three newest database versions and their checksums are retained. A new
database is built and validated before an older version is removed, so a failed
build or upload cannot remove the current fallback.

Clients discover the available assets through the stable GitHub API endpoint:

```text
https://api.github.com/repos/sparpreis-guru/sparpreis.guru-direct-connections-data/releases/tags/direct-connections-data
```

The rolling data release is the repository's latest release.

## Automation

The workflow runs daily at 07:00 UTC and can also be started manually. It checks
out the generator from `sparpreis-guru/sparpreis.guru`, downloads the current
GTFS.de feeds, builds the SQLite database, validates its complete compressed
payload, uploads the database and checksum, and prunes older assets.

The source repository can be changed without editing the workflow by defining
the repository variable `SOURCE_REPOSITORY`. `SOURCE_REF` can similarly select
a branch or tag. This is useful when the application repository moves to the
`sparpreis-guru` organization.

## Retention

The workflow keeps three complete versions by default. Change
`RETAIN_DATABASE_VERSIONS` in the workflow when a different rollback window is
needed.
