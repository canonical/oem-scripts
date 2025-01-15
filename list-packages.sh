#!/bin/bash

set -euo pipefail

OPTS="$(getopt -o a:c:h --long arch:,codename:,help -n 'list-packages.sh' -- "$@")"

ARCH=$(dpkg --print-architecture)
CODENAME=$(lsb_release -c -s)
PPA=
eval set -- "${OPTS}"

help() {
    cat <<ENDLINE
USAGE:

 This command will list published packages for the specified arch in a given PPA.

 $0 ppa:whatever/you-like [OPTIONS]

OPTIONS:

 -a | --arch
      If not specified, it will use the output of \`dpkg --print-architecture\`.
 -c | --codename ${CODENAME}
      If not specified, it will use the output of \`lsb_release -c -s\`.
ENDLINE
}

while :; do
    case "$1" in
        ('-h'|'--help')
            help
            exit ;;
        ('-a'|'--arch')
            ARCH="$2"
            shift 2;;
        ('-c'|'--codename')
            CODENAME="$2"
            shift 2;;
        ('--') shift; break ;;
        (*) break ;;
    esac
done

if [ "$#" -ne 1 ]; then
    help
    exit 1
fi

PPA="$1"

if [[ "$PPA" =~ ^ppa: ]]; then
    GROUP=$(echo "${PPA//[:\/]/ }" | awk '{print $2}')
    ARCHIVE=$(echo "${PPA//[:\/]/ }" | awk '{print $3}')
else
    echo "Please give a valid PPA name. '$PPA' is not a valid PPA name."
    help
    exit 1
fi

lp-api get "~$GROUP/+archive/ubuntu/$ARCHIVE" ws.op==getPublishedBinaries "distro_arch_series==https://api.launchpad.net/devel/ubuntu/$CODENAME/$ARCH" pocket==Release status==Published order_by_date==true > /tmp/payload.json
jq -r .entries.[].binary_package_name < /tmp/payload.json
link=$(jq -r .next_collection_link < /tmp/payload.json)
while [ "$link" != "null" ]; do
    lp-api get "$link" > /tmp/payload.json
    jq -r .entries.[].binary_package_name < /tmp/payload.json
    link=$(jq -r .next_collection_link < /tmp/payload.json)
done
