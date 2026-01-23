#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2021  Canonical Ltd.
# Author: Shih-Yuan Lee (FourDollars) <sylee@canonical.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os
import re
import sys
import subprocess

from logging import debug, info, error, critical
from tempfile import TemporaryDirectory

__version__ = "2.66"

ALLOWED_KERNEL_META_LIST = (
    "linux-oem-20.04d",
    "linux-oem-20.04c",
    "linux-oem-20.04b",
    "linux-oem-20.04",
    "linux-oem-22.04d",
    "linux-oem-22.04c",
    "linux-oem-22.04b",
    "linux-oem-22.04a",
    "linux-oem-22.04",
    "linux-oem-24.04d",
    "linux-oem-24.04c",
    "linux-oem-24.04b",
    "linux-oem-24.04a",
    "linux-oem-24.04",
    "linux-generic-hwe-20.04",
    "linux-generic-hwe-22.04",
    "linux-generic-hwe-24.04",
    "linux-generic",
)

TAG_LIST = ["oem-meta-packages", "oem-priority", f"oem-scripts-{__version__}"]


# Python 3.9 supports this.
def remove_prefix(s, prefix):
    return s[len(prefix) :] if s.startswith(prefix) else s


def yes_or_ask(yes: bool, message: str) -> bool:
    if yes:
        if sys.stdout.isatty():
            print(f"> \033[1;34m{message}\033[1;0m (y/n) y")
        else:
            print(f"> {message} (y/n) y")
        return True
    while True:
        if sys.stdout.isatty():
            res = input(f"> \033[1;34m{message}\033[1;0m (y/n) ").lower()
        else:
            res = input(f"> {message} (y/n) ").lower()
        if res not in {"y", "n"}:
            continue
        if res == "y":
            return True
        else:
            return False


def _run_command(
    command: list or tuple, returncode=(0,), env=None, silent=False
) -> (str, str, int):
    if not silent:
        debug("$ " + " ".join(command))
    proc = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )
    out, err = proc.communicate()

    if out:
        out = out.decode("utf-8").strip()
    else:
        out = ""

    if err:
        err = err.decode("utf-8").strip()
    else:
        err = ""

    if proc.returncode not in returncode:
        critical(f"return {proc.returncode}")
        if out:
            info(out)
        if err:
            critical(err)
        exit(1)

    if not silent:
        if out:
            debug(out)
        if err:
            debug(err)

    return (out, err, proc.returncode)


def _get_items_from_git(project: str, branch: str, pkg_name: str) -> tuple:
    git_command = (
        "git",
        "clone",
        "--depth",
        "1",
        "-b",
        branch,
        f"https://git.launchpad.net/~oem-solutions-engineers/pc-enablement/+git/oem-{project}-projects-meta",
        pkg_name,
    )
    with TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        _run_command(git_command)
        git_dir = os.path.join(tmpdir, pkg_name)

        if project == "somerville":
            prog = re.compile(
                r"alias pci:\*sv00001028sd0000([0-9A-F]{4})[^ ]* meta (.*)"
            )
        elif project == "stella":
            prog = re.compile(
                r"alias pci:\*sv0000103Csd0000([0-9A-F]{4})[^ ]* meta (.*)"
            )
        elif project == "sutton":
            prog = re.compile(
                r"alias dmi:\*bvn([0-9a-zA-Z]+):bvr([0-9a-zA-Z]{3})\*(:pvr(.*)\*)? meta (.*)"
            )
        else:
            critical("This should not happen.")
            exit(1)

        ids = []
        with open(os.path.join(git_dir, "debian", "modaliases"), "r") as modaliases:
            for line in modaliases:
                result = prog.match(line.strip())
                if result is None:
                    continue
                if result.group(result.lastindex) != pkg_name:
                    error(
                        "Something wrong in debian/modaliases. Please fix it manually first."
                    )
                    return False
                if result.lastindex == 5:
                    ids.append((result.group(1), result.group(2), result.group(4)))
                else:
                    ids.append(result.group(1))
        kernel_flavour = None
        kernel_meta = None
        market_name = None
        with open(os.path.join(git_dir, "debian", "control"), "r") as control:
            for line in control:
                if line.startswith("XB-Ubuntu-OEM-Kernel-Flavour:"):
                    kernel_flavour = line[
                        len("XB-Ubuntu-OEM-Kernel-Flavour:") :
                    ].strip()
                elif line.startswith("Depends:"):
                    for meta in ALLOWED_KERNEL_META_LIST:
                        if meta in line:
                            kernel_meta = meta
                            break
                elif line.startswith("Description:"):
                    if (
                        "Dell" in line or "HP" in line or "Lenovo" in line
                    ) and "(factory)" not in line:
                        prog = re.compile(
                            r"Description: hardware support for (Dell|HP|Lenovo) (.*)"
                        )
                        result = prog.match(line.strip())
                        market_name = result.group(2)
        return kernel_flavour, kernel_meta, market_name, ids
