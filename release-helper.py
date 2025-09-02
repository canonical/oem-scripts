#!/usr/bin/env python3
# Copyright 2021 Canonical
# Helper to release image

import sys
import argparse
import logging
import requests
import json

url = "http://f1.cctu.space:5000"
pdu_req = "/pdu?"
query_req = "/q?"

log = logging.getLogger("release-helper-logger")
log.setLevel(logging.INFO)
logging.basicConfig(
    format="%(asctime)s[%(levelname)s]: %(message)s", datefmt="%m/%d/%Y %I:%M:%S %p"
)


class Platform:
    tag = ""
    skus = []

    class SKU:
        name = ""
        mac = ""
        ip = ""
        fram = ""
        pdu_port = ""

        def __init__(self, name):
            self.name = name

    def __init__(self, tag):
        self.tag = tag

    def add_sku(self, name):
        self.skus.append(self.SKU(name))

    def update_name(self, name, new_name):
        for sku in self.skus:
            if name == sku.name:
                sku.name = new_name

    def update_mac(self, name, mac):
        for sku in self.skus:
            if name == sku.name:
                sku.mac = mac

    def update_ip(self, name, ip):
        for sku in self.skus:
            if name == sku.name:
                sku.ip = ip

    def update_fram(self, name, fram):
        for sku in self.skus:
            if name == sku.name:
                sku.fram = fram

    def update_pdu_port(self, name, pdu_port):
        for sku in self.skus:
            if name == sku.name:
                sku.pdu_port = pdu_port

    def list_skus(self):
        log.info("[%s]" % self.tag)
        for sku in self.skus:
            log.info("* %s:" % sku.name)
            log.info(" - mac: %s" % sku.mac)
            log.info(" - ip: %s" % sku.ip)
            log.info(" - fram: %s" % sku.fram)
            log.info(" - pdu_port: %s" % sku.pdu_port)


def check_connection(url):
    try:
        r = requests.head(url)
    except:
        log.error("Not able to connect to %s" % url)
        sys.exit("Please check the network connection, e.g. VPN.")
    log.debug("Connection checked.")
    return r.status_code


def get_platform_information_by_tag(url, platform_tag):
    p = Platform(platform_tag)

    # Get the SKUs of a platform
    log.debug("Get the SKUs for a tag.")
    tag_param = {"db": "tag"}
    try:
        r = requests.get(url + query_req, params=tag_param)
        jr = r.json()
        for key in jr:
            if jr[key] == platform_tag:
                p.add_sku(key)
    except:
        log.error(
            "Not able to get %s from %s%s with %s."
            % (platform_tag, url, query_req, tag_param)
        )
        sys.exit("Please make sure the arguments are expected.")

    # Get the IP and non-force-uppercase name of each SKU
    log.debug("Get the IP per SKU.")
    ipo_param = {"db": "ipo"}
    try:
        r = requests.get(url + query_req, params=ipo_param)
        jr = r.json()
        # FIXME: HIC shouldn't translate to uppercase
        # https://chat.canonical.com/canonical/pl/us55dkuarjgy3j1eko65jn49ny
        for sku in p.skus:
            cid = sku.name[-12:]
            for key in jr:
                if cid in key:
                    p.update_name(sku.name, key)
                    p.update_ip(sku.name, jr[key][0])
            if sku.ip == "":
                p.update_ip(sku.name, "OFFLINE")
    except:
        log.error(
            "Not able to get %s%s from %s%s with %s."
            % (platform_tag, url, query_req, ipo_param)
        )
        sys.exit("Please make sure the arguments are expected.")

    # Get the MAC address of each SKU
    log.debug("Get the MAC per SKU.")
    ipq_param = {"db": "ipq"}
    try:
        r = requests.get(url + query_req, params=ipq_param)
        jr = r.json()
        # FIXME: HIC shouldn't translate to uppercase
        # https://chat.canonical.com/canonical/pl/us55dkuarjgy3j1eko65jn49ny
        for sku in p.skus:
            cid = sku.name[-12:]
            for key in jr:
                if cid in jr[key]:
                    p.update_name(sku.name, jr[key])
                    p.update_mac(sku.name, key)
            if sku.ip == "":
                p.update_ip(sku.name, "offline")
    except:
        log.error(
            "Not able to get %s from %s%s with %s."
            % (platform_tag, url, query_req, ipq_param)
        )
        sys.exit("Please make sure the arguments are expected.")

    # Get the fram and PDU port number for each SKU
    log.debug("Get the physical location of each SKU.")
    for sku in p.skus:
        pdu_param = {"sku": sku.name}
        try:
            r = requests.get(url + pdu_req, params=pdu_param)
            fram = r.text.split(":")[0]
            pdu_port = r.text.split(":")[1]
            p.update_fram(sku.name, fram)
            p.update_pdu_port(sku.name, pdu_port)
        except:
            log.error(
                "Not able to get %s%s from %s%s with %s."
                % (platform_tag, url, pdu_req, pdu_param)
            )
            sys.exit("Please make sure the arguments are expected.")

    return p


def get_platform_information_by_cid(url, cid):
    sku = ""
    # Get the MAC address of each SKU
    log.debug("Get the SKU by cid %s." % cid)
    ipq_param = {"db": "ipq"}
    try:
        r = requests.get(url + query_req, params=ipq_param)
        jr = r.json()
        # FIXME: HIC shouldn't translate to uppercase
        # https://chat.canonical.com/canonical/pl/us55dkuarjgy3j1eko65jn49ny
        for key in jr:
            if cid in jr[key]:
                sku = jr[key]
                break
    except:
        log.error(
            "Not able to get %s from %s%s with %s."
            % (platform_tag, url, query_req, ipq_param)
        )
        sys.exit("Please make sure the arguments are expected.")

    if sku == None:
        sys.exit("Not found sku by cid %s." & cid)

    log.debug("Get the platform tag by sku %s." % sku)
    tag_param = {"db": "tag"}
    try:
        r = requests.get(url + query_req, params=tag_param)
        jr = r.json()
        # FIXME: HIC shouldn't translate to uppercase
        # https://chat.canonical.com/canonical/pl/us55dkuarjgy3j1eko65jn49ny
        # tag = jr[sku]
        for key in jr:
            if cid in key:
                tag = jr[key]
                break
    except:
        log.error(
            "Not able to get %s from %s%s with %s."
            % (platform_tag, url, query_req, tag_param)
        )
        sys.exit("Please make sure the arguments are expected.")

    if tag == None:
        sys.exit("Not platform tag by sku %s." & sku)

    p = get_platform_information_by_tag(url, tag)

    return p


if __name__ == "__main__":
    description = """A helper to manage the targeted SKUs of a specific
    platform."""
    help = """release-helper ${platform-tag} to manage the daily operation."""

    parser = argparse.ArgumentParser(
        description=description,
        epilog=help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-t", "--tag", help="The platform tag.")
    parser.add_argument("-c", "--cid", help="A CID of a platform.")
    parser.add_argument(
        "-v",
        "--verbose",
        help="Show more information for debugging.",
        action="store_true",
        default=False,
    )

    args = parser.parse_args()
    if args.tag == None and args.cid == None:
        parser.error("Must need to specify a platform tag or CID.")
    if args.verbose:
        log.setLevel(logging.DEBUG)

    check_connection(url)

    if args.tag:
        p = get_platform_information_by_tag(url, args.tag)
    elif args.cid:
        p = get_platform_information_by_cid(url, args.cid)

    p.list_skus()
