#!/bin/bash
# -*- coding: utf-8 -*-
# Copyright (C) 2020  Canonical Ltd.
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

export LANG=C

exec 2>&1
set -euo pipefail

APTDIR=
CODENAME=
DEBUG=
ARCH=
I386=
KEYS=()
LISTS=()
MIRROR=
NO_BASE=
NO_UPDATES=
NO_BACKPORTS=
NO_COMMUNITY=
HAS_SOURCE=
DPKG_STATUS=
OUTPUT=
PPA=()
PROPOSED=
OPTS="$(getopt -o c:dho:ps:m: --long apt-dir:,arch:,codename:,dpkg-status:,disable-base,disable-updates,disable-backports,disable-community,enable-source,debug,help,i386,output:,proposed,ppa:,mirror:,extra-repo:,extra-key: -n 'setup-apt-dir.sh' -- "$@")"
eval set -- "${OPTS}"
while :; do
    case "$1" in
        ('-h'|'--help')
            cat <<ENDLINE
USAGE:

 $0 [OPTIONS]

OPTIONS:

 -d | --debug
      Print more debug messages

 -h | --help
      Print help manual

 --arch amd64|arm64|armhf|...
      Specify target architecture. If not specified, defaults to current architecture reported from dpkg.

 --i386
      Enable i386 arch (only works with --arch amd64).

 -c | --codename focal
      If not specified, it will use the output of \`lsb_release -c -s\`.

 -s | --dpkg-status /var/lib/dpkg/status
      If not specified, it will use an empty status. If this is specified, it will copy the dpkg status into the temporary apt folder.

 --disable-base
      Disable the base channel.

 --disable-updates
      Disable -updates channel.

 --disable-backports
      Disable -backports channel.

 --disable-community
      Disable universe and multiverse components.

 --enable-source
      Enable deb-src in the source list.

 -m | --mirror mirror://mirrors.ubuntu.com/mirrors.txt
      If not specified, it will use http://archive.ubuntu.com/ubuntu by default.

 -o | --output
      Specify the filename to output the apt dir. If not specified, it will output in the last line.

 -p | --proposed
      Enable -proposed channel.

 --apt-dir APT-DIR
      If not specified, it will generate one.

 --extra-repo REPO_SPEC
      Provide an additional line (REPO_SPEC) to be appended to sources.list, e.g.:
         'deb <URL> <distrib> <components>'

 --extra-key APT_GPG_KEY
      Provide an additional GPG fingerprint to be imported and used by --extra-repo.

 --ppa ppa:whatever/you-like
      Just make sure you can access it by checking \`get-private-ppa ppa:whatever/you-like\`
ENDLINE
            exit ;;
        ('-d'|'--debug')
            DEBUG=1
            shift ;;
        ('--arch')
            ARCH="$2"
            shift 2;;
        ('--i386')
            I386=1
            shift;;
        ('-c'|'--codename')
            CODENAME="$2"
            shift 2;;
        ('-s'|'--dpkg-status')
            DPKG_STATUS="$2"
            shift 2;;
        ('--disable-base')
            NO_BASE=1
            shift;;
        ('--disable-updates')
            NO_UPDATES=1
            shift;;
        ('--disable-backports')
            NO_BACKPORTS=1
            shift;;
        ('--disable-community')
            NO_COMMUNITY=1
            shift;;
        ('--enable-source')
            HAS_SOURCE=1
            shift;;
        ('-o'|'--output')
            OUTPUT="$2"
            shift 2;;
        ('-p'|'--proposed')
            PROPOSED=1
            shift ;;
        ('--ppa')
            PPA+=("$2")
            shift 2;;
        ('-m'|'--mirror')
            MIRROR="$2"
            shift 2;;
        ('--apt-dir')
            APTDIR="$2"
            shift 2;;
        ('--extra-key')
            KEYS+=("$2")
            shift 2;;
        ('--extra-repo')
            LISTS+=("$2")
            shift 2;;
        ('--') shift; break ;;
        (*) break ;;
    esac
done

[ -n "$DEBUG" ] && set -x

if [ -z "$CODENAME" ]; then
    CODENAME="$(lsb_release -c -s)"
fi

if [ -z "$MIRROR" ]; then
    MIRROR="http://archive.ubuntu.com/ubuntu"
fi

if [ -n "$OUTPUT" ] && [ -e "$OUTPUT" ]; then
    echo "$OUTPUT already exists. Please specify other filename."
    exit 1
fi

if [ -z "$APTDIR" ]; then
    APTDIR="$(mktemp -d /tmp/apt.XXXXXXXXXX)"
    echo "APTDIR=$APTDIR"
fi
mkdir -p "$APTDIR"/var/lib/apt/lists "$APTDIR"/var/lib/dpkg "$APTDIR"/etc/apt/preferences.d "$APTDIR"/var/lib/dpkg
if [ -n "$DPKG_STATUS" ] && [ -f "$DPKG_STATUS" ]; then
    cp -v "$DPKG_STATUS" "$APTDIR"/var/lib/dpkg/status
else
    :> "$APTDIR"/var/lib/dpkg/status
fi

if [ "${#PPA[@]}" != "0" ]; then
    while read -r _ url key; do
        KEYS+=("$key")
        LISTS+=("deb [signed-by=$APTDIR/$key.pub] $url $CODENAME main")
        if [ -n "${HAS_SOURCE}" ]; then
            LISTS+=("deb-src [signed-by=$APTDIR/$key.pub] $url $CODENAME main")
        fi
    done< <(get-private-ppa "${PPA[@]}")
fi

case "${CODENAME}" in
    (xenial|bionic|focal)
        PUBKEY="790BC7277767219C42C86F933B4FE6ACC0B21F32"
        ;;
    (hirsute|impish|jammy|mantic|noble|resolute)
        PUBKEY="F6ECB3762474EDA9D21B7022871920D1991BC93C"
        ;;
    (*)
        echo "${CODENAME} is not supported by setup-apt-dir.sh yet."
        exit 1
        ;;
esac

: > "$APTDIR/etc/apt/sources.list"

# Set up architecture for apt sources
# Default to running system architecture if not specified
if [ -z "$ARCH" ]; then
    ARCH="$(dpkg --print-architecture)"
fi

# Validate --i386 only works with amd64
if [ -n "$I386" ] && [ "$ARCH" != "amd64" ]; then
    echo "error: --i386 can only be used with --arch amd64" >&2
    exit 1
fi

# Set up arch parameter for sources.list
if [ -z "$I386" ]; then
    ARCH_OPTION=" arch=$ARCH"
else
    ARCH_OPTION=" arch=amd64,i386"
fi

if [ -z "$NO_COMMUNITY" ]; then
    DIST=(main restricted universe multiverse)
else
    DIST=(main restricted)
fi

if [ -z "$NO_BASE" ]; then
    cat >> "$APTDIR/etc/apt/sources.list" <<ENDLINE
deb [signed-by=$APTDIR/$PUBKEY.pub$ARCH_OPTION] $MIRROR $CODENAME ${DIST[*]}
ENDLINE
    if [ -n "${HAS_SOURCE}" ]; then
        cat >> "$APTDIR/etc/apt/sources.list" <<ENDLINE
deb-src [signed-by=$APTDIR/$PUBKEY.pub$ARCH_OPTION] $MIRROR $CODENAME ${DIST[*]}
ENDLINE
    fi
fi

if [ -z "$NO_UPDATES" ]; then
    cat >> "$APTDIR/etc/apt/sources.list" <<ENDLINE
deb [signed-by=$APTDIR/$PUBKEY.pub$ARCH_OPTION] $MIRROR $CODENAME-updates ${DIST[*]}
ENDLINE
    if [ -n "${HAS_SOURCE}" ]; then
        cat >> "$APTDIR/etc/apt/sources.list" <<ENDLINE
deb-src [signed-by=$APTDIR/$PUBKEY.pub$ARCH_OPTION] $MIRROR $CODENAME-updates ${DIST[*]}
ENDLINE
    fi
fi

if [ -z "$NO_BACKPORTS" ]; then
    cat >> "$APTDIR/etc/apt/sources.list" <<ENDLINE
deb [signed-by=$APTDIR/$PUBKEY.pub$ARCH_OPTION] $MIRROR $CODENAME-backports ${DIST[*]}
ENDLINE
    if [ -n "${HAS_SOURCE}" ]; then
        cat >> "$APTDIR/etc/apt/sources.list" <<ENDLINE
deb-src [signed-by=$APTDIR/$PUBKEY.pub$ARCH_OPTION] $MIRROR $CODENAME-backports ${DIST[*]}
ENDLINE
    fi
fi

if [ -n "$PROPOSED" ]; then
    cat >> "$APTDIR/etc/apt/sources.list" <<ENDLINE
deb [signed-by=$APTDIR/$PUBKEY.pub$ARCH_OPTION] $MIRROR $CODENAME-proposed ${DIST[*]}
ENDLINE
    if [ -n "${HAS_SOURCE}" ]; then
        cat >> "$APTDIR/etc/apt/sources.list" <<ENDLINE
deb-src [signed-by=$APTDIR/$PUBKEY.pub$ARCH_OPTION] $MIRROR $CODENAME-proposed ${DIST[*]}
ENDLINE
    fi
fi

if ! gpg --fingerprint $PUBKEY >/dev/null 2>&1; then
    gpg --keyserver keyserver.ubuntu.com --recv-key $PUBKEY
fi
gpg --export --armor $PUBKEY > "$APTDIR/$PUBKEY.pub"

for PUBKEY in "${KEYS[@]}"; do
    if ! gpg --fingerprint "$PUBKEY" >/dev/null 2>&1; then
        gpg --keyserver keyserver.ubuntu.com --recv-key "$PUBKEY"
    fi
    gpg --export --armor "$PUBKEY" > "$APTDIR/$PUBKEY.pub"
done

# Process extra repos and inject signed-by if keys are provided
for i in "${!LISTS[@]}"; do
    list="${LISTS[$i]}"
    # If there's a corresponding key, inject signed-by into the repo line
    if [ -n "${KEYS[$i]:-}" ]; then
        key="${KEYS[$i]}"
        # Check if there are already options in brackets
        if [[ "$list" =~ ^(deb(-src)?[[:space:]]+)\[([^]]+)\][[:space:]]+ ]]; then
            # Check if the options next to deb/deb-src already has signed-by
            if [[ "${BASH_REMATCH[3]}" != *signed-by* ]]; then
                # Insert signed-by into existing options
                list=$(echo "$list" | sed -E "s#^(deb(-src)?[[:space:]]+)\[([^]]+)\]#\1[signed-by=$APTDIR\/$key.pub \3]#")
            fi
        else
            # No options, insert new bracket with signed-by after 'deb' or 'deb-src'
            list=$(echo "$list" | sed -E "s#^(deb(-src)?[[:space:]]+)#\1[signed-by=$APTDIR\/$key.pub] #")
        fi
    fi
    echo "$list" >> "$APTDIR/etc/apt/sources.list"
done

APTOPT=(-o "Dir=$APTDIR")
APTOPT+=(-o "Dir::State::status=$APTDIR/var/lib/dpkg/status")
APTOPT+=(-o "APT::Architecture=$ARCH")
echo "${APTOPT[@]}"

apt-get "${APTOPT[@]}" update

if [ -z "$OUTPUT" ]; then
    echo "$APTDIR"
else
    echo "$APTDIR" > "$OUTPUT"
fi
