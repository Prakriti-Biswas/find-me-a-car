# GTA Corolla Cross Hybrid finder

This small Python program searches public web results for new, used, and
pre-owned Toyota Corolla Cross Hybrid listings around the Greater Toronto Area,
then ranks the results by any price found in the title or snippet.

It is intentionally a lead finder rather than a guaranteed inventory API:
search results may be stale, prices may exclude fees, and some dealers may not
appear in the results. Always open the source link and confirm availability,
trim, mileage, taxes, fees, and whether the vehicle is actually a hybrid.

## Run it

```bash
python3 find_corolla_cross.py --csv corolla-cross-results.csv
```

Use `--per-query 12` to inspect more results per search. The terminal output
shows the cheapest prices first, followed by each source link and snippet.

Every run checks 18 dealer pages across nine dealerships, alongside 14 web
queries covering all 12 GTA locations above. Dealer searches no longer have
model-year restrictions and run even when web search finds matches.
Sources include Woodbridge, Maple, Yorkdale, Ken Shaw, Downtown, Richmond Hill,
Dixie, Oakville, and Whitby Toyota. Woodbridge, Maple, and Yorkdale have separate
new/used and Cross/Cross Hybrid pages; other sources use combined inventory.

This is still partial coverage: sites may block requests, require JavaScript,
omit structured vehicle data, or paginate results. The finder reads the
configured inventory pages; it does not crawl all result pages or detail pages.
It only extracts matching vehicles from public JSON-LD offers.

Each CSV run also writes `corolla-cross-results.coverage.csv`, showing matches,
failed sources, and pages with no matching parsable listings. A zero source
count does **not** mean the dealer has no cars. Use `--coverage PATH` to change
the report location. Requests run with four workers by default (`--workers 1`
for sequential requests, maximum eight).

Add another GTA dealer without editing Python:

```bash
python3 find_corolla_cross.py --csv corolla-cross-results.csv \
  --dealer-source Toronto https://dealer.example/inventory/
```

Replace the example URL with a real inventory page. Repeat `--dealer-source`
for additional sources; the page must expose vehicle offers as JSON-LD.

The CSV contains one row per lead, sorted by price, and uses UTF-8 with a BOM
for Excel compatibility. Open it in Excel or Numbers to see columns; a code
editor displays the raw comma-separated text.

If every source fails or returns no matches, the script exits with an error
and leaves your existing CSV untouched instead of replacing it with headers.
Blank prices mean no CAD asking price was found. Dealer listings may still
be stale; confirm availability and final pricing through the source link.

Run regression checks with `python3 -m unittest -v`.
