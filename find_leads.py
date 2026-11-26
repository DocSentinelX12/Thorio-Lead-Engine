"""Find recent business-intent posts and save human-reviewed drafts to Airtable."""
import os
import re
import sys
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import yaml

PARTNERS = ("Shiftr", "Paxus", "Thorio", "Astrivon Labs")
INTENT = (
    "hiring", "looking for a developer", "need a developer", "need developers",
    "looking for developers", "need an engineer", "looking for an engineer",
    "contractor", "contractors", "dev agency", "development agency",
    "build an mvp", "building an mvp", "build my app", "build our app",
    "technical cofounder", "software team", "engineering team", "freelance developer",
    "mobile app developer", "web developer", "software development", "outsourcing development",
)
NEGATIVE = (
    "looking for a job", "looking for work", "open to work", "hire me",
    "my resume", "my cv", "recruiter looking", "i am a recruiter",
    "we are recruiting", "we're recruiting", "recruitment agency",
    "staffing agency", "recruiter", "we recruit", "dm me for candidates", "apply now",
)
SPAM = ("giveaway", "airdrop", "crypto signal", "赚", "telegram group", "click my bio")


def load_keywords(path="keywords.yaml"):
    with open(path, encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    return {name: [str(word).strip() for word in data.get(name, {}).get("keywords", []) if str(word).strip()]
            for name in PARTNERS}


def normalize(value):
    return " ".join(str(value or "").lower().split())


def partner_match(post_text, keywords):
    text = normalize(post_text)
    scores = {}
    for partner, terms in keywords.items():
        scores[partner] = sum(1 for term in terms if re.search(
            r"(?<![a-z0-9])" + re.escape(normalize(term)) + r"(?![a-z0-9])", text
        ))
    best = max(scores, key=scores.get) if scores else None
    return best if best and scores[best] else None


def is_duplicate(post_url, handle, seen_posts, seen_handles):
    return normalize(post_url) in seen_posts or (
        bool(handle) and normalize(handle).lstrip("@") in seen_handles
    )


def is_real_need(text):
    value = normalize(text)
    if any(term in value for term in NEGATIVE + SPAM):
        return False
    return any(term in value for term in INTENT)


def recent(timestamp):
    try:
        value = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - timedelta(days=7) <= value <= datetime.now(timezone.utc) + timedelta(minutes=5)
    except (TypeError, ValueError):
        return False


def draft_message(name, post_text):
    excerpt = re.sub(r"\s+", " ", str(post_text)).strip()
    excerpt = excerpt[:150].rstrip()
    greeting = f"Hi {name}," if name else "Hi there,"
    return f"{greeting} I saw your post: "{excerpt}". I thought it might be useful to connect. Would you be open to a quick conversation?"


def request_json(url, token, params=None, token_in_query=False):
    params = dict(params or {})
    headers = {}
    if token_in_query:
        params["access_token"] = token
    else:
        headers["Authorization"] = f"Bearer {token}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def search_x(keywords):
    token = os.getenv("X_BEARER_TOKEN")
    if not token:
        print("X skipped: add the X_BEARER_TOKEN secret in GitHub Actions.")
        return []
    posts = []
    for term in keywords:
        try:
            query = f'"{term}" -is:retweet'
            data = request_json("https://api.x.com/2/tweets/search/recent", token, {
                "query": query, "max_results": "100",
                "tweet.fields": "created_at,author_id",
                "expansions": "author_id", "user.fields": "name,username",
            })
            users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
            for item in data.get("data", []):
                user = users.get(item.get("author_id"), {})
                posts.append({
                    "platform": "X", "id": item.get("id"),
                    "text": item.get("text", ""), "timestamp": item.get("created_at"),
                    "name": user.get("name") or user.get("username", ""),
                    "handle": user.get("username", ""),
                    "profile": f'https://x.com/{user["username"]}' if user.get("username") else "",
                    "url": f'https://x.com/{user["username"]}/status/{item["id"]}' if user.get("username") else "",
                })
        except Exception as exc:
            print(f"X search warning for '{term}': {exc}")
    return posts


def search_threads(keywords):
    token = os.getenv("THREADS_ACCESS_TOKEN")
    if not token:
        print("Threads skipped: add the THREADS_ACCESS_TOKEN secret in GitHub Actions.")
        return []
    posts = []
    for term in keywords:
        try:
            data = request_json("https://graph.threads.com/v1.0/keyword_search", token, {
                "q": term, "search_type": "RECENT", "limit": "100",
                "fields": "id,text,permalink,timestamp,username",
                "since": str(int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())),
            }, token_in_query=True)
            for item in data.get("data", []):
                username = item.get("username", "")
                posts.append({
                    "platform": "Threads", "id": item.get("id"),
                    "text": item.get("text", ""), "timestamp": item.get("timestamp"),
                    "name": username, "handle": username,
                    "profile": f"https://www.threads.net/@{username}" if username else "",
                    "url": item.get("permalink", ""),
                })
        except Exception as exc:
            print(f"Threads search warning for '{term}': {exc}")
    return posts


