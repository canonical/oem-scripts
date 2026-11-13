# Development and testing

To release, see [Release process](README.md#release-process).

## Checks in CI

`.github/workflows/validate.yml` runs on pull requests to `master` (not from forks), on pushes to `master`, and by manual dispatch (`workflow_dispatch`). It skips changes that only touch `.github/**`, `debian/changelog`, `debian/copyright` or Markdown files (`**.md`). The job:

1. Installs autopkgtest, LXC and the build dependencies from `debian/control` (`.github/actions/autopkgtest`, shared with the release workflow).
2. Checks that the runner knows the series `resolute`, and lets the `lxcbr0` bridge forward traffic.
3. Runs `./run-autopkgtest lxc resolute`. Exit status 0 and 2 (some tests skipped) pass.
4. Uploads the autopkgtest logs.
5. Builds the binary and source packages with `dpkg-buildpackage`. The build runs `tests/test_black`, `tests/test_flake8` and `tests/test_shellcheck` (`debian/rules`, `override_dh_auto_test`). It fails when the source package contains generated autopkgtest output.

You can run the same style checks directly: `./tests/test_black`, `./tests/test_flake8`, `./tests/test_shellcheck`.

## Run autopkgtests locally

The tests are in `debian/tests/`, listed in `debian/tests/control`. Tests that use the real Launchpad or the private archive need credentials and exit with status 77 (skipped) without them; the `-mock` tests need neither.

Run `run-autopkgtest` from the repository root:

```
./run-autopkgtest qemu jammy
./run-autopkgtest -t lp-api-mock qemu jammy
```

Usage: `run-autopkgtest [lxc|qemu|vm-ubuntu-cloud] [OPTIONS] SERIES...`. Options:

- `-t NAME`, `--test-name NAME`: run only that test.
- `-A`, `--architecture`: target architecture (default: host architecture).
- `-m`, `--mirror`: mirror (QEMU testbed only).
- `-s`, `--size`: QEMU image size (default `12G`).
- `-R`, `--rebuild-testbed`, `-F`, `--flush-cache`: rebuild the testbed.
- `-S`, `--shell-fail`: open a shell in the testbed after a failure.
- `-C`, `--credentials`: run the credential setup script `autopkgtest-<directory name>-auto` when one exists (`./`, `./bin/` or in `PATH`). It needs `~/.ssh/id_ecdsa` or `~/.ssh/id_rsa`.
- `-d`, `--debug`, `-B`, `--benchmark`.

The script uses `sudo`, creates the testbed image in `$HOME` (for example `~/ubuntu-jammy-amd64.img`) on first use, and writes logs to `autopkgtest-build-<builder>-<commit>-<series>-summary.log`, `...-complete.log` and a directory of the same name. Exit status 2 from autopkgtest means that some tests were skipped.
