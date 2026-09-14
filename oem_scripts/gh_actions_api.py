#!/usr/bin/env python3
"""
A simple module to interact with GitHub Actions API.
Requires Github Token. Sample Fine-grained permissions:
- Repository Actions: Read & Write
- Repository Contents + metadata: Read
- Organization Permissions: None

### Usage Standalone:

export GITHUB_TOKEN=ghp_your_token_here

python3 -m oem_scripts.gh_actions_api --owner myuser --repo myrepo --list-workflows
python3 -m oem_scripts.gh_actions_api --owner myuser --repo myrepo --workflow deploy.yml \
  --input cid=123456-123456 --input plan=camera-automated

### Usage as Module:

from oem_scripts.gh_actions_api import GitHubActionsAPI

api = GitHubActionsAPI(token="ghp_xxx", owner="myuser", repo="myrepo")
api.trigger_workflow(
    workflow_id="build.yml",
    ref="main",
    inputs={"cid": "123456-12345", "plan": "camera-automated"}
)

# Check recent runs
runs = api.get_workflow_runs(workflow_id="build.yml")
"""

import argparse
import json
import logging
import os
import sys
from typing import Dict, Optional, Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)


class GitHubActionsAPI:
    """Generic GitHub Actions API client."""

    def __init__(
        self,
        token: Optional[str] = None,
        owner: Optional[str] = None,
        repo: Optional[str] = None,
    ):
        """
        Initialize GitHub Actions API client.

        Args:
            token: GitHub personal access token. If not provided, reads from
                   GITHUB_TOKEN environment variable.
            owner: Repository owner (username or organization)
            repo: Repository name
        """
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError(
                "GitHub token is required. Set GITHUB_TOKEN env var or pass token parameter."
            )

        self.owner = owner
        self.repo = repo
        self.base_url = "https://api.github.com"

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Make HTTP request to GitHub API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: Optional JSON data for request body

        Returns:
            Response JSON as dictionary, or None for 204 No Content responses
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }

        request_data = json.dumps(data).encode("utf-8") if data else None
        req = Request(url, data=request_data, headers=headers, method=method)

        try:
            with urlopen(req) as response:
                # GitHub API returns 204 No Content for successful workflow dispatch
                if response.status == 204:
                    return None
                response_body = response.read().decode("utf-8")
                if response_body:
                    return json.loads(response_body)
                return {}
        except HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                error_body = str(e)
            logger.error(f"HTTP Error {e.code}: {error_body}")
            raise
        except URLError as e:
            logger.error(f"URL Error: {e.reason}")
            raise

    def trigger_workflow(
        self,
        workflow_id: str,
        ref: str = "main",
        inputs: Optional[Dict[str, Any]] = None,
        owner: Optional[str] = None,
        repo: Optional[str] = None,
    ) -> bool:
        """
        Trigger a GitHub Actions workflow run.

        Args:
            workflow_id: Workflow file name (e.g., 'build.yml') or workflow ID
            ref: Git reference (branch, tag, or commit SHA) to run workflow on
            inputs: Optional dictionary of input parameters for the workflow
            owner: Repository owner (overrides instance owner)
            repo: Repository name (overrides instance repo)

        Returns:
            True if workflow was triggered successfully

        Example:
            >>> api = GitHubActionsAPI(token="ghp_xxx", owner="myuser", repo="myrepo")
            >>> api.trigger_workflow("build.yml", ref="main", inputs={"environment": "prod"})
        """
        owner = owner or self.owner
        repo = repo or self.repo

        if not owner or not repo:
            raise ValueError("Repository owner and name are required")

        endpoint = f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"

        payload = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs

        try:
            self._make_request("POST", endpoint, payload)
            logger.info(f"Successfully triggered workflow: {workflow_id}")
            logger.info(f"Repository: {owner}/{repo}")
            logger.info(f"Reference: {ref}")
            if inputs:
                logger.info(f"Inputs: {json.dumps(inputs, indent=2)}")
            return True
        except Exception as e:
            logger.error(f"Failed to trigger workflow: {e}")
            return False

    def list_workflows(
        self, owner: Optional[str] = None, repo: Optional[str] = None
    ) -> Dict:
        """
        List all workflows in a repository.

        Args:
            owner: Repository owner (overrides instance owner)
            repo: Repository name (overrides instance repo)

        Returns:
            Dictionary containing workflow information
        """
        owner = owner or self.owner
        repo = repo or self.repo

        if not owner or not repo:
            raise ValueError("Repository owner and name are required")

        endpoint = f"/repos/{owner}/{repo}/actions/workflows"
        return self._make_request("GET", endpoint)

    def get_workflow_runs(
        self,
        workflow_id: Optional[str] = None,
        owner: Optional[str] = None,
        repo: Optional[str] = None,
        per_page: int = 10,
    ) -> Dict:
        """
        Get workflow runs for a repository or specific workflow.

        Args:
            workflow_id: Optional workflow file name or ID to filter runs
            owner: Repository owner (overrides instance owner)
            repo: Repository name (overrides instance repo)
            per_page: Number of results per page

        Returns:
            Dictionary containing workflow run information
        """
        owner = owner or self.owner
        repo = repo or self.repo

        if not owner or not repo:
            raise ValueError("Repository owner and name are required")

        if workflow_id:
            endpoint = f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs?per_page={per_page}"
        else:
            endpoint = f"/repos/{owner}/{repo}/actions/runs?per_page={per_page}"

        return self._make_request("GET", endpoint)

    def get_run_status(
        self, run_id: int, owner: Optional[str] = None, repo: Optional[str] = None
    ) -> Dict:
        """
        Get status of a specific workflow run.

        Args:
            run_id: Workflow run ID
            owner: Repository owner (overrides instance owner)
            repo: Repository name (overrides instance repo)

        Returns:
            Dictionary containing workflow run status
        """
        owner = owner or self.owner
        repo = repo or self.repo

        if not owner or not repo:
            raise ValueError("Repository owner and name are required")

        endpoint = f"/repos/{owner}/{repo}/actions/runs/{run_id}"
        return self._make_request("GET", endpoint)


