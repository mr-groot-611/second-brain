import httpx

REDDIT_DOMAINS = ("reddit.com", "www.reddit.com", "old.reddit.com")
JINA_BASE = "https://r.jina.ai/"


def extract_url(url: str) -> str:
    """Extract content from a URL. Returns empty string if extraction fails.
    Strategy:
    - Reddit URLs: try JSON API first (richer content + comments), fall back to Jina
    - All other URLs: Jina AI Reader (handles JS rendering, redirects, most URL types)
    """
    if any(domain in url for domain in REDDIT_DOMAINS):
        content = _extract_reddit(url)
        if content:
            return content
        # Fall back to Jina if Reddit JSON API fails
        return _extract_via_jina(url)

    return _extract_via_jina(url)


def _extract_via_jina(url: str) -> str:
    """Use Jina AI Reader to extract clean markdown from any URL.
    Handles JS-rendered pages, redirects, share links, paywalls, etc.
    No API key required.
    """
    try:
        response = httpx.get(
            f"{JINA_BASE}{url}",
            timeout=20,
            headers={
                "Accept": "text/plain",
                "X-Return-Format": "markdown",
            },
            follow_redirects=True,
        )
        if response.status_code == 200:
            return response.text.strip()
        return ""
    except Exception:
        return ""


def _extract_reddit(url: str) -> str:
    """Use Reddit's JSON API for richer content (post + top comments).
    Resolves share links (/s/ format) via redirect before applying the JSON trick.
    """
    try:
        # Resolve redirects first — handles share links like /r/sub/s/abc123
        resolved = httpx.get(
            url,
            follow_redirects=True,
            timeout=10,
            headers={"User-Agent": "SecondBrain/1.0"},
        )
        resolved_url = str(resolved.url)
    except Exception:
        resolved_url = url

    # Strip query params and append .json
    clean_url = resolved_url.rstrip("/").split("?")[0] + ".json?limit=10"
    try:
        response = httpx.get(
            clean_url,
            headers={"User-Agent": "SecondBrain/1.0"},
            timeout=10,
        )
        data = response.json()
        post = data[0]["data"]["children"][0]["data"]
        comments = data[1]["data"]["children"]

        parts = [
            f"Title: {post.get('title', '')}",
            f"Subreddit: r/{post.get('subreddit', '')}",
            f"Body: {post.get('selftext', '')}",
            "\nTop Comments:",
        ]
        for c in comments[:5]:
            body = c["data"].get("body", "")
            score = c["data"].get("score", 0)
            if body and score > 10:
                parts.append(f"- [{score} upvotes] {body}")

        return "\n".join(parts)
    except Exception:
        return ""
