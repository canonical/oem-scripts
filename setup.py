#! /usr/bin/env python3
"""Short OEM related scripts"""
#
# Copyright (C) 2020 Canonical Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from setuptools import setup, find_packages
from debian.changelog import Changelog

with open("debian/changelog") as f:
    cl = Changelog(f)
    version = str(cl.version)

setup(
    name="oem-scripts",
    version=version,
    description="Short OEM related scripts",
    long_description="""Short OEM related scripts can go here.
Also there is a meta package oem-dev-tools that installs all scripts""",
    platforms=["Linux"],
    license="GPLv3+1",
    author="Commercial Engineering",
    author_email="commercial-engineering@canonical.com",
    scripts=[
        "bootstrap-meta",
        "bug-bind.py",
        "lp-bug",
        "mir-bug",
        "oem-image-sbom",
        "oem-meta-packages",
        "pkg-iot-meta",
        "pkg-list",
        "pkg-oem-meta",
        "review-merge-proposal",
        "umadison",
    ],
    packages=find_packages(),
    test_suite="tests",
)
