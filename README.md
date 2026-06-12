# moodle-core-manifests

Pristine file manifests for every [Moodle](https://github.com/moodle/moodle)
core build from 4.1 onwards — tagged point releases **and** weekly `+` builds —
generated automatically from moodle.git by a scheduled GitHub Action.

These manifests let a tool determine whether a Moodle installation's core
files have been modified, by comparing on-disk file hashes against the
pristine tree for the **exact build** the site is running. They are consumed
by [Sentinel](https://github.com/davidpesce/moodle-local_sentinel) /
mdlsentinel.com, but anyone is welcome to use them.

## Layout

```
manifests/
  index.json                      # branches available
  MOODLE_405_STABLE/
    index.json                    # builds available for this branch
    2024100700.00.txt             # manifest for 4.5 (Build: 20241007)
    2024100711.04.txt             # manifest for 4.5.11+ (Build: 20260525)
  MOODLE_501_STABLE/
    ...
```

## Manifest format

One line per file in the build's tree, sorted by path (byte order):

```
<git-blob-sha1><TAB><path><LF>
```

The hash is the **git blob SHA-1** of the file content:

```
sha1("blob " + <size-in-bytes> + "\0" + <content>)
```

which is exactly what `git hash-object <file>` prints, and is cheap to
compute in any language without git installed. Known vector: the empty file
hashes to `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391`.

## Build identity — read this before consuming

- A build is identified by the **literal decimal string** value of
  `$version` in `version.php` (e.g. `2024100711.04`), *not* the integer
  part. Weekly builds bump only the decimals; truncating to an integer
  collapses different trees into one key.
- Manifests are generated at the first commit on each stable branch
  (first-parent order) that introduces a given `$version` value — the
  release/weekly bump commit that official moodle.org packages are built
  from. A git-deployed site that pulls *between* weekly bumps will differ
  from its build's manifest by whatever upstream commits it is ahead.
- **Moodle 5.1+** moved the webroot to `public/`; paths in 5.1+ manifests
  carry the `public/` prefix. Resolve paths against the repository root
  (`$CFG->root`), not the webroot (`$CFG->dirroot`).
- Dev/beta/rc builds are excluded — only stable releases and weekly `+`
  builds get manifests.

## Fetching

```
https://raw.githubusercontent.com/davidpesce/moodle-core-manifests/main/manifests/<BRANCH>/<version>.txt
```

A raw manifest is ~2.9 MB and gzip-compresses to ~0.9 MB on the wire.

## Regenerating locally

```bash
git clone --bare https://github.com/moodle/moodle.git moodle.git
python3 scripts/generate_manifests.py --repo moodle.git --out manifests
```

Requires Python 3.10+ and git ≥ 2.36. The script is idempotent — existing
manifest files are never rewritten, so a run only adds new builds.

## Status / support

This repository is generated and consumed by automation. It is published in
the open so that integrity comparisons against it are independently
reproducible: every manifest can be re-derived from the public moodle.git
history. No support is provided; issues and PRs may not receive a response.

## License

The manifests are derived facts (hashes and paths) about Moodle's source
tree; Moodle itself is GPLv3. The generator script is MIT licensed.
