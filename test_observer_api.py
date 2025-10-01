#!/usr/bin/env python3
import requests
import argparse
import json
import sys


FAMILY = "image"
OS = "ubuntu"
RELEASE = "noble"
TOB_API_BASE_URL = "http://test-observer-api-staging.canonical.com"


def generate_tob_payload(args):
    """
    Generate the payload for Test Observer API requests.
    """
    # start with defaults and required args
    payload = {
        "family": FAMILY,
        "os": OS,
        "release": RELEASE,
        "owner": args.owner,
        "name": None,
        "version": None,
        "arch": None,
        "environment": args.environment,
        "test_plan": None,
        "execution_stage": args.execution_stage,
        "sha256": None,
        "image_url": None,
        "ci_link": None,
    }

    # get values from submission.json if available
    if args.submission_json:
        image_info = parse_image_info(args.submission_json)
        if image_info:
            # Directly update payload with image_info values
            for key in ["name", "version", "test_plan", "image_url", "arch"]:
                if key in image_info and image_info[key] is not None:
                    payload[key] = image_info[key]

    # override if user provided values via args
    override_fields = {
        "name": args.name,
        "version": args.version,
        "arch": args.arch,
        "test_plan": args.test_plan,
        "image_url": args.image_url,
        "sha256": args.sha256,
        "ci_link": args.ci_link,
        "execution_stage": args.execution_stage,
    }

    for key, value in override_fields.items():
        if value is not None:  # Only override if the argument was provided
            payload[key] = value

    validate_tob_payload(payload)

    # removes the None values, let api handle the defaults
    return {k: v for k, v in payload.items() if v is not None}


def validate_tob_payload(payload):
    """Validate that required fields that could be found in submission file
    Otherwise, request them via args
    """
    required_fields = {
        "arch": "--arch",
        "test_plan": "--test-plan",
    }

    for field, arg_name in required_fields.items():
        if not payload.get(field):
            field_name = " ".join(word.capitalize() for word in field.split("_"))
            print(
                f"Error: {field_name} is required but was not provided.",
                file=sys.stderr,
            )
            print(
                f"\nPlease provide the {field.replace('_', ' ')} using the {arg_name} argument",
                file=sys.stderr,
            )
            sys.exit(1)


