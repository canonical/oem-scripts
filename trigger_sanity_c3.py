#!/usr/bin/env python3
"""Trigger infrastructure-checkbox-run job on Jenkins.

This script can:

1. Trigger job on a specific CID:
   - Specify the CID with --cid
   - Provide --iso-url to provision or --plan to test (or both)

   Example:
   ./trigger_sanity_c3.py --cid 202411-35996 --iso-url <url>
   ./trigger_sanity_c3.py --cid 202411-35996 --plan <plan>

2. Trigger job on all compatible CIDs:
   - Requires both --iso-url and --platform-info-dir, because it will search C3 for machines compatible with the ISO and kernel_meta in platform dir
   - (Optional) provide --plan to specify the test plan, e.g pc-sanity-smoke-test-24-04

   Example:
   ./trigger_sanity_c3.py --iso-url <url> --platform-info-dir <dir>
   ./trigger_sanity_c3.py --iso-url <url> --platform-info-dir <dir> --plan <plan>

Note: When other optional parameters are not provided, Jenkins job will use own defaults.
"""

import subprocess
import json
import os
import sys
import logging
import argparse
import configparser
import jenkins
import ast
from pathlib import Path
import time

OEM_SCRIPTS_CONFIG = Path.home() / ".config" / "oem-scripts" / "config.ini"
C3_V2_API_CLI = os.path.join(os.path.dirname(__file__), "c3-v2-api.py")
logger = logging.getLogger("trigger-sanity")

SSH_USER = "ubuntu"
SSH_TIMEOUT = "30"
SSH_OPTS = (
    "-o StrictHostKeyChecking=no "
    "-o UserKnownHostsFile=/dev/null "
    "-o ConnectTimeout=30 "
    "-o PubkeyAuthentication=yes "
    "-o PasswordAuthentication=no"
)


def read_config_value(config_file, key):
    """Read a value from the oem-scripts config file."""
    if not config_file.exists():
        return None

    config = configparser.ConfigParser()
    config.read(config_file)

    try:
        return config["private"][key]
    except (KeyError, configparser.Error):
        return None


def get_jenkins_connection():
    # First try environment variables
    jenkins_url = os.getenv("JENKINS_URL")
    jenkins_user = os.getenv("JENKINS_USER")
    jenkins_token = os.getenv("JENKINS_TOKEN")

    # If any credentials are missing, try reading from config file
    if not all([jenkins_url, jenkins_user, jenkins_token]):
        if not jenkins_url:
            jenkins_addr = read_config_value(OEM_SCRIPTS_CONFIG, "jenkins_addr")
            if jenkins_addr:
                jenkins_url = f"http://{jenkins_addr}"

        if not jenkins_user:
            jenkins_user = read_config_value(OEM_SCRIPTS_CONFIG, "jenkins_user")

        if not jenkins_token:
            jenkins_token = read_config_value(OEM_SCRIPTS_CONFIG, "jenkins_token")

    if not all([jenkins_url, jenkins_user, jenkins_token]):
        logger.error("Missing Jenkins credentials. Please either:")
        logger.error(
            "1. Set JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN environment variables, or"
        )
        logger.error("2. Configure in ~/.config/oem-scripts/config.ini:")
        logger.error("   [private]")
        logger.error("   jenkins_addr = your.jenkins.server")
        logger.error("   jenkins_user = your_username")
        logger.error("   jenkins_token = your_api_token")
        sys.exit(1)

    try:
        return jenkins.Jenkins(
            jenkins_url, username=jenkins_user, password=jenkins_token, timeout=60
        )
    except Exception as e:
        logger.error(f"Failed to connect to Jenkins: {e}")
        sys.exit(1)


def clean_json_string(s):
    """Convert Python literal string from subprocess output to valid JSON string."""
    s = s.strip()
    try:
        # First try direct JSON parsing
        return json.loads(s)
    except json.JSONDecodeError:
        # Evaluate as Python literal and then convert to JSON
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError) as e:
            raise json.JSONDecodeError(
                f"Failed to parse JSON or Python literal: {e}", s, 0
            )


