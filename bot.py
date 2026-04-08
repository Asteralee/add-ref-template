import requests
import re
import time
from datetime import datetime
import os
import random

API_URL = "https://test.wikipedia.org/w/api.php"
TARGET_SECTION = "Pages to fix"
DELAY = 3.0
USER_AGENT = "ReflistBot/3.0 (https://simple.wikipedia.org/wiki/User:YourBotName)"
WORKLIST_PAGE = "User:YourBot/Worklist" 
USERNAME = os.environ["BOT_USER"]
PASSWORD = os.environ["BOT_PASS"]

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def api_request(method, params=None, data=None):
    try:
        if method == "GET":
            r = session.get(API_URL, params={**(params or {}), "maxlag": 5})
        else:
            r = session.post(API_URL, data={**(data or {}), "maxlag": 5})
        result = r.json()
        if "error" in result:
            print("API error:", result)
            return None
        return result
    except Exception as e:
        print("Request failed:", e)
        return None


def login():
    data = api_request("GET", {
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    })
    if not data:
        raise Exception("Failed to fetch login token")
    token = data["query"]["tokens"]["logintoken"]

    result = api_request("POST", data={
        "action": "login",
        "lgname": USERNAME,
        "lgpassword": PASSWORD,
        "lgtoken": token,
        "format": "json"
    })
    if result["login"]["result"] != "Success":
        raise Exception("Login failed")

def get_page(title):
    data = api_request("GET", {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": title,
        "format": "json"
    })
    if not data:
        return None
    page = next(iter(data["query"]["pages"].values()))
    return page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")

def edit_page(title, text, summary):
    data = api_request("GET", {
        "action": "query",
        "meta": "tokens",
        "format": "json"
    })
    if not data:
        return None
    token = data["query"]["tokens"]["csrftoken"]
    return api_request("POST", data={
        "action": "edit",
        "title": title,
        "text": text,
        "summary": summary,
        "token": token,
        "bot": True,
        "minor": True,
        "format": "json"
    })

def extract_section(text):
    pattern = re.compile(
        rf"^==+\s*{re.escape(TARGET_SECTION)}\s*==+\s*$\n(.*?)(?=\n==+|\Z)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE
    )
    match = pattern.search(text)
    return match.group(1) if match else ""

def extract_pages(section_text):
    pages = []
    for line in section_text.splitlines():
        if "[[" in line and "{{done" not in line.lower():
            m = re.search(r"\[\[(.*?)\]\]", line)
            if m:
                pages.append(m.group(1))
    return pages

def mark_done(text, title):
    today = datetime.utcnow().strftime("%d %B %Y")
    pattern = re.compile(rf"\*\s*\[\[{re.escape(title)}\]\].*")
    return pattern.sub(f"* [[{title}]] -- {{{{done}}}} on {today}", text)

def update_last_modified(text):
    today = datetime.utcnow().strftime("%d %B %Y")
    if "'''Last modified''':" in text:
        return re.sub(r"'''Last modified''':.*", f"'''Last modified''': {today} UTC", text)
    else:
        return f"'''Last modified''': {today} UTC\n\n{text}"

REF_SECTION_REGEX = re.compile(r"^=+\s*(references?|sources?|citations?)\s*:?\s*=+$", re.IGNORECASE)
REFLIST_REGEX = re.compile(r"\{\{\s*reflist", re.IGNORECASE)

def fix_reflist(text):
    if re.search(r"<references\s*/?>", text, re.IGNORECASE):
        return None

    lines = text.split("\n")
    new_lines = []
    in_ref = False
    found_section = False
    found_reflist = False

    for line in lines:
        if REF_SECTION_REGEX.match(line.strip()):
            in_ref = True
            found_section = True
            found_reflist = False
            new_lines.append(line)
            continue
        if in_ref and line.startswith("="):
            if not found_reflist:
                new_lines.append("{{reflist}}")
            in_ref = False
        if in_ref and REFLIST_REGEX.search(line):
            found_reflist = True
        new_lines.append(line)

    if in_ref and not found_reflist:
        new_lines.append("{{reflist}}")
    if not found_section:
        new_lines.append("\n== References ==\n{{reflist}}")

    new_text = "\n".join(new_lines)
    return new_text if new_text != text else None

# Main

def main():
    login()
    worklist_text = get_page(WORKLIST_PAGE)
    if not worklist_text:
        print("Failed to fetch worklist page")
        return

    section_text = extract_section(worklist_text)
    pages = extract_pages(section_text)

    for title in pages:
        print("Processing:", title)
        text = get_page(title)
        if not text:
            continue

        new_text = fix_reflist(text)
        if not new_text:
            continue

        edit_page(title, new_text, "Bot: Adding {{reflist}}")

        worklist_text = mark_done(worklist_text, title)
        time.sleep(DELAY + random.random())

    edit_page(WORKLIST_PAGE, update_last_modified(worklist_text),
              "Bot: Marked pages as done on worklist")
    print("Done.")

if __name__ == "__main__":
    main()
