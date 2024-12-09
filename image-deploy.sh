#!/bin/bash
# vim: ts=4:et

set -eo pipefail

# shellcheck source=config.sh
source config.sh || source /usr/share/oem-scripts/config.sh 2>/dev/null

usage() {
cat << EOF
Usage:
    $0 [OPTIONS] <TARGET_IP 1> <TARGET_IP 2> ...
Options:
    -h|--help        The manual of the script
    --iso            ISO file path to be deployed on the target
    --url            URL link to deploy the ISO from internet
    URL of PS5 Jenkins needs to config USER_ID and USER_TOKEN locally
    URL of oem-share Webdav needs to config rclone config locally
    -u|--user        The user of the target, default ubuntu
    -o|--timeout     The timeout for doing the deployment, default 3600 seconds
Environment variables:
    LAUNCHPAD_USER          The user of the launchpad, default \$USER
    RCLONE_CONFIG_PATH      The path of rclone config, default \$HOME/.config/rclone/rclone.conf
    CONFIG_REPO_REMOTE      The remote URL of the config repo, default
                            git+ssh://\$LAUNCHPAD_USER@git.launchpad.net/~oem-solutions-engineers/oem-dev-tools/+git/ubuntu-oem-image-builder
    CONFIG_REPO_BRANCH      The branch of the config repo, default main
    INTERACTIVE             The flag to enable the interactive mode, default false
Examples:
    $0 -u ubuntu --iso /home/ubuntu/Downloads/somerville-noble-hwe-20240501-65.iso 10.42.0.161
    $0 -u ubuntu --url https://people.canonical.com/~kchsieh/images/somerville-noble-hwe-20240501-65.iso 10.42.0.161
    $0 -u ubuntu --url https://oem-share.canonical.com/partners/somerville/share/releases/noble/hwe/20240515-86/somerville-noble-hwe-20240515-86.iso 10.102.182.186
    $0 -u ubuntu --url https://oem-share.canonical.com/share/somerville/releases/noble/hwe/20240515-86/somerville-noble-hwe-20240515-86.iso 10.102.182.186
EOF
}