def is_ssh_online(ip_address):
    """Check if a host is reachable and SSH-accessible."""
    response = subprocess.run(
        ["ping", "-c", "1", "-W", str(SSH_TIMEOUT), ip_address],
        stdout=subprocess.DEVNULL,
    )
    if response.returncode != 0:
        logger.warning(f"Ping {ip_address} has failed. Skip...")
        return False

    # Verify SSH connectivity
    subprocess.run(
        [
            "ssh-keygen",
            "-f",
            os.path.expanduser("~/.ssh/known_hosts"),
            "-R",
            ip_address,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        command = f"ssh {SSH_OPTS} {SSH_USER}@{ip_address} exit"
        result = subprocess.run(
            command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if result.returncode != 0:
            logger.error(f"SSH access to {ip_address} is not available. Skip...")
            return False
        return True
    except subprocess.SubprocessError as e:
        logger.error(f"Subprocess error: {e}")
        return False


def get_linked_labresources():
    """Get list of available CIDs from linked lab resources."""
    try:
        logger.info("Fetching lab resources from C3 API...")
        result = subprocess.run(
            [
                C3_V2_API_CLI,
                "--get",
                "/api/v2/linked-labresource/?datacentre__name__iexact=tel-l4",
            ],
            capture_output=True,
            text=True,
        )
        # Parse API response from stdout
        response_data = clean_json_string(result.stdout)
        if not response_data:
            logger.error("Failed to fetch lab resources")
            return []

        available_cids = []
        while True:
            # Extract CIDs that meet our criteria (role=DUT and has IP)
            results = response_data.get("results", {})
            for cid, data in results.items():
                ip_address = data.get("ip_address")
                if data.get("role") == "DUT" and ip_address:
                    if is_ssh_online(ip_address):
                        available_cids.append(cid)
                        logger.debug(f"Added CID: {cid} with IP: {ip_address}")

            # Check if there are more pages
            next_page = response_data.get("next")
            if not next_page:
                break

            # Remove host part from the URL and get next page
            next_page = next_page.replace("https://certification.canonical.com", "")
            logger.info(f"Fetching next page: {next_page}")

            result = subprocess.run(
                [C3_V2_API_CLI, "--get", next_page], capture_output=True, text=True
            )
            response_data = clean_json_string(result.stdout)
            if not response_data:
                logger.error("Failed to fetch next page of lab resources")
                break

        logger.info(
            f"Found {len(available_cids)} available CIDs with role=DUT and IP address"
        )
        return available_cids

    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        logger.error(f"Failed to get lab resources: {e}")
        return []


def is_supported_kernel_meta(platform_info_dir, project, launchpad_tag, kernel_meta):
    """Returns True if machine supports the specified kernel_meta version in platform info."""
    platform_info_file = Path(platform_info_dir) / project / f"{launchpad_tag}.json"
    if not platform_info_file.exists():
        logger.warning(f"No platform info found for {launchpad_tag}")
        return False

    try:
        with open(platform_info_file) as f:
            platform_info = json.load(f)

        # Compare kernel meta versions
        if platform_info.get("kernel_meta") == f"linux-oem-{kernel_meta}":
            return True
        elif (
            platform_info.get("kernel_meta") == f"linux-generic-hwe-{kernel_meta[:-1]}"
        ):
            # transitioned to generic kernel, e.g "linux-generic-hwe-24.04"
            return True

        return False

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error reading platform info for {launchpad_tag}: {e}")
        return False


def has_existing_queue(cid):
    """Returns True when machine has existing queues in testflinger."""
    try:
        logger.info(f"Checking queue status for CID: {cid}...")
        result = subprocess.run(
            [
                C3_V2_API_CLI,
                "--get",
                f"/api/v2/physicalmachinesview/{cid}",
            ],
            capture_output=True,
            text=True,
        )
        data = clean_json_string(result.stdout)
        if not data:
            logger.warning(f"Failed to fetch queue details for CID: {cid}")
            return False
        queues = data.get("queues")
        if queues:
            logger.debug(f"CID {cid} has existing queues: {queues}")
            return True

        return False

    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        logger.error(f"Failed to check queue status for CID {cid}: {e}")
        return False


def get_supported_cids(available_cids, iso_url, platform_info_dir):
    """Filter CIDs of machines that support the specified ISO."""
    supported_cids = []
    iso_file = iso_url.split("/")[
        -1
    ]  # "somerville-noble-oem-24.04b-next-20241128-125.iso"
    project = iso_file.split("-")[0].lower()  # "somerville"
    kernel_meta = iso_file.split("-")[3].lower()  # "24.04b"

    logger.info(
        f"Looking for machines for project: {project}, kernel_meta: {kernel_meta}"
    )
    logger.info(f"Checking {len(available_cids)} available CIDs: {available_cids}")

    for cid in available_cids:
        try:
            result = subprocess.run(
                [C3_V2_API_CLI, "--get", f"/api/v2/machines/{cid}"],
                capture_output=True,
                text=True,
            )
            data = clean_json_string(result.stdout)
            if not data:
                logger.warning(f"Failed to fetch details for CID: {cid}")
                continue

            projects = data.get("projects", [])
            arch_name = data.get("arch_name", "").lower()
            logger.debug(f"CID {cid}: arch={arch_name}, projects={projects}")

            is_project_match = False
            for p in projects:
                # API returns a list of projects
                if p.get("name").lower() == project:
                    is_project_match = True
                    break

            if arch_name == "x86_64" and is_project_match:
                tag = data.get("launchpad_tag")
                if tag:
                    logger.debug(
                        f"CID {cid}: checking kernel_meta support for tag {tag}"
                    )
                    if is_supported_kernel_meta(
                        platform_info_dir, project, tag, kernel_meta
                    ):
                        if not has_existing_queue(cid):
                            logger.info(
                                f"Warning: No Testfligner Queues for CID: {cid}. Skip."
                            )
                            continue
                        logger.info(f"Found supported CID: {cid} (tag: {tag})")
                        supported_cids.append(cid)
                else:
                    logger.debug(f"CID {cid}: no launchpad tag found")
            else:
                logger.debug(
                    f"CID {cid}: skipped (arch match: {arch_name=='x86_64'}, project match: {is_project_match})"
                )

        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            logger.error(f"Failed to get machine details: {e}")

    logger.info(f"Found {len(supported_cids)} supported CIDs: {supported_cids}")
    return supported_cids


def trigger_job(server, job_name, parameters, dry_run=False):
    """Trigger the Jenkins job with given parameters."""
    MAX_ATTEMPTS = 20
    SLEEP_TIME = 3
    try:
        if dry_run:
            logger.info(f"[DRY RUN] Would trigger job: {job_name} with parameters:")
            for key, value in parameters.items():
                logger.info(f"  {key}: {value}")
            return None
        else:
            # Keep the last build number before we trigger
            last_build_number = server.get_job_info(job_name)["lastBuild"]["number"]
            logger.debug(f"last_build_number: {last_build_number}")

            # Trigger job and get new build number
            server.build_job(job_name, parameters=parameters)
            for attempt in range(MAX_ATTEMPTS):
                current_build_number = server.get_job_info(job_name)["lastBuild"][
                    "number"
                ]
                logger.debug(f"current_build_number: {current_build_number}")
                if current_build_number > last_build_number:
                    logger.info(
                        f"Successfully triggered {job_name} build {current_build_number}"
                    )
                    return current_build_number
                time.sleep(SLEEP_TIME)

            # Build was not triggered
            logger.error(
                f"Failed to trigger {job_name} after build {last_build_number}"
            )
            return False
    except Exception as e:
        logger.error(f"Failed to trigger job {job_name}: {e}")
        return False


def verify_job_success(server, job_name, build_number, wait_timeout):
    """Poll the Jenkins job status until it completes and return True if successful."""
    SLEEP_TIME = 240
    MAX_ATTEMPTS = int(wait_timeout / SLEEP_TIME + 1)
    logger.debug(
        f"Set timeout after {MAX_ATTEMPTS} tries. Sleep after try: {SLEEP_TIME} sec"
    )

    for attempt in range(MAX_ATTEMPTS):
        try:
            # Fetch job info
            status = server.get_build_info(job_name, build_number).get("result")
            if status is None:
                logger.info(
                    f"Build {build_number} is still running... Sleep {SLEEP_TIME} sec..."
                )
                time.sleep(SLEEP_TIME)
            elif status == "SUCCESS":
                logger.info(f"Build {build_number} completed successfully.")
                return True
            else:
                logger.error(f"Build {build_number} failed with status: {status}")
                return False
        except Exception as e:
            logger.error(f"Error fetching job info on attempt {attempt}: {e}")
            time.sleep(SLEEP_TIME)

    logger.error("Max attempts reached. Unable to verify job status.")
    return False


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Trigger infrastructure-checkbox-run job"
    )
    parser.add_argument(
        "--platform-info-dir",
        help="Path to platform-info directory, e.g oem-hw-info/platform-info (required when --cid is not provided)",
    )
    parser.add_argument(
        "--iso-url", help="URL to ISO file (required when --cid is not provided)"
    )
    parser.add_argument(
        "--cid",
        help="Specific CID to trigger the job on. If not provided, we search C3 for all compatible machines",
    )
    parser.add_argument(
        "--job-name",
        default="infrastructure-checkbox-run",
        help="Jenkins job name (default: infrastructure-checkbox-run)",
    )
    parser.add_argument(
        "--plan",
        help="Target plan under com.canonical.certification name space",
    )
    parser.add_argument(
        "--exclude-task",
        help='Tasks to exclude (e.g., ".*audio/alsa_record_playback_automated")',
    )
    parser.add_argument("--additional-ppas", help="Additional PPAs to include")
    # TODO: verify the multiline strings, may need to use clean_json_string
    parser.add_argument(
        "--plainbox-conf", help="Content of plainbox.conf for checkbox to override"
    )
    parser.add_argument(
        "--machine-mst-json",
        help="Content of /var/tmp/checkbox-ng/machine-manifest.json to override",
    )
    parser.add_argument(
        "--clone-manifest", action="store_true", help="Whether to clone the manifest"
    )
    parser.add_argument(
        "--prefix-submission-tarball", help="Prefix for the submission tarball"
    )
    parser.add_argument(
        "--auto-create-bugs-assignee", help="Assignee for automatically created bugs"
    )
    parser.add_argument(
        "--auto-create-bugs-milestone", help="Milestone for automatically created bugs"
    )
    parser.add_argument(
        "--test-flinger-global-timeout",
        type=int,
        help="Global timeout for Test Flinger (in seconds)",
    )
    parser.add_argument(
        "--force-run-test-flinger",
        action="store_true",
        help="Force run Test Flinger even if the queue is not available",
    )
    parser.add_argument(
        "--send-email-notification", action="store_true", help="Send email notification"
    )
    parser.add_argument(
        "--upload-to-oem-share", action="store_true", help="Upload results to OEM share"
    )
    parser.add_argument(
        "--put-dell-embargo",
        action="store_true",
        help="Put Dell embargo on the results",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without triggering Jenkins jobs"
    )
    parser.add_argument(
        "--wait-success",
        action="store_true",
        help="Wait for the job to succeed after trigger (single CID only)",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=3600,
        help="Timeout period with --wait-success in seconds (Default: 3600 seconds)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Validate arguments
    if not args.cid:
        # Run on all compatible machines
        if not args.iso_url or not args.platform_info_dir:
            parser.error(
                "Both --iso-url and --platform-info-dir are required when --cid is not provided"
            )
    elif not args.iso_url and not args.plan:
        # Run on specific CID
        parser.error(
            "At least one of --iso-url or --plan must be provided when using --cid"
        )

    return args


def main():
    args = parse_arguments()

    # Set up logging based on debug flag
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    job_name = "infrastructure-checkbox-run"
    parameters = {}

    if args.iso_url:
        parameters["IMAGE_URL"] = args.iso_url
    if args.plan:
        parameters["PLAN"] = args.plan

    # Add optional parameters only if they were passed
    # If not passed, Jenkins job will use it's default values
    if args.exclude_task:
        parameters["EXCLUDE_TASK"] = args.exclude_task

    if args.additional_ppas:
        parameters["ADDITIONAL_PPAS"] = args.additional_ppas

    if args.plainbox_conf:
        parameters["PLAINBOX_CONF"] = args.plainbox_conf

    if args.machine_mst_json:
        parameters["MACHINE_MST_JSON"] = args.machine_mst_json

    if args.clone_manifest:
        parameters["CLONE_MANIFEST"] = "true"

    if args.prefix_submission_tarball:
        parameters["PREFIX_SUBMISSION_TARBALL"] = args.prefix_submission_tarball

    if args.auto_create_bugs_assignee:
        parameters["AUTO_CREATE_BUGS_ASSIGNEE"] = args.auto_create_bugs_assignee

    if args.auto_create_bugs_milestone:
        parameters["AUTO_CREATE_BUGS_MILESTONE"] = args.auto_create_bugs_milestone

    if args.test_flinger_global_timeout:
        parameters["TEST_FLINGER_GLOBAL_TIMEOUT"] = str(
            args.test_flinger_global_timeout
        )

    if args.force_run_test_flinger:
        parameters["FORCE_RUN_TEST_FLINGER"] = "true"

    if args.send_email_notification:
        parameters["SEND_EMAIL_NOTIFICATION"] = "true"

    if args.upload_to_oem_share:
        parameters["UPLOAD_TO_OEM_SHARE"] = "true"

    if args.put_dell_embargo:
        parameters["PUT_DELL_EMBARGO"] = "true"

    jenkins_server = get_jenkins_connection()

    if args.cid:
        # If single CID is provided, use it directly
        logger.info(f"Using provided CID: {args.cid}")
        if not has_existing_queue(args.cid):
            logger.error("CID does not have testflinger queue")
            sys.exit(1)
        parameters["CID"] = args.cid
        build_number = trigger_job(jenkins_server, job_name, parameters, args.dry_run)
        if not build_number:
            logger.error(f"Failed to trigger job: {job_name}")
            sys.exit(1)
        if not args.dry_run and args.wait_success and build_number:
            # poll the job status untill it succeed
            if not verify_job_success(
                jenkins_server, job_name, build_number, args.wait_timeout
            ):
                logger.error(f"Triggered job was not successful: {job_name}")
                sys.exit(1)
            logger.info(f"Job completed successfully: {job_name}")
            return True
    else:
        # Get CIDs which are online in Lab4 (IoT and PC)
        available_cids = get_linked_labresources()
        if not available_cids:
            logger.error("No available CIDs found")
            sys.exit(1)

        # Filter PC CIDs suitable for this ISO provisioning
        supported_cids = get_supported_cids(
            available_cids, args.iso_url, args.platform_info_dir
        )
        if not supported_cids:
            logger.error("No supported CIDs found for the given ISO file")
            sys.exit(1)

        for cid in supported_cids:
            parameters["CID"] = cid
            if not trigger_job(jenkins_server, job_name, parameters, args.dry_run):
                logger.error(f"Failed to trigger job for CID: {cid}")


if __name__ == "__main__":
    main()
