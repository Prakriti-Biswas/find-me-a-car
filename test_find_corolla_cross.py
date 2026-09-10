import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import find_corolla_cross as finder


class FinderTests(unittest.TestCase):
    def test_inventory_filters_and_deduplicates(self):
        def car(name, price, url, availability="InStock"):
            return {"name": name, "offers": {"url": url, "price": price,
                    "priceCurrency": "CAD", "availability": availability}}
        hybrid = car("2024 Toyota Corolla Cross Hybrid", "38,998", "https://dealer.ca/1")
        data = {"@graph": [hybrid, hybrid,
                car("2026 Toyota Corolla Cross Gas", 35000, "https://dealer.ca/2"),
                car("2026 Toyota Corolla Cross Hybrid", 40000, "https://dealer.ca/3", "SoldOut")]}
        rows = finder.parse_dealer_inventory(
            '<script type="application/ld+json">' + json.dumps(data) + '</script>',
            "Maple", "https://dealer.ca")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].price, 38998)

    def test_csv_round_trip_and_empty_run_preserves_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            row = finder.Listing('Toyota, "Hybrid"', 38998, "Maple", "https://dealer.ca/1",
                                 "Line one\nLine two — details", "query")
            finder.write_csv(str(path), [row])
            with path.open(encoding="utf-8-sig", newline="") as stream:
                saved = list(csv.DictReader(stream))
            self.assertEqual(saved[0]["title"], row.title)
            self.assertEqual(saved[0]["snippet"], row.snippet)
            before = path.read_bytes()
            with patch("sys.argv", ["finder", "--csv", str(path)]), \
                 patch.object(finder, "search_web", return_value=[]), \
                 patch.object(finder, "search_dealer", return_value=[]):
                self.assertEqual(finder.main(), 1)
            self.assertEqual(path.read_bytes(), before)

    def test_dealers_run_even_when_web_finds_results_and_failures_are_reported(self):
        row = finder.Listing("Corolla Cross Hybrid", 35000, "Toronto",
                             "https://dealer.ca/1", "Hybrid", "query")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            with patch("sys.argv", ["finder", "--csv", str(path)]), \
                 patch.object(finder, "build_queries", return_value=["query"]), \
                 patch.object(finder, "DEALER_SOURCES", (("Toronto", "https://dealer.ca"),)), \
                 patch.object(finder, "search_web", return_value=[row]), \
                 patch.object(finder, "search_dealer", side_effect=OSError("blocked")) as dealer:
                self.assertEqual(finder.main(), 0)
            dealer.assert_called_once()
            with path.with_suffix(".coverage.csv").open(encoding="utf-8-sig") as stream:
                coverage = list(csv.DictReader(stream))
            self.assertEqual(coverage[0]["status"], "failed")
            self.assertEqual(coverage[0]["detail"], "blocked")

    def test_mileage_is_not_a_price(self):
        self.assertIsNone(finder.extract_price("2024 Hybrid 38,998 km"))
        self.assertEqual(finder.extract_price("38,998 km; $32,500 CAD"), 32500)


if __name__ == "__main__":
    unittest.main()
