#!/usr/bin/env python3
"""Generate pristine file manifests for Moodle core builds.

For every build (tagged point release or weekly "+" build) on each supported
MOODLE_*_STABLE branch, emit a manifest file listing the git blob SHA-1 and
path of every file in that build's tree:

    manifests/<BRANCH>/<version>.txt      lines: "<blob-sha1>\t<path>\n"
    manifests/<BRANCH>/index.json         builds available for the branch
    manifests/index.json                  branches available

Builds are identified by the literal decimal string value of ``$version`` in
version.php (e.g. "2024100711.04") — the only build identifier a running
Moodle site can report. A build's manifest is generated from the FIRST
commit on the branch (first-parent order) whose version.php carries that
value, i.e. the release/weekly bump commit that official packages are built
from.

Notes:
- Moodle 5.1+ moved the webroot to public/; version.php lives at
  public/version.php and manifest paths carry the public/ prefix. Consumers
  must resolve paths relative to the repository root, not the webroot.
- The ``$branch`` value inside version.php is matched against the branch
  name, which filters out the pre-fork ancestry commits that a stable
  branch's first-parent history also contains.
- Requires git >= 2.36 (ls-tree --format).

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION_RE = re.compile(r"^\s*\$version\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;", re.M)
RELEASE_RE = re.compile(r"^\s*\$release\s*=\s*'([^']*)'", re.M)
BRANCH_RE = re.compile(r"^\s*\$branch\s*=\s*'([0-9]+)'", re.M)
BRANCH_NAME_RE = re.compile(r"^MOODLE_([0-9]+)_STABLE$")
# Stable releases and weekly "+" builds only — not dev/beta/rc, which are
# main-line ancestry or pre-release builds no production site runs.
RELEASE_OK_RE = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?\+? ")

MIN_BRANCH = 401  # Moodle 4.1


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def discover_branches(repo: Path, min_branch: int) -> dict[str, str]:
    """Return {branch_name: ref} for stable branches >= min_branch."""
    branches: dict[str, str] = {}
    for prefix in ("refs/remotes/origin/", "refs/heads/"):
        out = git(repo, "for-each-ref", prefix, "--format=%(refname)")
        for ref in out.splitlines():
            name = ref[len(prefix):]
            m = BRANCH_NAME_RE.match(name)
            if m and int(m.group(1)) >= min_branch and name not in branches:
                branches[name] = ref
        if branches:
            break
    return branches


def read_version_php(repo: Path, commit: str) -> str | None:
    for path in ("version.php", "public/version.php"):
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit}:{path}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
    return None


def enumerate_builds(repo: Path, ref: str, branch_digits: str) -> list[dict]:
    """All builds on a branch: first commit per distinct $version value."""
    log = git(
        repo, "log", "--first-parent", "--reverse", "--format=%H",
        ref, "--", "version.php", "public/version.php",
    )
    builds: list[dict] = []
    seen: set[str] = set()
    for commit in log.splitlines():
        content = read_version_php(repo, commit)
        if content is None:
            continue
        vm = VERSION_RE.search(content)
        bm = BRANCH_RE.search(content)
        if not vm or not bm or bm.group(1) != branch_digits:
            continue  # unparsable, or pre-fork ancestry of another branch
        version = vm.group(1)
        if version in seen:
            continue
        seen.add(version)
        rm = RELEASE_RE.search(content)
        release = rm.group(1) if rm else ""
        if not RELEASE_OK_RE.match(release):
            continue  # dev/beta/rc build
        builds.append({
            "version": version,
            "release": release,
            "commit": commit,
        })
    return builds


def write_manifest(repo: Path, commit: str, dest: Path) -> int:
    """Write the sorted '<blob-sha1>\t<path>' manifest. Returns line count."""
    out = git(
        repo, "ls-tree", "-r", "-z",
        "--format=%(objecttype)%x09%(objectname)%x09%(path)", commit,
    )
    lines = []
    for entry in out.split("\0"):
        if not entry:
            continue
        objtype, sha, path = entry.split("\t", 2)
        if objtype != "blob":
            continue  # ignore submodule gitlinks
        lines.append((path.encode(), f"{sha}\t{path}\n"))
    lines.sort(key=lambda item: item[0])
    tmp = dest.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.writelines(line for _, line in lines)
    tmp.replace(dest)
    return len(lines)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True,
                        help="path to a moodle.git clone (bare or worktree)")
    parser.add_argument("--out", default="manifests",
                        help="output directory (default: manifests)")
    parser.add_argument("--branches", nargs="*",
                        help="restrict to these branches (default: all "
                             f"MOODLE_*_STABLE >= {MIN_BRANCH})")
    parser.add_argument("--min-branch", type=int, default=MIN_BRANCH)
    parser.add_argument("--limit", type=int, default=0,
                        help="max NEW manifests per branch (0 = no limit; "
                             "for testing)")
    args = parser.parse_args()

    repo = Path(args.repo)
    outdir = Path(args.out)
    branches = discover_branches(repo, args.min_branch)
    if args.branches:
        missing = set(args.branches) - set(branches)
        if missing:
            print(f"unknown branches: {sorted(missing)}", file=sys.stderr)
            return 1
        branches = {name: branches[name] for name in args.branches}
    if not branches:
        print("no stable branches found", file=sys.stderr)
        return 1

    total_new = 0
    for name in sorted(branches):
        ref = branches[name]
        digits = BRANCH_NAME_RE.match(name).group(1)
        builds = enumerate_builds(repo, ref, digits)
        branch_dir = outdir / name
        branch_dir.mkdir(parents=True, exist_ok=True)
        new = 0
        for build in builds:
            dest = branch_dir / f"{build['version']}.txt"
            if dest.exists():
                continue
            if args.limit and new >= args.limit:
                break
            count = write_manifest(repo, build["commit"], dest)
            print(f"{name} {build['version']} ({build['release']}): "
                  f"{count} files")
            new += 1
        total_new += new
        index = {
            "branch": name,
            "updated_at": utcnow(),
            "builds": [
                {**b, "generated_at": utcnow()}
                for b in builds
                if (branch_dir / f"{b['version']}.txt").exists()
            ],
        }
        with open(branch_dir / "index.json", "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=1)
            fh.write("\n")

    top = {
        "updated_at": utcnow(),
        "branches": sorted(branches),
        "format": "<git-blob-sha1>\\t<path>\\n, sorted by path (byte order)",
    }
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "index.json", "w", encoding="utf-8") as fh:
        json.dump(top, fh, indent=1)
        fh.write("\n")
    print(f"done: {total_new} new manifest(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
