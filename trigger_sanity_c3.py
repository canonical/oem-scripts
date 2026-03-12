#!/usr/bin/env python3
"""Trigger sanity test via GitHub Actions or Jenkins job
Currently script supports both while in the middle of migration.
After GitHub workflow is up, pipeline can use the same script but need to update the arguments.

TODO: After Jenkins jobs are discontinued, the Jenkins related code can be removed

GitHub Actions:

./trigger_sanity_c3.py --use-github-actions \
  --github-owner canonical \
  --github-repo oem-enablement-ops \
  --github-workflow provision-test-image.yml \
  --github-branch develop-branch \
  --cid 202411-35996 --iso-url <url> --plan <plan>

When multiple CIDs are provided, GitHub Actions is triggered once with CIDs joined by commas:

./trigger_sanity_c3.py --use-github-actions \
    --github-owner canonical \
    --github-repo oem-enablement-ops \
    --github-workflow provision-test-image.yml \
    --github-branch develop-branch \
    --cid 202411-35996 202411-35997 --iso-url <url> --plan <plan>

Jenkins job::
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
from pathlib import Path
import time
from gh_actions_api import GitHubActionsAPI

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


def get_github_actions_connection(owner, repo):
    """Initialize GitHub Actions API client.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
    """
    github_token = os.getenv("GITHUB_TOKEN")

    if not github_token:
        logger.error(
            "Missing GitHub token. Please set GITHUB_TOKEN environment variable."
        )
        sys.exit(1)

    try:
        return GitHubActionsAPI(token=github_token, owner=owner, repo=repo)
    except Exception as e:
        logger.error(f"Failed to initialize GitHub Actions API: {e}")
        sys.exit(1)


def clean_json_string(s):
    """Extract a JSON object or array from a string that may contain leading text."""
    start_brace = s.find("{")
    start_bracket = s.find("[")

    start_index = -1

    # Determine the actual start index of the JSON content
    if start_brace != -1 and start_bracket != -1:
        start_index = min(start_brace, start_bracket)
    elif start_brace != -1:
        start_index = start_brace
    elif start_bracket != -1:
        start_index = start_bracket

    if start_index == -1:
        logger.error("No JSON object or array found in the input string.")
        raise json.JSONDecodeError("No JSON object or array found.", s, 0)

    return json.loads(s[start_index:])


def is_ping_online(ip_address):
    """Check if a host is reachable via ping."""
    try:
        response = subprocess.run(
            ["ping", "-c", "1", "-W", str(SSH_TIMEOUT), ip_address],
            stdout=subprocess.DEVNULL,
            timeout=10,
        )
        if response.returncode != 0:
            logger.warning(f"Ping {ip_address} has failed. Skip...")
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"Ping to {ip_address} timed out. Skip...")
        return False

    return True


def get_linked_labresources():
    """Get list of available CIDs from linked lab resources."""
    try:
        logger.info("Fetching lab resources from C3 API...")
        result = subprocess.run(
            [
                C3_V2_API_CLI,
                "--get",
                "/api/v2/linked-labresources/?datacentre__name__iexact=tel-l10&pagination=limitoffset&limit=0&format=json",
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
                    if is_ping_online(ip_address):
                        available_cids.append(cid)
                        logger.debug(f"Added CID: {cid} with IP: {ip_address}")
                    else:
                        logger.debug(f"Skip CID: {cid} with IP: {ip_address}. No ping.")

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
            check=True,
        )
        data = clean_json_string(result.stdout)
        if not data:
            logger.warning(f"Failed to fetch queue details for CID: {cid}")
            return False

        if data.get("queues"):
            logger.debug(f"CID {cid} has existing queues: {data['queues']}")
            return True

        logger.debug(f"CID {cid} has no queues")
        return False

    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        logger.error(f"Failed to check queue status for CID {cid}: {e}")
        return False


def is_reserved_cid(platform_info_dir, cid):
    # Reserved CIDs are in oem-hw-info/daily-sanity/daily-sanity-exclude.json
    # Returns True when CID is listed in "cids"
    reserved_file_path = (
        Path(platform_info_dir).parent / "daily-sanity" / "daily-sanity-exclude.json"
    )

    try:
        with open(reserved_file_path, "r") as file:
            data = json.load(file)
            reserved_cids = data.get("cids", [])
            if cid in reserved_cids:
                return True
    except FileNotFoundError:
        logger.info(f"{reserved_file_path} is missing. Skip...")
        return False


def is_reserved_tag(platform_info_dir, tag):
    # Reserved tags are in oem-hw-info/daily-sanity/daily-sanity-exclude.json
    # Returns True when tag is listed in "components"
    reserved_file_path = (
        Path(platform_info_dir).parent / "daily-sanity" / "daily-sanity-exclude.json"
    )

    try:
        with open(reserved_file_path, "r") as file:
            data = json.load(file)
            reserved_tags = data.get("components", [])
            if tag in reserved_tags:
                return True
    except FileNotFoundError:
        logger.info(f"{reserved_file_path} is missing. Skip...")
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
        if is_reserved_cid(platform_info_dir, cid):
            logger.info(f"{cid} is reserved in daily-sanity-exclude.json. Skip...")
            continue

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
                    if is_reserved_tag(platform_info_dir, tag):
                        logger.info(
                            f"{tag} is reserved in daily-sanity-exclude.json. Skip {cid}..."
                        )
                        continue

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


def trigger_github_action(api, workflow_id, branch, parameters, dry_run=False):
    """Trigger GitHub Actions workflow with given parameters.

    Returns:
        - run_id (int) on success
        - False on failure
        - None for dry_run
    """
    try:
        # GitHub workflow uses ISO_NAME to set the run-name
        # so passing iso name instead of full URL is for readability
        # workflow itself has logic to reconstruct the full URL
        github_inputs = parameters.copy()
        if "IMAGE_URL" in github_inputs:
            iso_url = github_inputs.pop("IMAGE_URL")
            iso_name = iso_url.split("/")[-1]
            github_inputs["ISO_NAME"] = iso_name

        if dry_run:
            logger.info(f"[DRY RUN] Would trigger workflow: {workflow_id} with inputs:")
            logger.info(f"  branch: {branch}")
            for key, value in github_inputs.items():
                logger.info(f"  {key}: {value}")
            return None
        else:
            # Get the latest run number before triggering to detect the new one
            try:
                runs_before = api.get_workflow_runs(workflow_id=workflow_id, per_page=1)
                last_run_number = (
                    runs_before["workflow_runs"][0]["run_number"]
                    if runs_before and runs_before.get("workflow_runs")
                    else 0
                )
                logger.debug(f"Last run number before trigger: {last_run_number}")
            except Exception as e:
                logger.warning(f"Could not get existing runs: {e}")
                last_run_number = 0

            # Trigger the workflow
            if not api.trigger_workflow(
                workflow_id=workflow_id, ref=branch, inputs=github_inputs
            ):
                logger.error(f"Failed to trigger workflow: {workflow_id}")
                return False

            # Poll for the new run to appear
            # sleeps longer each attempt in case API is slow
            MAX_POLL_ATTEMPTS = 5
            BASE_SLEEP = 2
            for attempt in range(MAX_POLL_ATTEMPTS):
                sleep_time = BASE_SLEEP * (2 ** attempt)
                time.sleep(sleep_time)
                try:
                    runs_after = api.get_workflow_runs(
                        workflow_id=workflow_id, per_page=5
                    )
                    if runs_after and runs_after.get("workflow_runs"):
                        for run in runs_after["workflow_runs"]:
                            if run["run_number"] > last_run_number:
                                run_id = run["id"]
                                run_number = run["run_number"]
                                logger.info(
                                    f"Successfully triggered workflow: {workflow_id} - Run #{run_number} (ID: {run_id})"
                                )
                                return run_id
                except Exception as e:
                    logger.debug(f"Polling attempt {attempt + 1}: {e}")

            logger.error(
                "Workflow triggered but could not find new run ID after polling"
            )
            return False
    except Exception as e:
        logger.error(f"Failed to trigger GitHub Actions workflow: {e}")
        return False


def trigger_ci(
    use_github,
    github_api,
    workflow_id,
    branch,
    jenkins_server,
    job_name,
    parameters,
    dry_run,
):
    """Unified function to trigger either GitHub Actions or Jenkins.

    Returns:
        - For GitHub Actions: run_id (int) on success, False on failure, None for dry_run
        - For Jenkins: build_number (int) on success, False on failure, None for dry_run
    """
    if use_github:
        return trigger_github_action(
            github_api, workflow_id, branch, parameters, dry_run
        )
    else:
        return trigger_job(jenkins_server, job_name, parameters, dry_run)


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


def verify_github_workflow_success(api, run_id, wait_timeout):
    """Poll the GitHub Actions workflow status until it completes and return True if successful.

    Args:
        api: GitHubActionsAPI instance
        run_id: Specific workflow run ID to monitor
        wait_timeout: Maximum time to wait in seconds
    """
    SLEEP_TIME = 240
    MAX_ATTEMPTS = int(wait_timeout / SLEEP_TIME + 1)
    logger.debug(
        f"Set timeout after {MAX_ATTEMPTS} tries. Sleep after try: {SLEEP_TIME} sec"
    )

    for attempt in range(MAX_ATTEMPTS):
        try:
            # Fetch run status for the specific run_id
            run_status = api.get_run_status(run_id)
            status = run_status.get("status")
            conclusion = run_status.get("conclusion")
            run_number = run_status.get("run_number", run_id)

            if status != "completed":
                logger.info(
                    f"Workflow run #{run_number} is still running (status: {status})... Sleep {SLEEP_TIME} sec..."
                )
                time.sleep(SLEEP_TIME)
            elif conclusion == "success":
                logger.info(f"Workflow run #{run_number} completed successfully.")
                return True
            else:
                logger.error(
                    f"Workflow run #{run_number} failed with conclusion: {conclusion}"
                )
                return False
        except Exception as e:
            logger.error(f"Error fetching workflow status on attempt {attempt}: {e}")
            time.sleep(SLEEP_TIME)

    logger.error("Max attempts reached. Unable to verify workflow status.")
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
        "--iso-sha", help="sha256sum of the ISO file, passed to Jenkins as IMAGE_SHA"
    )
    parser.add_argument(
        "--cid",
        nargs="+",
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
        "--embargo-vendor",
        default=None,
        help="Put 'dell' or 'hp' embargo config on DUT after provisioning",
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
    parser.add_argument(
        "--use-github-actions",
        action="store_true",
        help="Use GitHub Actions instead of Jenkins (requires GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--github-owner",
        help="GitHub repository owner (required with --use-github-actions)",
    )
    parser.add_argument(
        "--github-repo",
        help="GitHub repository name (required with --use-github-actions)",
    )
    parser.add_argument(
        "--github-workflow",
        help="GitHub Actions workflow file name (required with --use-github-actions)",
    )
    parser.add_argument(
        "--github-branch",
        help="Git branch to run GitHub Actions workflow on (required with --use-github-actions)",
    )
    args = parser.parse_args()

    # Validate GitHub Actions specific arguments
    if args.use_github_actions:
        if (
            not args.github_owner
            or not args.github_repo
            or not args.github_workflow
            or not args.github_branch
        ):
            parser.error(
                "When using --use-github-actions, you must provide: "
                "--github-owner, --github-repo, --github-workflow, and --github-branch"
            )

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
    job_name = args.job_name
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

    if args.test_flinger_global_timeout:
        parameters["TEST_FLINGER_GLOBAL_TIMEOUT"] = str(
            args.test_flinger_global_timeout
        )

    if args.force_run_test_flinger:
        parameters["FORCE_RUN_TEST_FLINGER"] = "true"

    if args.embargo_vendor:
        parameters["EMBARGO_VENDOR"] = args.embargo_vendor

    if args.iso_sha:
        parameters["IMAGE_SHA"] = args.iso_sha

    # Initialize connection based on mode
    if args.use_github_actions:
        github_api = get_github_actions_connection(args.github_owner, args.github_repo)
        workflow_id = args.github_workflow
        jenkins_server = None
    else:
        jenkins_server = get_jenkins_connection()
        github_api = None

    # only run on CIDs in Lab10
    if len(args.cid) == 1:
        # Single CID is provided, used for canary deployment
        cid = args.cid[0]
        if args.platform_info_dir:
            if is_reserved_cid(args.platform_info_dir, cid):
                logger.info(f"{cid} is reserved in daily-sanity-exclude.json. Skip...")
                sys.exit(2)

        logger.info(f"Using provided CID: {cid}")
        if not has_existing_queue(cid):
            logger.error("CID does not have testflinger queue")
            sys.exit(1)
        parameters["CID"] = cid

        result = trigger_ci(
            args.use_github_actions,
            github_api,
            workflow_id,
            args.github_branch,
            jenkins_server,
            job_name,
            parameters,
            args.dry_run,
        )

        if not result:
            logger.error(
                f"Failed to trigger {'workflow' if args.use_github_actions else 'job'}"
            )
            sys.exit(1)

        # Wait for success if requested
        if not args.dry_run and args.wait_success and result:
            if args.use_github_actions:
                # result is run_id for GitHub Actions
                if not verify_github_workflow_success(
                    github_api, result, args.wait_timeout
                ):
                    logger.error(
                        f"Triggered workflow was not successful: {workflow_id}"
                    )
                    sys.exit(1)
                logger.info(f"Workflow completed successfully: {workflow_id}")
            else:
                # result is build_number for Jenkins
                if not verify_job_success(
                    jenkins_server, job_name, result, args.wait_timeout
                ):
                    logger.error(f"Triggered job was not successful: {job_name}")
                    sys.exit(1)
                logger.info(f"Job completed successfully: {job_name}")
            return True
    elif len(args.cid) > 1:
        # Multiple CIDs are provided, used with selected list of CIDs
        # This runs get_linked_labresources() only once to save time
        available_cids = get_linked_labresources()
        supported_cids = get_supported_cids(
            available_cids, args.iso_url, args.platform_info_dir
        )
        selected_cids = []
        for cid in args.cid:
            if args.platform_info_dir:
                if is_reserved_cid(args.platform_info_dir, cid):
                    logger.info(
                        f"{cid} is reserved in daily-sanity-exclude.json. Skip..."
                    )
                    continue

            if cid not in supported_cids:
                logger.warning(
                    f"{cid} is not supported (i.e. reserved tag, not available in Lab10, etc.). Skip..."
                )
                continue

            logger.info(f"Using provided CID: {cid}")
            if not has_existing_queue(cid):
                logger.error("CID does not have testflinger queue")
                sys.exit(1)
            selected_cids.append(cid)

        if not selected_cids:
            logger.error("No valid CIDs available to trigger")
            sys.exit(1)

        if args.use_github_actions:
            parameters["CID"] = ",".join(selected_cids)
            if not trigger_ci(
                args.use_github_actions,
                github_api,
                workflow_id,
                args.github_branch,
                jenkins_server,
                job_name,
                parameters,
                args.dry_run,
            ):
                logger.error(f"Failed to trigger workflow for CIDs: {selected_cids}")
                sys.exit(1)
        else:
            for cid in selected_cids:
                parameters["CID"] = cid
                if not trigger_ci(
                    args.use_github_actions,
                    github_api,
                    workflow_id,
                    args.github_branch,
                    jenkins_server,
                    job_name,
                    parameters,
                    args.dry_run,
                ):
                    logger.error(f"Failed to trigger for CID: {cid}")
                    continue
    else:
        # No CID is provided, get all CIDs which are online in Lab10 (IoT and PC)
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

        if args.use_github_actions:
            parameters["CID"] = ",".join(supported_cids)
            if not trigger_ci(
                args.use_github_actions,
                github_api,
                workflow_id,
                args.github_branch,
                jenkins_server,
                job_name,
                parameters,
                args.dry_run,
            ):
                logger.error(f"Failed to trigger workflow for CIDs: {supported_cids}")
        else:
            for cid in supported_cids:
                parameters["CID"] = cid
                if not trigger_ci(
                    args.use_github_actions,
                    github_api,
                    workflow_id,
                    args.github_branch,
                    jenkins_server,
                    job_name,
                    parameters,
                    args.dry_run,
                ):
                    logger.error(f"Failed to trigger for CID: {cid}")


if __name__ == "__main__":
    main()
