#! /usr/bin/env python3

import os
import sys
import subprocess
import tempfile
import shutil
import argparse
import logging

series_codename_map = {"noble": "numbat"}
series_release_map = {"noble": "24.04"}

def mount_iso(iso_path, mount_point):
    subprocess.run(["sudo", "mount", "-o", "loop", iso_path, mount_point], check=True)


def unmount_iso(mount_point):
    subprocess.run(["sudo", "umount", mount_point], check=True)


def find_file(root_dir, filename):
    for dirpath, _, files in os.walk(root_dir):
        if filename in files:
            return os.path.join(dirpath, filename)
    return None


def get_description_line(file_path):
    with open(file_path, "r") as f:
        for line in f:
            lstripped = line.lstrip()
            if not lstripped.startswith("#") and lstripped.strip() != "":
                return lstripped.strip()
    return None


def parse_description(desc_line):
    parts = [p.strip() for p in desc_line.split("-")]
    return parts


def find_directory_with_packages(root_dir, series, project):
    target_dirname = f"canonical_{series}_{project}-meta"
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Check if directory name matches exactly
        if os.path.basename(dirpath) == target_dirname:
            packages_path = os.path.join(dirpath, "debs", "Packages")
            if os.path.isfile(packages_path):
                return packages_path
    return None


def parse_packages_file(packages_path):
    items = []
    current_item = {}
    with open(packages_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:  # Empty line: end of the current package
                if current_item:
                    items.append(current_item)
                    current_item = {}
            elif ": " in line:
                key, value = line.split(": ", 1)
                current_item[key] = value
            else:
                # Ignore any non-empty line that is not a colon+space key-value
                continue
        if current_item:
            items.append(current_item)
    return items


def main():
    parser = argparse.ArgumentParser(
        description="List supported platforms against the ISO file."
    )
    parser.add_argument("iso_path", help="Path to ISO file")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    if len(sys.argv) < 2:
        logging.error(f"Usage: {sys.argv[0]} <path-to-iso>")
        sys.exit(1)
    iso_path = args.iso_path
    filename = "ubuntu_dist_channel"
    temp_dir = tempfile.mkdtemp()
    mount_point = os.path.join(temp_dir, "mnt")
    os.mkdir(mount_point)
    try:
        mount_iso(iso_path, mount_point)
        target_file = find_file(mount_point, filename)
        if not target_file:
            logging.error(f"{filename} not found in ISO!")
            sys.exit(2)
        desc_line = get_description_line(target_file)
        if not desc_line:
            logging.error("No non-comment description line found in the file!")
            sys.exit(3)
        logging.debug(f"Description line: {desc_line}")
        info = parse_description(desc_line)
        logging.debug("Parsed info fields:")
        for idx, field in enumerate(info):
            logging.debug(f"  Field {idx}: {field}")
        # process as specified
        try:
            project = info[2]
            series = info[3]
            kernel = f"{info[4]}-{info[5]}"
        except IndexError:
            logging.error(
                "Not enough fields in description string to extract variables."
            )
            sys.exit(4)
        # find project meta sideload Packages
        if "hwe" in kernel:
            release = series_release_map[series]
            kernel_meta = f"linux-generic-hwe-{release}"
        else:
            kernel_meta = f"linux-{kernel}"
        packages_file = find_directory_with_packages(mount_point, series, project)
        if packages_file:
            logging.debug(f"Found Packages file at: {packages_file}")
            packages_list = parse_packages_file(packages_file)
            if not packages_list:
                logging.error(
                    "No valid package entries found in the Packages file. Exiting."
                )
                sys.exit(5)
            for item in packages_list:
                if "Depends" in item and kernel_meta in item["Depends"]:
                    parts = item["Package"].split("-")
                    platform_tag = f"{series_codename_map[series]}-{parts[2]}"
                    print(platform_tag)
        else:
            logging.error(
                f"No Packages file found under directory canonical_{series}_{project}-meta."
            )
            sys.exit(4)
    finally:
        try:
            unmount_iso(mount_point)
        except Exception as e:
            logging.error(f"Warning: failed to unmount: {e}")
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    main()
