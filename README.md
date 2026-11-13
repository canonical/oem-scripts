# oem-scripts

oem-scripts is a collection of short command-line tools from Canonical OEM/commercial engineering. The tools create and maintain OEM meta-packages, work with Launchpad bugs, PPAs and merge proposals, inspect OEM images, and run package tests. The Debian source package is `oem-scripts`.

## Install

```
sudo add-apt-repository ppa:oem-solutions-engineers/pc-enablement-tools
sudo apt install oem-scripts
```

debian/control defines one binary package, `oem-scripts`.

## Documentation

- [Release process](#release-process): how to release a new version (below).
- [docs/scripts.md](docs/scripts.md): what each script does, examples, requirements, and Launchpad credentials.
- [CONTRIBUTING.md](CONTRIBUTING.md): CI checks and running autopkgtests locally.

## Release process

1. Add a `debian/changelog` entry. Its distribution must be the target series, not `UNRELEASED`.
2. Merge the change to `master`.
3. Push a tag that follows the [tagging rules](#tagging-rules).
4. `.github/workflows/build-and-release.yml` starts on the tag. It checks the release metadata, runs the autopkgtests as in `validate.yml`, builds the packages, signs the source upload, and uploads it with `dput` to `ppa:oem-solutions-engineers/pc-enablement-tools` for the changelog series only. If the PPA already has that version as Pending or Published, it skips the upload; if the version exists in another state, the job fails. It does not wait for the Launchpad build.
5. Check the build on https://launchpad.net/~oem-solutions-engineers/+archive/ubuntu/pc-enablement-tools/+packages.
6. Copy the package to other series manually on Launchpad (the "Copy packages" page of the PPA).

Do not push a new release tag before the workflow of the previous tag has finished. The upload jobs share one concurrency group, and GitHub keeps only one pending job.

## Tagging rules

- A tag is `X.Y` for a release (for example `2.73`) or `X.Y.Z` for a point release (for example `2.73.1`). The release workflow triggers only on these patterns.
- The tag must equal the `debian/changelog` version exactly.
- The tag must point to a commit on `master`. The workflow refuses other commits.
- Do not use Debian pre-release versions with `~` (for example `2.73~rc1`) or `_` test tags.

Reasons:

- `setup.py` passes the `debian/changelog` version to setuptools, and setuptools accepts only [PEP 440](https://peps.python.org/pep-0440/) versions. A `~` version raises `packaging.version.InvalidVersion` in `setup.py clean`, and the package build fails.
- Git does not allow `~` in tag names, so a `~` version cannot match its tag.
- `X.Y` and `X.Y.Z` are valid as PEP 440 and as Debian versions, and they sort the same way in both.
- The master-only rule makes sure that every upload comes from `master`.

Changing these rules needs a team discussion first.