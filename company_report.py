import json
import os
import re
import sys
from typing import Any
from urllib.parse import urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen


TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
TAVILY_ENDPOINT = "https://api.tavily.com/search"

EXCLUDED_DOMAINS = {
    "wikipedia.org",
    "linkedin.com",
    "forbes.com",
    "bloomberg.com",
    "reuters.com",
    "statista.com",
    "crunchbase.com",
    "youtube.com",
    "reddit.com",
    "glassdoor.com",
    "zoominfo.com",
    "quora.com",
    "medium.com",
}


def sanitize_domain(url: str) -> str:
    """Extract a normalized hostname from a URL."""
    value = url.strip()
    if not value:
        return ""

    parsed = urlparse(value if "://" in value else f"//{value}")
    try:
        hostname = parsed.hostname or ""
    except ValueError:
        return ""

    return hostname.lower().rstrip(".").removeprefix("www.")


def run_tavily_query(payload: dict[str, Any]) -> dict[str, Any]:
    """Post a search payload to Tavily and return its JSON response."""
    headers = {
        "Authorization": f"Bearer {TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }
    request = Request(
        TAVILY_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not isinstance(data, dict):
        raise ValueError("Tavily returned an unexpected response format.")
    return data


def _is_excluded_domain(domain: str) -> bool:
    return any(
        domain == excluded or domain.endswith(f".{excluded}")
        for excluded in EXCLUDED_DOMAINS
    )


def fetch_top_companies(
    industry: str, country: str, limit: int = 10
) -> list[dict[str, str]]:
    """Find company names and their canonical domains."""
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    query = (
        f"top major {industry} manufacturing companies in {country} "
        "official website"
    )
    payload = {
        "query": query,
        "search_depth": "advanced",
        "max_results": 20,
        "topic": "general",
    }

    try:
        data = run_tavily_query(payload)
    except (URLError, TimeoutError) as error:
        print(f"[!] Error fetching companies: {error}", file=sys.stderr)
        return []

    companies = []
    seen_domains = set()

    for item in data.get("results", []):
        url = item.get("url", "")
        domain = sanitize_domain(url)

        if not domain or domain in seen_domains or _is_excluded_domain(domain):
            continue

        raw_title = item.get("title", "")
        clean_name = re.split(r"[-|–—:•]", raw_title)[0].strip()
        if not clean_name:
            clean_name = domain.split(".")[0].capitalize()

        seen_domains.add(domain)
        companies.append(
            {
                "company_name": clean_name,
                "domain": domain,
                "website": f"https://{domain}",
            }
        )

        if len(companies) >= limit:
            break

    return companies


def fetch_company_pdfs(domain: str, max_pdfs: int = 5) -> list[str]:
    """Find direct PDF links hosted on the company domain."""
    if max_pdfs < 1:
        raise ValueError("max_pdfs must be at least 1.")

    query = (
        "annual report OR whitepaper OR investor presentation OR "
        "sustainability report filetype:pdf"
    )
    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": max_pdfs,
        "include_domains": [domain],
    }

    try:
        data = run_tavily_query(payload)
    except (URLError, TimeoutError) as error:
        print(f"[!] Error fetching PDFs for {domain}: {error}", file=sys.stderr)
        return []

    pdf_urls = []
    for result in data.get("results", []):
        url = result.get("url", "")
        if urlparse(url).path.lower().endswith(".pdf"):
            pdf_urls.append(url)

    return list(dict.fromkeys(pdf_urls))


def generate_company_report(
    industry: str,
    country: str,
    output_file: str = "output.json",
) -> dict[str, Any]:
    """Search for companies, find PDFs, display results, and save JSON."""
    if not TAVILY_API_KEY:
        raise ValueError(
            "Set a valid TAVILY_API_KEY environment variable before running."
        )

    print(f"[*] Searching for top 10 {industry} companies in {country}...")
    companies = fetch_top_companies(industry, country, limit=10)

    if not companies:
        print("[!] No companies found. Check the query or API key status.")
        return {}

    final_records = []
    for index, company in enumerate(companies, 1):
        domain = company["domain"]
        print(
            f"[{index}/{len(companies)}] Fetching PDF documents for "
            f"{company['company_name']} ({domain})..."
        )
        pdfs = fetch_company_pdfs(domain)

        final_records.append(
            {
                "company_name": company["company_name"],
                "domain": domain,
                "website": company["website"],
                "pdf_documents": pdfs,
            }
        )

    structured_result = {
        "query_parameters": {
            "industry": industry,
            "country": country,
        },
        "total_companies": len(final_records),
        "companies": final_records,
    }

    with open(output_file, "w", encoding="utf-8") as output:
        json.dump(structured_result, output, indent=2, ensure_ascii=False)

    print(f"\n[✓] Search complete. Results saved to {output_file}")
    return structured_result


if __name__ == "__main__":
    INDUSTRY = "Robotics"
    COUNTRY = "Japan"
    OUTPUT_FILENAME = "japan_robotics_companies.json"

    try:
        result = generate_company_report(
            industry=INDUSTRY,
            country=COUNTRY,
            output_file=OUTPUT_FILENAME,
        )
    except (ValueError, URLError, TimeoutError) as error:
        print(f"[!] {error}", file=sys.stderr)
        sys.exit(1)

    if result:
        print("\n--- JSON Output ---")
        print(json.dumps(result, indent=2, ensure_ascii=False))
