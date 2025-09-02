#!/usr/bin/env python3

import argparse
import os
import json
from asyncio.subprocess import PIPE
from pickle import TRUE
import shutil
import sys
import re
from subprocess import Popen


def modinfo2dict(module_path):
    module = {}
    module["id"] = module_path.split("/")[-1]
    if os.path.isfile(module_path):
        cmd = "modinfo" + " " + module_path
    elif os.path.isfile(module_path + ".zst"):
        cmd = "modinfo" + " " + module_path + ".zst"
    else:
        print(module_path + " " + "doesn't exist", file=sys.stderr)
        return
    output = Popen(cmd, stdout=PIPE, shell=TRUE).communicate()[0]
    modinfo = output.decode(encoding="utf-8")
    line_regex = r"(?P<item>\w+):\s+(?P<value>\S+)"
    line_pattern = re.compile(line_regex)
    alias = []
    firmware = []
    for line in modinfo.splitlines():
        m = line_pattern.match(line)
        if m:
            if m.group("item") == "filename" and m.group("value").startswith("/tmp"):
                i = m.group("value").index("/lib")
                module[m.group("item")] = m.group("value")[i:]
            elif m.group("item") == "alias":
                alias.append(m.group("value"))
            elif m.group("item") == "firmware":
                firmware.append(m.group("value"))
            elif m.group("item") == "signature":
                # do nothing
                continue
            else:
                module[m.group("item")] = m.group("value")

    if len(alias) > 0:
        module["alias"] = alias
    if len(firmware) > 0:
        module["firmware"] = firmware

    return module


def modules_filter(modules, type):
    type_modules = []
    for module in modules:
        if "alias" in module:
            alias_list = module["alias"]
            for a in alias_list:
                if a.startswith(type):
                    type_modules.append(module)
                    break

    return type_modules


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pci", action="store_true", help="filter pci devices")
    group.add_argument("--usb", action="store_true", help="filter usb devices")
    group.add_argument("--cpu", action="store_true", help="filter cpu devices")
    group.add_argument("--hid", action="store_true", help="filter hid devices")
    group.add_argument("--acpi", action="store_true", help="filter acpi devices")
    group.add_argument("--hdaudio", action="store_true", help="filter hdaudio devices")
    parser.add_argument("-d", "--deb", type=str, help="linux-modules debian file path")
    parser.add_argument(
        "-e", "--extra", type=str, help="linux-modules-extra debian file path"
    )
    args = parser.parse_args()

    if args.deb:
        if not os.path.exists(args.deb):
            print("cannot open the file: %s" % args.deb)
            return 1

        output = Popen("mktemp -d", stdout=PIPE, shell=TRUE).communicate()[0].strip()
        tmpdir = output.decode(encoding="utf-8")
        cmd = "dpkg -x" + " " + args.deb + " " + tmpdir
        output = Popen(cmd, stdout=PIPE, shell=TRUE).communicate()[0]
        if args.extra:
            if not os.path.exists(args.extra):
                print("cannot open the file: %s" % args.extra)
                return 1

            cmd = "dpkg -x" + " " + args.extra + " " + tmpdir
            output = Popen(cmd, stdout=PIPE, shell=TRUE).communicate()[0]
        prefix = tmpdir + "/lib/modules"
        cmd = "ls -1" + " " + prefix
        output = Popen(cmd, stdout=PIPE, shell=TRUE).communicate()[0].strip()
        kernel_version = output.decode(encoding="utf-8")
    else:
        output = Popen("uname -r", stdout=PIPE, shell=TRUE).communicate()[0].strip()
        prefix = "/lib/modules"
        kernel_version = output.decode(encoding="utf-8")

    modules_order_path = prefix + "/" + kernel_version + "/modules.order"
    f = open(modules_order_path, "r")
    lines = f.readlines()
    f.close()

    modules = []
    for line in lines:
        module_path = prefix + "/" + kernel_version + "/" + line.rstrip()
        modules.append(modinfo2dict(module_path))

    if args.deb:
        shutil.rmtree(tmpdir)

    if args.pci:
        pci_modules = modules_filter(modules, "pci")
        print(json.dumps(pci_modules, indent=4))
    elif args.usb:
        usb_modules = modules_filter(modules, "usb")
        print(json.dumps(usb_modules, indent=4))
    elif args.cpu:
        cpu_modules = modules_filter(modules, "cpu")
        print(json.dumps(cpu_modules, indent=4))
    elif args.hid:
        hid_modules = modules_filter(modules, "hid")
        print(json.dumps(hid_modules, indent=4))
    elif args.acpi:
        acpi_modules = modules_filter(modules, "acpi")
        print(json.dumps(acpi_modules, indent=4))
    elif args.hdaudio:
        hdaudio_modules = modules_filter(modules, "hdaudio")
        print(json.dumps(hdaudio_modules, indent=4))
    else:
        print(json.dumps(modules, indent=4))

    return 0


if __name__ == "__main__":
    sys.exit(main())