def start_test_execution(api_url, headers, payload):
    """Starts a new test execution and returns its ID."""
    start_url = f"{api_url}/v1/test-executions/start-test"

    print("Starting test execution...")
    print("Payload:", json.dumps(payload, indent=2))
    try:
        response = requests.put(start_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        response_data = response.json()
        execution_id = response_data.get("id")

        if not execution_id:
            print(" Error: 'id' not found in start-test response.", file=sys.stderr)
            print(f"Full response: {response_data}", file=sys.stderr)
            sys.exit(1)

        print(f"Test execution started successfully. ID: {execution_id}")
        return execution_id
    except requests.exceptions.RequestException as e:
        print(f" HTTP Error starting execution: {e}", file=sys.stderr)
        if e.response:
            print(f"Response Body: {e.response.text}", file=sys.stderr)
        sys.exit(1)


def submit_test_results(api_url, headers, execution_id, results_data):
    """Submits test results to the Test Observer API.

    Args:
        api_url: Base URL of the Test Observer API
        headers: Dictionary of HTTP headers to include in the request
        execution_id: ID of the test execution to submit results for
        results_data: Dictionary containing test results in the expected format
    """
    results_url = f"{api_url}/v1/test-executions/{execution_id}/test-results"

    print("Submitting test results...")
    try:
        response = requests.post(
            results_url, headers=headers, json=results_data, timeout=30
        )
        response.raise_for_status()

        print("Test results submitted successfully.")
    except requests.exceptions.RequestException as e:
        print(f"HTTP Error submitting results: {e}", file=sys.stderr)
        if e.response:
            print(f"Response Body: {e.response.text}", file=sys.stderr)
        sys.exit(1)


def end_test_execution(api_url, headers, execution_id, ci_link):
    """Ends the test execution by patching its status to COMPLETED."""
    patch_url = f"{api_url}/v1/test-executions/{execution_id}"
    payload = {"status": "COMPLETED", "ci_link": ci_link}

    print("Ending test execution...")
    try:
        response = requests.patch(patch_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        print("Test execution marked as COMPLETED.")
    except requests.exceptions.RequestException as e:
        print(f" HTTP Error ending execution: {e}", file=sys.stderr)
        if e.response:
            print(f"Response Body: {e.response.text}", file=sys.stderr)
        sys.exit(1)


def parse_submission_json(submission_file):
    """
    Parse a Checkbox submission.json file and convert it to the TOB test results format.

    Args:
        submission_file (str): Path to the submission.json file

    Returns:
        list: List of test results in TOB format
    """
    try:
        with open(submission_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        results = []
        for result in data.get("results", []):
            # Skip if not a test result
            if "status" not in result or "id" not in result:
                continue

            # Create test result entry
            test_result = {
                "name": str(result["id"]),
                "status": "PASSED" if result.get("status") == "pass" else "SKIPPED" if result.get("status") == "skip" else "FAILED",
                "template_id": str(result.get("template_id", "")),
                "category": str(result.get("category", "")),
                "comment": str(result.get("comments", "")),
                "io_log": str(result.get("io_log", "")),
            }
            results.append(test_result)

        return results

    except json.JSONDecodeError as e:
        print(f"Error parsing JSON file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error processing submission file: {e}", file=sys.stderr)
        sys.exit(1)


def parse_image_info(submission_file):
    try:
        with open(submission_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        payload = (
            data.get("system_information")
            .get("image_info")
            .get("outputs")
            .get("payload")
        )
        project = payload.get("project")  # somerville
        series = payload.get("series")  # noble

        kernel_type = payload.get("kernel_type")  # oem
        kernel_version = payload.get("kernel_version")  # 24.04c
        kernel_suffix = payload.get("kernel_suffix")  # proposed, next, edge

        build_date = payload.get("build_date")
        build_number = payload.get("build_number")
        image_version = f"{build_date}-{build_number}"

        url = payload.get("url")

        # Build the name from available meta data because suffix maybe None
        name_parts = [project, kernel_type, kernel_version, kernel_suffix]
        name = "-".join(str(part) for part in name_parts if part is not None)

        architecture = data.get("architecture")
        test_plan = data.get("testplan_id")
        if test_plan:
            test_plan = test_plan.split("::", 1)[-1]  # remove canonical prefix
        return {
            "name": name,
            "version": image_version,
            "series": series,
            "image_url": url,
            "arch": architecture,
            "test_plan": test_plan,
        }

    except KeyError as e:
        raise ValueError(f"Missing expected field in JSON: {e}")
    except Exception as e:
        raise ValueError(f"Error processing submission file: {e}")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Submit test results to Test Observer API",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Existing arguments
    parser.add_argument(
        "--api-url",
        default=TOB_API_BASE_URL,
        help="Base URL of the Test Observer API (default: %s)" % TOB_API_BASE_URL,
    )
    parser.add_argument("--name", help="Name of the test image")
    parser.add_argument("--version", help="Version of the test image")
    parser.add_argument("--arch", help="Architecture i.e. amd64")
    parser.add_argument(
        "--environment", required=True, help="Test environment, i.e CID of PC platform"
    )
    parser.add_argument("--test-plan", help="Test plan identifier")
    parser.add_argument(
        "--execution-stage",
        default="pending",
        choices=["pending", "current"],
        help="Execution stage (default: %(default)s)",
    )
    parser.add_argument("--sha256", required=True, help="SHA256 hash of the test image")
    parser.add_argument("--image-url", help="URL to the test image")
    parser.add_argument("--ci-link", help="URL to CI job")
    parser.add_argument("--owner", required=True, help="Owner of the test execution")
    parser.add_argument(
        "--submission-json", help="Path to Checkbox submission JSON file"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="If set, will not make any API calls, only show what would be done",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    payload = generate_tob_payload(args)
    if args.api_url:
        print(f"\nAPI URL: {args.api_url}")
    else:
        print(f"\nAPI URL: {TOB_API_BASE_URL}")

    if args.dry_run:
        print("\nDry run - would execute the following:")
        print("\nStart test execution with payload:")
        print(json.dumps(payload, indent=2))

        if args.submission_json:
            print(f"\nSubmit test results from: {args.submission_json}")
            try:
                results = parse_submission_json(args.submission_json)
                print(f"   - Found {len(results)} test results to submit")
            except Exception as e:
                print(f"   - Could not parse test results: {e}")

        if "ci_link" in payload and payload["ci_link"]:
            print(
                f"\nMark test execution as completed with CI link: {payload['ci_link']}"
            )
    else:
        execution_id = start_test_execution(args.api_url, headers, payload)

        if args.submission_json:
            results = parse_submission_json(args.submission_json)
            submit_test_results(args.api_url, headers, execution_id, results)

        end_test_execution(args.api_url, headers, execution_id, payload.get("ci_link"))
        print("\nAll steps completed successfully!")


if __name__ == "__main__":
    main()
