from __future__ import annotations

import logging
import os
import urllib3
from datetime import date

import requests

log = logging.getLogger(__name__)

# The PSFC site has a malformed intermediate certificate (pathlen without
# keyCertSign), which strict OpenSSL in Python 3.14 rejects.  Traffic is
# still encrypted; we just skip chain verification for this host.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def login_as(session: requests.Session, base_url: str, username: str, password: str) -> None:
    """Log into the PSFC member site with explicit credentials."""
    login_url = f"{base_url}/services/login/"

    # Fetch login page to get CSRF token
    resp = session.get(login_url, verify=False)
    resp.raise_for_status()

    csrf_token = None
    if "csrfmiddlewaretoken" in resp.text:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
        if csrf_input:
            csrf_token = csrf_input.get("value")

    payload = {
        "username": username,
        "password": password,
    }
    if csrf_token:
        payload["csrfmiddlewaretoken"] = csrf_token

    headers = {"Referer": login_url}
    resp = session.post(login_url, data=payload, headers=headers, verify=False)
    resp.raise_for_status()

    if "login" in resp.url.lower() and "logout" not in resp.text.lower():
        raise RuntimeError("Login appears to have failed — still on login page")

    log.info("Logged in successfully")


def login(session: requests.Session, base_url: str) -> None:
    """Log into the PSFC member site using env var credentials."""
    username = os.environ["COOP_USERNAME"]
    password = os.environ["COOP_PASSWORD"]
    login_as(session, base_url, username, password)


def fetch_member_status(session: requests.Session, base_url: str) -> str:
    """Fetch the /services/ page HTML (member status info)."""
    url = f"{base_url}/services/"
    resp = session.get(url, verify=False)
    resp.raise_for_status()
    log.info("Fetched member status page: %s", url)
    return resp.text


def fetch_shift_pages(
    session: requests.Session,
    base_url: str,
    path_template: str,
    max_weeks: int = 6,
) -> list[str]:
    """Fetch shift calendar pages for the next N weeks.

    URL pattern: /services/shifts/{week_offset}/{committee_id}/{time_of_day}/{date}/
    We use committee_id=0 (all) and time_of_day=0 (all day).
    """
    pages: list[str] = []
    today = date.today().isoformat()

    for week_offset in range(max_weeks):
        path = path_template.format(
            week_offset=week_offset,
            committee_id=0,
            time_of_day=0,
            date=today,
        )
        url = f"{base_url}{path}"

        try:
            resp = session.get(url, verify=False)
            resp.raise_for_status()
            pages.append(resp.text)
            log.info("Fetched week %d: %s", week_offset, url)
        except Exception:
            log.exception("Failed to fetch week %d: %s", week_offset, url)

    return pages


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "CoopShiftMonitor/1.0",
    })
    return session
