from configparser import ConfigParser, Error as ConfigError
from functools import lru_cache
import os
import requests

JIRA_API_URL = "https://warthogs.atlassian.net/rest/api/2/"


@lru_cache(maxsize=1)
def get_jira_auth() -> tuple:
    """Read Jira credentials once per process."""
    config = ConfigParser()
    config_path = os.path.expanduser("~/.config/oem-scripts/config.ini")
    try:
        with open(config_path) as config_file:
            config.read_file(config_file)
    except FileNotFoundError:
        raise RuntimeError(
            f"Jira configuration file does not exist: {config_path}"
        ) from None
    except (OSError, UnicodeError, ConfigError):
        raise RuntimeError(
            f"Failed to load Jira configuration file: {config_path}"
        ) from None
    return config["private"]["jira_email"], config["private"]["jira_token"]


def get_jira_status(bug_id: str) -> str:
    """Return the Jira ticket status using stored credentials."""
    response = requests.get(
        f"{JIRA_API_URL}issue/{bug_id}",
        params={"fields": "status"},
        auth=get_jira_auth(),
    )
    response.raise_for_status()
    return response.json()["fields"]["status"]["name"]