def airtable_request(method, url, payload=None):
    token = os.getenv("AIRTABLE_API_KEY")
    if not token:
        raise RuntimeError("AIRTABLE_API_KEY is missing.")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8")) if response.status != 204 else {}


def airtable_url():
    base = os.getenv("AIRTABLE_BASE_ID")
    if not base:
        raise RuntimeError("AIRTABLE_BASE_ID is missing.")
    table = urllib.parse.quote(os.getenv("AIRTABLE_LEAD_TABLE", "Lead Radar"), safe="")
    return f"https://api.airtable.com/v0/{base}/{table}"


def existing_leads(url):
    seen_posts, seen_handles = set(), set()
    next_page = None
    while True:
        params = {"pageSize": 100, "fields[]": ["Post link", "Handle"]}
        if next_page:
            params["offset"] = next_page
        page_url = url + "?" + urllib.parse.urlencode(params, doseq=True)
        page = airtable_request("GET", page_url)
        for record in page.get("records", []):
            fields = record.get("fields", {})
            if fields.get("Post link"):
                seen_posts.add(normalize(fields["Post link"]))
            if fields.get("Handle"):
                seen_handles.add(normalize(fields["Handle"]).lstrip("@"))
        next_page = page.get("offset")
        if not next_page:
            break
    return seen_posts, seen_handles


def save_lead(url, lead):
    fields = {
        "Date found": datetime.now(timezone.utc).date().isoformat(),
        "Platform": lead["platform"], "Name": lead["name"],
        "Handle": lead["handle"], "Profile link": lead["profile"],
        "Post link": lead["url"], "Post text": lead["text"],
        "Partner": lead["partner"], "Why they match": lead["reason"],
        "Draft message": lead["draft"], "Status": "New",
    }
    airtable_request("POST", url, {"records": [{"fields": fields}]})


def main():
    try:
        keywords = load_keywords()
    except Exception as exc:
        print(f"Could not load keywords.yaml: {exc}")
        return 1

    search_terms = list(dict.fromkeys(term for partner in PARTNERS for term in keywords[partner]))
    posts = search_x(search_terms) + search_threads(search_terms)
    seen_ids, candidates = set(), []
    for post in posts:
        text = post.get("text", "")
        identity = (post["platform"], post.get("id"))
        if identity in seen_ids or not post.get("url") or not recent(post.get("timestamp")):
            continue
        seen_ids.add(identity)
        if not is_real_need(text):
            continue
        partner = partner_match(text, keywords)
        if not partner:
            continue
        post["partner"] = partner
        post["reason"] = f"Your post mentions a business need and matches {partner} keywords."
        post["draft"] = draft_message(post.get("name"), text)
        candidates.append(post)

    try:
        url = airtable_url()
        seen_posts, seen_handles = existing_leads(url)
    except Exception as exc:
        print(f"Airtable lookup failed: {exc}")
        return 0

    saved, skipped = 0, 0
    for lead in candidates:
        post_url = normalize(lead["url"])
        handle = normalize(lead["handle"]).lstrip("@")
        if is_duplicate(post_url, handle, seen_posts, seen_handles):
            skipped += 1
            continue
        if saved >= 40:
            break
        try:
            save_lead(url, lead)
            seen_posts.add(post_url)
            if handle:
                seen_handles.add(handle)
            saved += 1
        except Exception as exc:
            print(f"Could not save lead from {lead['platform']} to Airtable: {exc}")
    print(f"Finished: saved {saved} new leads; skipped {skipped} duplicates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
