#!/bin/bash
# vim: noet
#
# This script installs OneSSH on the target machines. It is a simple wrapper
# around the OneSSH installation script which is intended to be run on the
# local machine.
#
# Hard-coded:
# https://ubu.link/onesshup is a short link to the OneSSH installation script.
# You may manage this short link at: https://ubu.link/admin/manage

usage() {
	echo "Usage: $0 <TARGET_IP1> [TARGET_IP2 ... TARGET_IPN]"
	echo "  <TARGET_IP>    IP addresses of the target machines."
	echo "  -h, --help     Display this help message."
	echo "Environment variables:"
	echo "  TARGET_USER    The user to ssh into the target machines. "
	echo "                 Default is 'ubuntu'."
	echo "  RESERVE_USER   The lpuser to reserve for ssh into the target"
	echo "                 machines. Do no reservation if not set."
    exit 1
}

if [[ "$#" -eq 0 || "$1" == "-h" || "$1" == "--help" ]]; then
	usage
fi

TARGET_IPs=("$@")
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=30"
TARGET_USER=${TARGET_USER:-"ubuntu"}

ignore_ssh_warn() { grep -v "^Warning: Permanently added" >&2; }

in_target() {
	local target="$1"
	shift
	echo "Running on $target: \"$*\""
	# shellcheck disable=SC2086
	ssh $SSH_OPTS "$target" -- "$@" \
		2> >(ignore_ssh_warn)
}

for TARGET_IP in "${TARGET_IPs[@]}"; do
	if ! in_target "$TARGET_USER@$TARGET_IP" \
		"curl -fskSL https://ubu.link/onesshup | sudo ONESSH_IMPORT_KEYFILE=/etc/ssh/authorized_keys bash"
	then
		>&2 echo "Failed to install OneSSH on $TARGET_IP"
	else
		echo "OneSSH installed on $TARGET_IP successfully"
		if [ -n "$RESERVE_USER" ]; then
			if ! in_target "onechad@$TARGET_IP" checkin "$RESERVE_USER"; then
				>&2 echo "Failed to reserve $RESERVE_USER on $TARGET_IP"
			fi
		fi
	fi
done
