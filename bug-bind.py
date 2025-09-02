#!/usr/bin/env python3
# Copyright 2018-2020 Canonical
# Helper script to `bind' private to public bug.

import argparse
import logging
import re
import os
import requests
from requests.auth import HTTPBasicAuth
import json

import lazr.restfulclient.resource
from oem_scripts.LaunchpadLogin import LaunchpadLogin
from configparser import ConfigParser

HWE_PUBLIC_PROJECT = "hwe-next"
OEM_PUBLIC_PROJECT = "oem-priority"

lp = None
log = logging.getLogger("bug-bind-logger")
log.setLevel(logging.DEBUG)
logging.basicConfig(
    format="%(levelname)s %(asctime)s - %(message)s", datefmt="%m/%d/%Y %I:%M:%S %p"
)


def get_jira_email_token():
    oem_scripts_config_ini = os.path.join(
        os.environ["HOME"], ".config/oem-scripts/config.ini"
    )
    oem_scripts_config = ConfigParser()
    oem_scripts_config.read(oem_scripts_config_ini)
    config = oem_scripts_config["private"]

    return config["jira_email"], config["jira_token"]


def issue_update_fields(
    email: str,
    token: str,
    issue_key: str,
    fields: dict,
):
    url = f"https://warthogs.atlassian.net/rest/api/2/issue/{issue_key}"
    auth = HTTPBasicAuth(email, token)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    payload = json.dumps(
        {
            "fields": fields,
        }
    )

    response = requests.request("PUT", url, data=payload, headers=headers, auth=auth)

    response.raise_for_status()


def link_bugs(public_bugnum, privates, ihv):
    assert public_bugnum.isdigit()
    login = LaunchpadLogin()
    lp = login.lp
    pub_bug = lp.bugs[public_bugnum]

    tag = "X-HWE-Bug: Bug #" + public_bugnum

    # Add X-HWE-Bug: tag to description.
    for priv in privates:
        if priv.isdigit():
            bug = lp.bugs[priv]

            if re.search(tag, bug.description) is None:
                # Add the referenced public bug to the private bug, if it's not in already.
                bug.description += "\n\n{}\n".format(tag)
                bug.lp_save()
            else:
                log.warning("Bug already linked to public bug " + tag)

            add_bug_tags(
                pub_bug,
                [
                    "originate-from-" + str(bug.id),
                    bug.bug_tasks_collection[0].bug_target_name,  # OEM codename
                    "oem-priority",
                ],
            )
        else:
            issue_key = priv
            jira_email, jira_token = get_jira_email_token()
            fields = {"customfield_10596": pub_bug.web_link}
            issue_update_fields(jira_email, jira_token, issue_key, fields)
            add_bug_tags(
                pub_bug,
                [
                    "jira-" + issue_key.lower(),
                    "oem-priority",
                ],
            )

        if ihv == "hwe":
            hwe_next = lp.projects[HWE_PUBLIC_PROJECT]
            sub_url = "%s~%s" % (lp._root_uri, "canonical-hwe-team")
            pub_bug.subscribe(person=sub_url)
            remote_bug_tag(pub_bug, "hwe-needs-public-bug")
        elif ihv == "swe":
            hwe_next = lp.projects[OEM_PUBLIC_PROJECT]
            sub_url = "%s~%s" % (lp._root_uri, "oem-solutions-engineers")
            pub_bug.subscribe(person=sub_url)
            remote_bug_tag(pub_bug, "swe-needs-public-bug")
        else:
            if lp.projects[ihv]:
                hwe_next = lp.projects[ihv]
                remote_bug_tag(pub_bug, "hwe-needs-public-bug")
            else:
                log.error("Project " + ihv + " not defined")

    add_bug_task(pub_bug, hwe_next)


def link_priv_bugs(main_bugnum, privates, ihv, watch):
    assert main_bugnum.isdigit()
    login = LaunchpadLogin()
    lp = login.lp
    main_bug = lp.bugs[main_bugnum]

    if watch:
        tag = "X-Watching-Bug: Bug #" + main_bugnum
    else:
        tag = "X-Working-Bug: Bug #" + main_bugnum

    # Add X-HWE-Bug: tag to description.
    for priv in privates:
        assert priv.isdigit()
        bug = lp.bugs[priv]

        if re.search(tag, bug.description) is None:
            # Add the referenced main bug to the private bug, if it's not in already.
            bug.description += "\n\n{}\n".format(tag)
            bug.lp_save()
        else:
            log.warning("Bug already linked to main bug " + tag)

        add_bug_tags(main_bug, ["originate-from-" + str(bug.id)])


def add_bug_task(bug, bug_task):
    assert type(bug_task) is lazr.restfulclient.resource.Entry

    # Check if already have the requested
    for i in bug.bug_tasks:
        if bug_task.name == i.bug_target_name:
            log.warning("Also-affects on {} already complete.".format(bug_task))
            return
    bug.addTask(target=bug_task)
    bug.lp_save()
    log.info("Also-affects on {} successful.".format(bug_task))


def remote_bug_tag(bug, tag):
    """remove tag from the bug"""
    if tag in bug.tags:
        tags = bug.tags
        tags.remove(tag)
        bug.tags = tags
        bug.lp_save()


def add_bug_tags(bug, tags):
    """add tags to the bug."""
    log.info("Add tags {} to bug {}".format(tags, bug.web_link))
    new_tags = []
    for tag_to_add in tags:
        if tag_to_add not in bug.tags:
            new_tags.append(tag_to_add)
    bug.tags = bug.tags + new_tags
    bug.lp_save()


if __name__ == "__main__":
    description = """bind private bugs or jira issues with pubilc bug
bud-bind.py -p public_bugnumber [private_bugnumber1|jira_issue1] [private_bugnumber2|jira_issue2]...
bug-bind.py -m private_bugnumber private_bugnumber1 private_bugnumer2...
bug-bind.py -w private_bugnumber private_bugnumber1 private_bugnumber2..."""
    help = """The expected live cycle of an oem-priority bug is:
    1. SWE/HWE manually tag hwe-need-public/swe-need-public on the existed private bug,
    2. SWE/HWE manually create a public bug.
    3. Use bug-bind to bind public and private bug."""

    parser = argparse.ArgumentParser(
        description=description,
        epilog=help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-m", "--main", help="The working private bug number")
    group.add_argument("-p", "--public", help="The working public bug number")
    group.add_argument("-w", "--watch", help="The watching private bug number")
    parser.add_argument(
        "-i",
        "--ihv",
        help='Launchpad project name for IHV\nExpecting "swe", "hwe", "intel", "amd", "nvidia", "lsi", "emulex"',
        default="swe",
    )
    parser.add_argument(
        "-v",
        "--vebose",
        help="shows debug messages",
        action="store_true",
        default=False,
    )
    # TODO
    # parser.add_argument('-c', '--clean', help='unlnk the bug between public and private', action='store_true', default=False)

    args, private_bugs = parser.parse_known_args()
    if args.vebose:
        log.setLevel(logging.DEBUG)
    if args.ihv not in ["swe", "hwe", "intel", "amd", "nvidia", "lsi", "emulex"]:
        raise Exception(
            'Expecting "swe", "hwe", "intel", "amd", "nvidia", "lsi", "emulex" for ihv'
        )
    if len(private_bugs) == 0:
        parser.error("must provide private bug numbers.")

    if args.main:
        link_priv_bugs(args.main, private_bugs, args.ihv, 0)
    elif args.watch:
        link_priv_bugs(args.watch, private_bugs, args.ihv, 1)
    else:
        link_bugs(args.public, private_bugs, args.ihv)
