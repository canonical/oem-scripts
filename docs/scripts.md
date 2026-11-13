# Scripts

Scripts install to `/usr/bin` (except `config.sh`, see below). Most scripts print usage with `--help`. Scripts that talk to Launchpad need Launchpad credentials; see [Launchpad credentials](#launchpad-credentials).

## Launchpad credentials

- Python tools use `oem_scripts.LaunchpadLogin`. It reads `LAUNCHPAD_TOKEN` (format `oauth_token:oauth_token_secret:oauth_consumer_key`; `::` means anonymous access). It also reads the `[oem-scripts]` section of `~/.config/oem-scripts/config.ini` when `LAUNCHPAD_API` is set. Otherwise it starts the interactive launchpadlib login.
- `lp-api` and the shell tools built on it read the same `config.ini`, or `LAUNCHPAD_TOKEN`. If neither exists, `lp-api` prints a Launchpad URL to authorize a new token and stores the token in `config.ini`. `lp-api test` checks the login.
- `LAUNCHPAD_API` (default `https://api.launchpad.net/`) and `LAUNCHPAD_URL` (default `https://launchpad.net`) select another Launchpad instance.

## Launchpad

- `lp-api` (aliases: `jq-lp`, `launchpad-api`): shell wrapper for the Launchpad REST API with the subcommands `get`, `post`, `patch`, `download`, `test` and `debug`. Given a jq filter such as `.attachments_collection_link`, it reads JSON from stdin and fetches the URL that the filter selects (the old `jq-lp` usage).
  Example: `lp-api get people/+me ws.op==getArchiveSubscriptionURLs`
  Requires: `http` (httpie), `jq`, `lsb_release`, network, Launchpad credentials.
- `get-private-ppa`: prints the apt source URL and signing-key fingerprint of a PPA. For a private PPA it prints the subscription URL of the logged-in user. `-g` prints sources.list content, `-c` sets the series (default: current).
  Example: `get-private-ppa ppa:oem-archive/somerville`
  Requires: `lp-api`, `jq`, `lsb_release`, network, Launchpad credentials.
- `list-packages.sh`: lists the binary packages published in a PPA for one architecture and series (`-a`, `-c`; defaults: current).
  Example: `list-packages.sh ppa:oem-solutions-engineers/pc-enablement-tools -c jammy`
  Requires: `lp-api`, `jq`, `lsb_release`, network, Launchpad credentials.
- `lp-dl-attm`: downloads all attachments of a bug into the folder `lp<bug id>`.
  Example: `lp-dl-attm 1234567`
  Requires: `launchpad-api`, `jq`, `wget`, network, Launchpad credentials.
- `lp-bug`: Launchpad bug helper with the subcommands `copy`, `cleanup`, `cqa-verify`, `attach`, `sync`, `tag` and `update`.
  Example: `lp-bug attach --name=log.txt FILE_PATH BUG_ID`
  Requires: Launchpad credentials, network.
- `bug-bind.py`: binds private Launchpad bugs or Jira issues to a public bug (`-p`), or private bugs to a working private bug (`-m`, `-w`).
  Example: `bug-bind.py -p PUBLIC_BUG_ID PRIVATE_BUG_ID`
  Requires: Launchpad credentials, network. Jira issues need `jira_email` and `jira_token` in the `[private]` section of `~/.config/oem-scripts/config.ini`.
- `review-merge-proposal`: checks the votes on a Launchpad Git merge proposal. It exits with status 0 when all reviewers who are members of the target repository owner approved, or, with `--minimal-approved-number N`, when at least N of them approved. It exits with status 1 unless the proposal status is "Needs review".
  Example: `review-merge-proposal --minimal-approved-number 2 MERGE_PROPOSAL_LINK`
  Requires: Launchpad credentials, network.

## Meta-packages

- `oem-meta-packages`: manages OEM meta-packages with the subcommands `collect`, `list`, `subscribe`, `unsubscribe`, `staging-copy`, `create` and `update`. Common options: `--dry-run`, `--yes`, `--apt-dir`, `--series`.
  Example: `oem-meta-packages collect oem-qemu-meta --output oem-qemu-meta.json`
  Requires: Launchpad credentials in the `[oem-scripts]` section of `~/.config/oem-scripts/config.ini` (`launchpad-api get people/+me` creates it), network. Access to private archives needs a `[private]` section in the same file (see `oem-meta-packages --help`).
- `bootstrap-meta`: creates and updates the MIR and SRU Launchpad bugs of an OEM meta-package and updates its Git branch. Subcommands: `create-mir-bug`, `update-mir-bug`, `create-sru-bug`, `update-sru-bug`, `update-sru-git`. The `*-mir-*` subcommands are marked work in progress in the help text.
  Example: `bootstrap-meta create-sru-bug PLATFORM_JSON --kernel linux-generic-hwe-20.04`
  Requires: Launchpad credentials, `git`, the Jinja2 templates below, network.
- `mir-bug`: creates, checks, updates and collects the MIR bugs of OEM meta-packages (`create`, `check`, `update`, `collect`).
  Example: `mir-bug check PLATFORM_JSON`
  Requires: Launchpad credentials, network. `check` and `update` also use Git; `--skip` skips the Git part.
- `oem-metapackage-mir-check`: compares a meta-package source package with the `oem-qemu-meta` reference package to check the MIR exception in https://wiki.ubuntu.com/MIRTeam/Exceptions/OEM.
  Example: `oem-metapackage-mir-check PACKAGE.dsc`
  Requires: `pull-lp-source`, `debdiff` (ubuntu-dev-tools, devscripts), network.
- `pkg-oem-meta` (aliases: `pkg-somerville-meta`, `pkg-stella-meta`, `pkg-sutton-meta`): generates the source tree and Git repository of a Somerville (Dell), Stella (HP) or Sutton (Lenovo) platform meta-package. The program name selects the project; run under its own name, `pkg-oem-meta` exits with an error, so use an alias. One of `--private-bug` or `--jira` is required.
  Example: `pkg-sutton-meta -s noble -k linux-oem-24.04 -g bachman -p banaing --private-bug BUG_ID S08`
  Requires: `git`, `debcommit` (devscripts), `/etc/os-release`.
- `pkg-iot-meta`: generates an IoT platform meta-package.
  Example: `pkg-iot-meta -s noble --project-name=lyoncore`
  Requires: `git`, `debcommit` (devscripts).
- `pkg-list`: lists the packages needed for the given Debian packages. Options include `--recommends`, `--suggests`, `--exclude FILE`, `--source`, `--arch` and `--apt-dir`.
  Example: `pkg-list ubuntu-desktop --recommends > ubuntu-desktop.list`
  Requires: Python module `apt` (`apt_pkg`) and the apt indexes of the system or of `--apt-dir`.
- `check-ssid-duplicated.sh`: checks that subsystem IDs and a platform codename are not yet used by a branch in the `oem-<project>-projects-meta` repository (`stella`, `somerville` or `sutton`). Exit status: 0 no duplicate, 1 duplicate of the ID or the codename, 2 duplicate of both, 3 other error. `WORKING_DIR` sets the clone directory (default: a temporary directory).
  Example: `check-ssid-duplicated.sh --project=stella --pc=audino "886D,8870"`
  Requires: `git` with the `lp:` prefix and access to Launchpad Git.

## Image/ISO

- `oem-image-sbom`: generates a software bill of materials from one `.manifest` file, or compares two `.manifest`/`.sbom` files.
  Example: `oem-image-sbom IMAGE.manifest`, `oem-image-sbom OLD.manifest NEW.sbom`
  Requires: Python modules `apt` and `yaml`.
- `isoplatformlist.py`: loop-mounts an ISO and prints the supported platforms as YAML (package, component, modaliases). Knows the series `noble` and `resolute`.
  Example: `isoplatformlist.py ubuntu-image.iso`
  Requires: `sudo` for `mount` and `umount`, Python module `yaml`.

## CI/test

- `run-autopkgtest`: wrapper that builds an autopkgtest testbed (`lxc`, `qemu` or `vm-ubuntu-cloud`) and runs the autopkgtests of the current directory in it. See [Run autopkgtests locally](../CONTRIBUTING.md#run-autopkgtests-locally).
  Example: `run-autopkgtest qemu jammy`
  Requires: `autopkgtest`, QEMU or LXC, `sudo`, `LANG` in `/etc/default/locale`.
- `trigger_sanity_c3.py`: starts a sanity-test workflow through GitHub Actions on one or more C3 machines (`--cid`), or on all machines that are compatible with an ISO.
  Example: `trigger_sanity_c3.py --github-owner OWNER --github-repo REPO --github-workflow WORKFLOW.yaml --github-branch BRANCH --cid CID --iso-url URL --plan PLAN`
  Requires: `GITHUB_TOKEN` in the environment, `c3-v2-api.py` and its credentials, network.
- `c3-v2-api.py`: client for the C3 v2 REST API (`https://certification.canonical.com`) with `--get`, `--post`, `--put` and `--patch`.
  Example: `c3-v2-api.py --get /api/v2/machines/CID`
  Requires: network and a token. The token is `C3_V2_TOKEN`, or it comes from `c3_client_id` and `c3_client_secret` in the `[oem-scripts]` section of `~/.config/oem-scripts/config.ini`.

## Helpers

- `setup-apt-dir.sh`: creates an isolated apt directory for an Ubuntu series, with options such as `--arch`, `--ppa`, `--extra-repo`, `--enable-source` and `--proposed`. Without `--apt-dir` it generates a directory and prints it.
  Example: `setup-apt-dir.sh --codename jammy --apt-dir ./apt`
  Requires: `gpg`, access to keyserver.ubuntu.com, network. The series must be one of xenial, bionic, focal, hirsute, impish, jammy, mantic, noble or resolute. `--ppa` uses `get-private-ppa`.
- `local-repo`: downloads the `oem-<project>-<name>-doc` packages (or exact package names) of a PPA, checks their MD5 sums, builds a signed local apt repository and archives it as a tar.gz file.
  Example: `local-repo GPG_KEY_ID lenovo-oem/preload sutton jammy akando`
  Requires: `wget`, `gpg` with the signing key, `apt-ftparchive`, network.
- `umadison` (alias: `dmadison`): prints package versions from qa.debian.org madison. `umadison` queries Ubuntu, `dmadison` queries Debian.
  Example: `umadison PACKAGE`
  Requires: Python module `requests`, network.
- `config.sh`: not a command. It installs to `/usr/share/oem-scripts` and the shell tools source it to read and write `~/.config/oem-scripts/config.ini`.

## Templates and Python module

- `/usr/share/oem-scripts/oem-meta-package.mir.jinja2` and `oem-meta-package.sru.jinja2`: bug description templates that `bootstrap-meta` renders.
- `oem_scripts` (Python package): shared code. `LaunchpadLogin` handles the Launchpad login, `logging` sets up logging, and `gh_actions_api` is a small GitHub Actions client (it needs `GITHUB_TOKEN`; `python3 -m oem_scripts.gh_actions_api --help` shows its options).

## Not packaged

These files are in the repository but the .deb does not install them.

- `pkg-sutton-ug`: generates a Sutton user guide Debian package from `template_ug/` and a user-guide PDF (for example one attached to a Launchpad bug). Example: `./pkg-sutton-ug -j jellyfish-abishag.json -f xxx.pdf`.
- `template_ug/`: Debian packaging templates (control, changelog, rules, install, links, postrm, copyright) that `pkg-sutton-ug` fills in.
- `UserGuide.pdf`: user guide (PDF).
- `supported-lts-ubuntu-series.sh`: prints the supported Ubuntu LTS series (`-f` prints the full names). Requires `ubuntu-distro-info`.