def parse_workflow_inputs(input_args):
    """Parse workflow input arguments from key=value format.

    Args:
        input_args: List of strings in 'key=value' format

    Returns:
        Dictionary of parsed inputs, or None if input_args is None/empty

    Raises:
        ValueError: If any input is not in valid 'key=value' format
    """
    if not input_args:
        return None

    inputs = {}
    for input_str in input_args:
        if "=" not in input_str:
            raise ValueError(f"Invalid input format '{input_str}'. Use key=value")
        key, value = input_str.split("=", 1)
        inputs[key.strip()] = value.strip()

    return inputs


def create_parser():
    """Create and configure argument parser."""
    parser = argparse.ArgumentParser(
        description="Trigger GitHub Actions workflows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Trigger a workflow on main branch
  %(prog)s --owner myuser --repo myrepo --workflow build.yml

  # Trigger with inputs
  %(prog)s --owner myuser --repo myrepo --workflow deploy.yml --ref main \\
           --input environment=production --input version=1.2.3

  # List available workflows
  %(prog)s --owner myuser --repo myrepo --list-workflows

Environment Variables:
  GITHUB_TOKEN    GitHub personal access token (required)
        """,
    )

    parser.add_argument(
        "--owner", required=True, help="Repository owner (username or organization)"
    )
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument(
        "--workflow", help="Workflow file name (e.g., build.yml) or workflow ID"
    )
    parser.add_argument(
        "--ref", default="main", help="Git reference to run workflow on (default: main)"
    )
    parser.add_argument(
        "--input",
        action="append",
        dest="inputs",
        help="Workflow input in key=value format (can be used multiple times)",
    )
    parser.add_argument(
        "--list-workflows",
        action="store_true",
        help="List all workflows in the repository",
    )
    parser.add_argument(
        "--list-runs", action="store_true", help="List recent workflow runs"
    )
    parser.add_argument(
        "--token", help="GitHub personal access token (or set GITHUB_TOKEN env var)"
    )

    return parser


def main():
    """Command-line interface for triggering GitHub Actions workflows."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = create_parser()
    args = parser.parse_args()

    try:
        api = GitHubActionsAPI(token=args.token, owner=args.owner, repo=args.repo)

        if args.list_workflows:
            workflows = api.list_workflows()
            logger.info(f"Available workflows in {args.owner}/{args.repo}:")
            logger.info("-" * 60)
            for workflow in workflows.get("workflows", []):
                logger.info(f"{workflow['name']}")
                logger.info(f"File: {workflow['path']}")
                logger.info(f"State: {workflow['state']}")
            return 0

        if args.list_runs:
            runs = api.get_workflow_runs(workflow_id=args.workflow)
            logger.info(f"Recent workflow runs in {args.owner}/{args.repo}:")
            logger.info("-" * 60)
            for run in runs.get("workflow_runs", []):
                logger.info(f"{run['name']} (#{run['run_number']})")
                logger.info(
                    f"Status: {run['status']} | Conclusion: {run['conclusion']}"
                )
                logger.info(f"Branch: {run['head_branch']}")
                logger.info(f"Created: {run['created_at']}")
            return 0

        if not args.workflow:
            parser.error("--workflow is required when triggering a workflow")

        inputs = parse_workflow_inputs(args.inputs)
        return (
            0
            if api.trigger_workflow(
                workflow_id=args.workflow, ref=args.ref, inputs=inputs
            )
            else 1
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