if [ $# -lt 3 ]; then
    usage
    exit
fi

is_correct_sha256sum() {
    local filepath="$1"
    local sha256file="$2"
    local calculated_sha256
    local filename
    local expected_sha256

    # Check if providedfiles exist
    [ ! -f "$filepath" ] && echo "Error: File $filepath does not exist" && return 1
    [ ! -f "$sha256file" ] && echo "Error: SHA256 file $sha256file does not exist" && return 1

    # Get expected sha256
    filename="./$(basename "$filepath")"
    expected_sha256=$(grep "$filename" "$sha256file" | cut -d' ' -f1)
    if [ -z "$expected_sha256" ]; then
        echo "Error: Could not find SHA256 hash for $filename in $sha256file"
        return 1
    fi

    # Verify sha256 of the file
    calculated_sha256=$(sha256sum "$filepath" | cut -d' ' -f1)
    if [ "$calculated_sha256" = "$expected_sha256" ]; then
        echo "SHA256 verification successful for $filepath"
        return 0
    else
        echo "SHA256 verification failed for $filepath"
        echo "Expected: $expected_sha256"
        echo "Got:      $calculated_sha256"
        return 1
    fi
}

# Environment variables
LAUNCHPAD_USER=${LAUNCHPAD_USER:-"$USER"}
RCLONE_CONFIG_PATH=${RCLONE_CONFIG_PATH:-"$HOME/.config/rclone/rclone.conf"}
CONFIG_REPO_REMOTE="${CONFIG_REPO_REMOTE:-"git+ssh://$LAUNCHPAD_USER@git.launchpad.net/~oem-solutions-engineers/oem-dev-tools/+git/ubuntu-oem-image-builder"}"
CONFIG_REPO_BRANCH="${CONFIG_REPO_BRANCH:-"main"}"
INTERACTIVE=${INTERACTIVE:-false}

TARGET_USER="ubuntu"
TARGET_IPS=()
DEPLOYED_IPS=()
SKIPPED_IPS=()
ISO_PATH=
ISO=
STORE_PART=""
TIMEOUT=3600
CACHE_ROOT="$HOME/.cache/oem-scripts"
URL_CACHE_PATH="$CACHE_ROOT/images"
CONFIG_REPO_PATH="$CACHE_ROOT/ubuntu-oem-image-builder"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=30 "

if ! $INTERACTIVE; then
    SSH_OPTS="$SSH_OPTS -o PubkeyAuthentication=yes -o PasswordAuthentication=no"
fi

mkdir -p "$CACHE_ROOT"

OPTS="$(getopt -o u:o: --long iso:,user:,timeout:,url: -n 'image-deploy.sh' -- "$@")"
eval set -- "${OPTS}"
while :; do
    case "$1" in
        ('-h'|'--help')
            usage
            exit;;
        ('--url')
            if valid_oem_scripts_config_jenkins_addr; then
                JENKINS_IP=$(read_oem_scripts_config jenkins_addr)
                JENKINS_USER_ID=$(read_oem_scripts_config jenkins_user)
                JENKINS_USER_TOKEN=$(read_oem_scripts_config jenkins_token)
            fi
            ISO=$(basename "$2")
            ISO_PATH="$URL_CACHE_PATH/$ISO"
            ISO_SHA256_URL="${2%.iso}.sha256sum"
            if [ -f "$ISO_PATH" ] && [ -f "$ISO_PATH.sha256sum" ]; then
                echo "$ISO has been downloaded"
            else
                # Remove any partial downloads
                rm -f "$ISO_PATH" "$ISO_PATH.sha256sum"
                mkdir -p "$URL_CACHE_PATH" || true
                pushd "$URL_CACHE_PATH"
                if [ -n "$JENKINS_IP" ] && [[ "$2" =~ $JENKINS_IP ]]; then
                    if [ -n "$JENKINS_USER_ID" ] && [ -n "$JENKINS_USER_TOKEN" ]; then
                        curl -u "$JENKINS_USER_ID:$JENKINS_USER_TOKEN" -O "$2"
                        curl -u "$JENKINS_USER_ID:$JENKINS_USER_TOKEN" -O "$ISO_SHA256_URL"
                    else
                        echo "No USER ID and USER TOKEN configured for jenkins operations"
                    fi
                elif [[ "$2" =~ "oem-share" ]]; then
                    if [ -f "$RCLONE_CONFIG_PATH" ]; then
                        if [[ "$2" =~ "partners" ]]; then
                            PROJECT=$(echo "$2" | cut -d "/" -f 5)
                            FILEPATH=$(echo "$2" | sed "s/.*share\///g")
                            FILEPATH_SHA256=$(echo "$ISO_SHA256_URL" | sed "s/.*share\///g")
                        else
                            PROJECT=$(echo "$2" | cut -d "/" -f 5)
                            FILEPATH=$(echo "$2" | sed "s/.*$PROJECT\///g")
                            FILEPATH_SHA256=$(echo "$ISO_SHA256_URL" | sed "s/.*$PROJECT\///g")
                        fi
                        rclone --config "$RCLONE_CONFIG_PATH" sync "$PROJECT":"$FILEPATH" .
                        rclone --config "$RCLONE_CONFIG_PATH" sync "$PROJECT":"$FILEPATH_SHA256" .
                    else
                        echo "Can't find rclone config for webdav manipulation"
                    fi
                else
                    curl -O "$2"
                    if ! curl -f -O "$ISO_SHA256_URL"; then
                        # Expect that other URLs must also provide our SHA
                        echo "Failed to download SHA256SUM file from $ISO_SHA256_URL"
                        exit 1
                    fi
                fi
                popd
            fi

            if ! is_correct_sha256sum "$ISO_PATH" "$ISO_PATH.sha256sum"; then
                echo "SHA256 verification failed for $ISO_PATH"
                echo "Removing the .iso and .sha256sum files"
                rm -f "$ISO_PATH" "$ISO_PATH.sha256sum"
                echo "Please re-run the job to download again"
                exit 1
            fi
            shift 2;;
        ('--iso')
            ISO_PATH="$2"
            ISO=$(basename "$ISO_PATH")
            shift 2;;
        ('-u'|'--user')
            TARGET_USER="$2"
            shift 2;;
        ('-o'|'--timeout')
            TIMEOUT="$2"
            shift 2;;
        ('--') shift; break ;;
        (*) break ;;
    esac
done

if [ ! -f "$ISO_PATH" ]; then
    echo "No designated ISO file"
    exit
fi

ignore_ssh_warn() { grep -v "^Warning: Permanently added" >&2; }

in_target() {
    echo "Running on $TARGET_IP: \"$*\""
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "$TARGET_USER@$TARGET_IP" -- "$@" \
        2> >(ignore_ssh_warn)
}

to_target() {
    local dir recursive
    if [ -n "$2" ]; then
        # if $2 ends with /, then it's a directory
        if [[ "$2" == */ ]]; then
            dir="$2"
        else
            dir=$(dirname "$2")
        fi
        in_target mkdir -p "$dir"
    fi

    if [ -d "$1" ]; then
        recursive="-r"
    fi

    echo "Copying $1 to $TARGET_IP:$2"

    # shellcheck disable=SC2086
    scp $SSH_OPTS $recursive "$1" "$TARGET_USER@$TARGET_IP:$2" \
        2> >(ignore_ssh_warn)
}

read -ra TARGET_IPS <<< "$@"

# Download config repo to local
if [ ! -d "$CONFIG_REPO_PATH" ]; then
    git -C "$CACHE_ROOT" clone -b "$CONFIG_REPO_BRANCH" "$CONFIG_REPO_REMOTE"
else
    git -C "$CONFIG_REPO_PATH" pull
fi

store_partition() {
    while read -r name fstype mountpoint; do
        if [ "$fstype" = "ext4" ]; then
            if [ "$mountpoint" = "$HOME" ] || [ "$mountpoint" = "/" ]; then
                echo "/dev/$name"
                return
            fi
        fi
    done < <(lsblk -n -l -o NAME,FSTYPE,MOUNTPOINT)
    return 1
}

redeploy() {
    local iso store_part device efi_part reset_part reset_partuuid
    iso=$1

    store_part=$(store_partition)
    device="${store_part:0:-1}"
    efi_part="${device}1"
    reset_part="${device}2"
    reset_partuuid=$(lsblk -n -o PARTUUID "$reset_part")

    # Umount andd format the partitions
    for part in "$reset_part" "$efi_part"; do
        if [ -n "$(lsblk -n -o MOUNTPOINT "$part")" ]; then
            sudo umount "$part"
        fi
        sudo mkfs.vfat "$part"
    done

    mkdir -p iso
    mkdir -p reset
    sudo mount -o loop "$iso" iso || return 1
    sudo mount "$reset_part" reset || return 1

    echo "Sync ISO to the reset partition"
    sudo rsync -avP iso/ reset || true

    echo "Sync cloud-configs to the reset partition"
    sudo mkdir -p reset/cloud-configs
    sudo cp -r redeploy/cloud-configs/redeploy/ reset/cloud-configs/
    sudo cp -r redeploy/ssh-config/ reset/

    echo "Update the grub.cfg to boot from the reset partition"
    sudo cp redeploy/cloud-configs/grub/redeploy.cfg reset/boot/grub/grub.cfg
    sudo sed -i "s/RP_PARTUUID/${reset_partuuid}/" reset/boot/grub/grub.cfg

    echo "Reboot to start the redeploy process"
    sudo reboot
}

for TARGET_IP in "${TARGET_IPS[@]}"; do
    if STORE_PART=$(in_target "$(typeset -f store_partition); store_partition"); then
        echo "Store partition: $STORE_PART"
        DEPLOYED_IPS+=("$TARGET_IP")
    else
        echo "Erorr: Can't access the $TARGET_IP or find partition to store ISO on target. Skipping..."
        SKIPPED_IPS+=("$TARGET_IP")
        continue
    fi

    # Copy ISO to the target
    to_target "$ISO_PATH"

    # Copy cloud-config redeploy to the target
    to_target "$CONFIG_REPO_PATH/alloem-init/cloud-configs/redeploy/meta-data" redeploy/cloud-configs/redeploy/
    to_target "$CONFIG_REPO_PATH/alloem-init/cloud-configs/redeploy/user-data" redeploy/cloud-configs/redeploy/
    to_target "$CONFIG_REPO_PATH/alloem-init/cloud-configs/grub/redeploy.cfg" redeploy/cloud-configs/grub/redeploy.cfg

    # Copy ssh key from alloem-init injections to the target
    to_target "$CONFIG_REPO_PATH/injections/alloem-init/chroot/minimal.standard.live.hotfix.squashfs/etc/ssh" redeploy/ssh-config

    echo "Start deployment on $TARGET_IP"
    in_target "$(typeset -f store_partition redeploy); redeploy $ISO"
done

if [ ${#DEPLOYED_IPS[@]} -eq 0 ]; then
    echo "No devices were deployed. Please check the logs for errors."
    exit 1
fi

# Clear the known hosts
for TARGET_IP in "${TARGET_IPS[@]}"; do
    if [ -f "$HOME/.ssh/known_hosts" ]; then
        ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$TARGET_IP"
    fi
done

# Polling the targets
STARTED=("${DEPLOYED_IPS[@]}")
finished=0
startTime=$(date +%s)
echo "Verify deployment status on ${DEPLOYED_IPS[*]}"
while :; do
    sleep 180
    currentTime=$(date +%s)
    if [[ $((currentTime - startTime)) -gt $TIMEOUT ]]; then
        echo "Timeout is reached, deployment are not finished"
        break
    fi

    for TARGET_IP in "${STARTED[@]}"; do
        if in_target exit; then
            STARTED=("${STARTED[@]/$TARGET_IP}")
            finished=$((finished + 1))
            echo "$TARGET_IP is back online. Deployment is done for this device."
        fi
    done

    if [ $finished -eq ${#DEPLOYED_IPS[@]} ]; then
        echo "Deployment are done on ${DEPLOYED_IPS[*]}"
        if [ ${#SKIPPED_IPS[@]} -ne 0 ]; then
            echo "Deployment failed on ${SKIPPED_IPS[*]}. Please check."
        fi
        break
    fi
done
