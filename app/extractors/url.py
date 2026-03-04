import httpx
import trafilatura

REDDIT_DOMAINS = ("reddit.com", "www.reddit.com", "old.reddit.com")


def extract_url(url: str) -> str:
    if any(domain in url for domain in REDDIT_DOMAINS):
        return _extract_reddit(url)
    return _extract_article(url)


def _extract_article(url: str) -> str:
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return ""
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
    return text or ""


def _extract_reddit(url: str) -> str:
    """Use Reddit's JSON API to get post + top comments."""
    clean_url = url.rstrip("/") + ".json?limit=10"
    headers = {"User-Agent": "SecondBrain/1.0"}
    try:
        response = httpx.get(clean_url, headers=headers, timeout=10)
        data = response.json()
        post = data[0]["data"]["children"][0]["data"]
        comments = data[1]["data"]["children"]

        parts = [
            f"Title: {post.get('title', '')}",
            f"Body: {post.get('selftext', '')}",
            "\nTop Comments:"
        ]
        for c in comments[:5]:
            body = c["data"].get("body", "")
            score = c["data"].get("score", 0)
            if body and score > 10:
                parts.append(f"- [{score} upvotes] {body}")

        return "\n".join(parts)
    except Exception:
        return ""
