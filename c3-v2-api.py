#! /usr/bin/env python3

import sys
import argparse
import os
import logging
from configparser import ConfigParser
import requests
from requests.auth import HTTPBasicAuth
import json

# Disable netrc to avoid requests using the credentials in netrc implicitly
os.environ["NETRC"] = "/dev/null"


def request_c3_access_token(client_id: str, secret: str):
    basic = HTTPBasicAuth(client_id, secret)
    data = {"grant_type": "client_credentials", "scope": "read write"}
    response = requests.post(
        "https://certification.canonical.com/oauth2/token/", auth=basic, data=data
    )
    return json.loads(response.text)["access_token"]


def get_c3_v2_api(token: str, api: str):
    host = "https://certification.canonical.com"
    auth = f"Bearer {token}"
    url = host + api
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": auth,
    }
    response = requests.request("GET", url, headers=headers)

    print(response.text)

    if response.status_code == 200:
        return 0

    return 1


def put_c3_v2_api(token: str, api: str, payload: str):
    host = "https://certification.canonical.com"
    auth = f"Bearer {token}"
    url = host + api
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": auth,
    }
    response = requests.request("PUT", url, headers=headers, data=payload)

    print(response.text)

    if response.status_code == 200:
        return 0

    return 1


def post_c3_v2_api(token: str, api: str, payload: str):
    host = "https://certification.canonical.com"
    auth = f"Bearer {token}"
    url = host + api
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": auth,
    }
    response = requests.request("POST", url, headers=headers, data=payload)

    print(response.text)

    if response.status_code == 200:
        return 0

    return 1


def patch_c3_v2_api(token: str, api: str, payload: str):
    host = "https://certification.canonical.com"
    auth = f"Bearer {token}"
    url = host + api
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": auth,
    }
    response = requests.request("PATCH", url, headers=headers, data=payload)

    print(response.text)

    if response.status_code == 200:
        return 0

    return 1


def main():
    parser = argparse.ArgumentParser(description="A tool to use C3 v2 REST API")
    op_group = parser.add_mutually_exclusive_group(required=True)
    op_group.add_argument(
        "--get", nargs="?", type=str, help="C3 HTTP GET for API endpoint"
    )
    op_group.add_argument(
        "--post",
        nargs="?",
        type=str,
        help="C3 HTTP POST for API endpoint",
    )
    op_group.add_argument(
        "--put",
        nargs="?",
        type=str,
        help="C3 HTTP PUT for API endpoint",
    )
    op_group.add_argument(
        "--patch",
        nargs="?",
        type=str,
        help="C3 HTTP PATCH for API endpoint",
    )
    parser.add_argument("payload", nargs="?", type=str, help="payload in json format")
    args = parser.parse_args()

    oem_scripts_config_ini = os.path.join(
        os.environ["HOME"], ".config/oem-scripts/config.ini"
    )

    access_token = os.environ.get("C3_V2_TOKEN")

    if os.path.exists(oem_scripts_config_ini):
        logging.info(
            "Obtain access token by cliend_id and client_secret in oem-scripts config"
        )
        oem_scripts_config = ConfigParser()
        oem_scripts_config.read(oem_scripts_config_ini)
        config = oem_scripts_config["oem-scripts"]

        if (
            "c3_client_id" not in config.keys()
            or "c3_client_secret" not in config.keys()
        ):
            logging.info(
                f"No c3_client_id and c3_client_secret configured in {oem_scripts_config_ini}"
            )
        elif not access_token:
            access_token = request_c3_access_token(
                config["c3_client_id"], config["c3_client_secret"]
            )

    if not access_token:
        logging.error("No access token for using C3 v2 API")
        return 1

    if args.get:
        return get_c3_v2_api(access_token, args.get)

    if args.put:
        if not args.payload:
            logging.error("Need payload for PUT operation")
            return 1

        return put_c3_v2_api(access_token, args.put, args.payload)

    if args.post:
        if not args.payload:
            logging.error("Need payload for POST operation")
            return 1

        return post_c3_v2_api(access_token, args.post, args.payload)

    if args.patch:
        if not args.payload:
            logging.error("Need payload for PATCH operation")
            return 1

        return patch_c3_v2_api(access_token, args.patch, args.payload)


if __name__ == "__main__":
    sys.exit(main())
