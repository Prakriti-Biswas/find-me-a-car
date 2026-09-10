#!/usr/bin/env python3
"""Find GTA Toyota Corolla Cross Hybrid listings from public web results.

This is a lead finder, not a guaranteed inventory feed. Search result snippets
can be stale, so open the source link and confirm the price, mileage, and trim.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from xml.etree import ElementTree
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GTA_LOCATIONS = (
    "Toronto",
    "Mississauga",
    "Brampton",
    "Markham",
    "Vaughan",
    "Richmond Hill",
    "Oakville",
    "Ajax",
    "Whitby",
    "Pickering",
    "Scarborough",
    "Etobicoke",
)

DEALER_SOURCES = (
    *tuple((city, f"https://{host}/{path}/Toyota-{model}.html")
           for city, host in (
               ("Woodbridge", "www.woodbridgetoyota.ca"),
               ("Maple", "www.mapletoyota.com"),
               ("Toronto", "www.yorkdaletoyota.com"),
           )
           for path in ("new/inventory", "used")
           for model in ("Corolla_Cross", "Corolla_Cross_Hybrid")),
    ("Toronto", "https://www.kenshawtoyota.ca/inventory/?model=corolla-cross"),
    ("Toronto", "https://www.downtowntoyota.ca/inventory/?model=corolla-cross"),
    ("Richmond Hill", "https://www.richmondhilltoyota.com/inventory/all?make=toyota&model=corolla+cross"),
    ("Mississauga", "https://dixietoyota.com/inventory"),
    ("Oakville", "https://www.oakvilletoyota.ca/en/all-inventory/toyota/corolla%20cross"),
    ("Whitby", "https://www.whitbytoyota.com/en/all-inventory/toyota/corolla%20cross"),
)


class StructuredDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.collecting = False
        self.parts: list[str] = []
        self.documents: list[object] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.collecting = dict(attrs).get("type") == "application/ld+json"
            self.parts = []

    def handle_data(self, data):
        if self.collecting:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.collecting:
            try:
                self.documents.append(json.loads("".join(self.parts)))
            except ValueError:
                pass
            self.collecting = False


def parse_dealer_inventory(html: str, location: str, source: str) -> list[Listing]:
    parser = StructuredDataParser()
    parser.feed(html)

    def objects(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from objects(child)
        elif isinstance(value, list):
            for child in value:
                yield from objects(child)

    listings = []
    for item in objects(parser.documents):
        title = clean_text(str(item.get("name", "")))
        description = clean_text(str(item.get("description", "")))
        combined = f"{title} {description}".lower()
        if "corolla cross" not in combined or "hybrid" not in combined or re.search(r"\bsold\b", combined):
            continue
        offers = item.get("offers", [])
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list):
            continue
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            url = offer.get("url", item.get("url", ""))
            if not isinstance(url, str) or not url.startswith("https://"):
                continue
            if str(offer.get("availability", "")).split("/")[-1] in {"SoldOut", "OutOfStock", "Discontinued"}:
                continue
            try:
                price = int(float(str(offer.get("price", "")).replace(",", "")))
            except (ValueError, OverflowError):
                price = None
            if offer.get("priceCurrency") != "CAD" or price is not None and not 15_000 <= price <= 100_000:
                price = None
            listings.append(Listing(description or title, price, location, url, description, source))
    return deduplicate(listings)


def search_dealer(location: str, source: str) -> list[Listing]:
    request = Request(source, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        return parse_dealer_inventory(response.read().decode("utf-8", errors="replace"), location, source)


@dataclass
class Listing:
    title: str
    price: int | None
    location: str
    url: str
    snippet: str
    query: str


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def extract_price(text: str) -> int | None:
    """Return the first plausible CAD asking price, ignoring monthly payments."""
    for match in re.finditer(r"(?:\$\s*|CAD\s+)(\d{2,3}(?:,\d{3})|\d{4,6})(?!\d)", text):
        start = max(0, match.start() - 20)
        context = text[start : match.end() + 20].lower()
        if any(word in context for word in ("/month", "monthly", "per month")):
            continue
        amount = int(match.group(1).replace(",", "").replace(".", ""))
        if 15_000 <= amount <= 100_000:
            return amount
    return None


def find_location(text: str) -> str:
    lowered = text.lower()
    for location in GTA_LOCATIONS:
        if location.lower() in lowered:
            return location
    return "GTA (confirm)"


def search_web(query: str, limit: int) -> list[Listing]:
    request = Request(
        "https://www.bing.com/search?" + urlencode({"format": "rss", "q": query}),
        headers={"User-Agent": "Mozilla/5.0 (compatible; CorollaCrossFinder/1.0)"},
    )
    with urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")
    root = ElementTree.fromstring(html)
    listings: list[Listing] = []
    for item in root.findall("./channel/item")[:limit]:
        title = clean_text(item.findtext("title", ""))
        snippet = clean_text(item.findtext("description", ""))
        url = item.findtext("link", "")
        combined = f"{title} {snippet}"
        listings.append(Listing(title, extract_price(combined), find_location(combined), url, snippet, query))
    return [
        listing for listing in listings
        if "corolla cross" in f"{listing.title} {listing.snippet}".lower()
        and "hybrid" in f"{listing.title} {listing.snippet}".lower()
    ]


def build_queries() -> list[str]:
    return [
        *(f'"Corolla Cross" "Hybrid" "{location}" for sale' for location in GTA_LOCATIONS),
        'site:autotrader.ca "Corolla Cross Hybrid" GTA',
        'site:carpages.ca "Corolla Cross Hybrid" Toronto',
    ]


def deduplicate(listings: list[Listing]) -> list[Listing]:
    seen: set[str] = set()
    unique: list[Listing] = []
    for listing in listings:
        key = listing.url.split("#", 1)[0].rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            unique.append(listing)
    return unique


def print_results(listings: list[Listing]) -> None:
    ranked = sorted(
        listings,
        key=lambda listing: listing.price if listing.price is not None else float("inf"),
    )
    print(f"Found {len(ranked)} unique leads, not a total of GTA availability. Prices are leads to verify.\n")
    for number, listing in enumerate(ranked, start=1):
        price = f"${listing.price:,.0f} CAD" if listing.price else "price not found"
        print(f"{number}. {price} | {listing.location} | {listing.title}")
        print(f"   {listing.url}")
        if listing.snippet:
            print(f"   {listing.snippet}")


def write_csv(path: str, listings: list[Listing]) -> None:
    if not listings:
        raise ValueError("No results to save; existing CSV was left untouched.")
    ranked = sorted(listings, key=lambda item: item.price or float("inf"))
    with open(path, "w", newline="", encoding="utf-8-sig") as output:
        writer = csv.writer(output)
        writer.writerow(("price_cad", "location", "title", "url", "snippet", "query"))
        for listing in ranked:
            writer.writerow((listing.price or "", listing.location, listing.title, listing.url, listing.snippet, listing.query))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-query", type=int, default=8, help="Results to read per web query")
    parser.add_argument("--csv", metavar="PATH", help="Also save results as a CSV file")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent source requests (1–8)")
    parser.add_argument("--coverage", metavar="PATH", help="Source status CSV (default: beside results CSV)")
    parser.add_argument("--dealer-source", nargs=2, action="append", default=[], metavar=("CITY", "URL"), help="Add a GTA dealer inventory page; repeat to add more")
    args = parser.parse_args()
    if args.per_query < 1:
        parser.error("--per-query must be greater than zero")
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be between 1 and 8")
    if any(not url.startswith("https://") for _, url in args.dealer_source):
        parser.error("--dealer-source URLs must start with https://")
    coverage_path = args.coverage or (str(Path(args.csv).with_suffix(".coverage.csv")) if args.csv else None)
    if coverage_path and args.csv and Path(coverage_path).resolve() == Path(args.csv).resolve():
        parser.error("--coverage and --csv must use different paths")

    all_listings: list[Listing] = []
    coverage = []
    dealers = list(dict.fromkeys((*DEALER_SOURCES, *map(tuple, args.dealer_source))))
    print(f"Checking {len(dealers)} dealer pages and {len(build_queries())} web queries...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(search_web, query, args.per_query): ("web", "GTA", query)
                   for query in build_queries()}
        futures.update({pool.submit(search_dealer, city, url): ("dealer", city, url)
                        for city, url in dealers})
        for future in as_completed(futures):
            kind, city, source = futures[future]
            try:
                rows = future.result()
                all_listings.extend(rows)
                status = "matches" if rows else "no_matches_or_unreadable"
                detail = "" if rows else "No matching parsable listings; this does not establish zero inventory."
                count = len(rows)
            except (OSError, ElementTree.ParseError, ValueError) as error:
                status, count, detail = "failed", 0, str(error)
            coverage.append((kind, city, source, status, count, detail))
            print(f"[{len(coverage)}/{len(futures)}] {city}: {status} ({count}) — {source}", file=sys.stderr)
    # Make duplicate selection stable despite concurrent completion order.
    all_listings.sort(key=lambda row: (row.url, row.price is None, row.query))
    results = deduplicate(all_listings)
    if coverage_path:
        with open(coverage_path, "w", newline="", encoding="utf-8-sig") as output:
            writer = csv.writer(output)
            writer.writerow(("source_type", "location", "source", "status", "matches", "detail"))
            writer.writerows(sorted(coverage))
        print(f"Saved coverage report: {coverage_path}")
    print_results(results)
    if not results:
        print("No matching results were returned. CSV was not written; any existing file is unchanged. Search may be blocked or inventory unavailable.", file=sys.stderr)
        return 1
    if args.csv:
        write_csv(args.csv, results)
        print(f"\nSaved CSV: {args.csv}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
