# Releasing

1. Move the `## Unreleased` notes in `CHANGELOG.md` under `## X.Y.Z - date`.
2. Set `version` in `pyproject.toml` and `CITATION.cff` to `X.Y.Z`, and
   `date-released` in `CITATION.cff` to the same date.
3. Merge to `main`, then tag it:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
   ```

`.github/workflows/release.yml` then refuses to continue unless the tag
matches `pyproject.toml`, runs the suite and `tti verify`, builds the sdist
and wheel, attaches them with a ledger snapshot and `SHA256SUMS`, and writes
the release notes from that version's CHANGELOG section.

## PyPI (one-time setup, optional)

The PyPI job is off by default. To turn it on:

1. On pypi.org, add a trusted publisher for project `time-to-index`:
   owner `abhid1234`, repository `time-to-index`, workflow `release.yml`,
   environment `pypi`.
2. In the repository settings, create an environment named `pypi`.
3. Add a repository variable `PUBLISH_PYPI` with the value `true`.

The next tag publishes to PyPI with no stored token.
