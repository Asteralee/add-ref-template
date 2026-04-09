import requests
import re
import time
from datetime import datetime
import os
import random
import difflib

API_URL = "https://test.wikipedia.org/w/api.php"
TARGET_SECTION = "Reference list missing"
DELAY = 3.0
MAX_PAGES = 10
USER_AGENT = "ReflistBot/3.0 (https://simple.wikipedia.org/wiki/User:AsteraBot)"
WORKLIST_PAGE = "User:AsteraBot/Pages to fix"
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
    page = next(iter(data["query"]["pages"].values()))
    return page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")


def edit_page(title, text, summary):
    data = api_request("GET", {
        "action": "query",
        "meta": "tokens",
        "format": "json"
    })
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
    return f"'''Last modified''': {today} UTC\n\n{text}"


# 🔍 Detect both <references /> and {{reflist}}
def has_references_block(text):
    return (
        re.search(r"<references\s*/?>", text, re.IGNORECASE) or
        re.search(r"\{\{\s*reflist", text, re.IGNORECASE)
    )


# 🧠 Fuzzy match reference headings
def is_reference_heading(title):
    title = title.lower().strip()
    valid = ["references", "reference", "sources", "citations"]

    if title in valid:
        return True

    return bool(difflib.get_close_matches(title, valid, n=1, cutoff=0.75))


def fix_reflist(text):
    # Skip pages with no <ref>
    if not re.search(r"<ref", text, re.IGNORECASE):
        return None

    lines = text.split("\n")
    heading_regex = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$")

    sections = []
    current = {"title": None, "start": 0}

    # Parse sections
    for i, line in enumerate(lines):
        m = heading_regex.match(line.strip())
        if m:
            if current["title"] is not None:
                current["end"] = i
                sections.append(current)

            current = {
                "title": m.group(2).strip(),
                "start": i
            }

    if current["title"] is not None:
        current["end"] = len(lines)
        sections.append(current)

    see_also_idx = None
    external_idx = None
    ref_section = None

    for sec in sections:
        title_norm = sec["title"].lower().strip()

        if title_norm in ["see also", "related pages"]:
            see_also_idx = sec["end"]

        elif title_norm in ["external links", "other websites"]:
            external_idx = sec["start"]

        elif is_reference_heading(title_norm):
            ref_section = sec

    # ✅ CASE 1: Fix existing section
    if ref_section:
        start = ref_section["start"]
        end = ref_section["end"]

        section_lines = lines[start:end]

        # Remove existing reflists/references
        cleaned = []
        for line in section_lines[1:]:
            if has_references_block(line):
                continue
            cleaned.append(line)

        # Rebuild section
        new_section = ["== References ==", "{{reflist}}"]
        new_section.extend(cleaned)

        lines[start:end] = new_section
        return "\n".join(lines)

    # ✅ CASE 2: Insert new section
    if see_also_idx is not None:
        insert_index = see_also_idx
    elif external_idx is not None:
        insert_index = external_idx
    else:
        insert_index = len(lines)
        for i in range(len(lines) - 1, -1, -1):
            t = lines[i].strip()
            if (
                t.startswith("[[Category:") or
                t.startswith("{{DEFAULTSORT:") or
                t.startswith("{{")
            ):
                insert_index = i
            elif t == "":
                continue
            else:
                break

    ref_block = ["", "== References ==", "{{reflist}}", ""]
    new_lines = lines[:insert_index] + ref_block + lines[insert_index:]
    return "\n".join(new_lines)


# 🚀 Main
def main():
    login()

    worklist_text = get_page(WORKLIST_PAGE)
    if not worklist_text:
        print("Failed to fetch worklist page")
        return

    section_text = extract_section(worklist_text)
    pages = extract_pages(section_text)

    for title in pages[:MAX_PAGES]:
        print("Processing:", title)

        text = get_page(title)
        if not text:
            continue

        new_text = fix_reflist(text)
        if not new_text:
            continue

        edit_page(title, new_text, "Bot: Fixing References section")

        worklist_text = mark_done(worklist_text, title)
        time.sleep(DELAY + random.random())

    edit_page(
        WORKLIST_PAGE,
        update_last_modified(worklist_text),
        "Bot: Updated worklist"
    )

    print("Done.")


if __name__ == "__main__":
    main()
