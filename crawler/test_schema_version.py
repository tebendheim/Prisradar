"""Versjonskravet i demand.py, crawler.js og app.js må følge den høyeste migreringen."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def latest_migration():
    names = [p.stem for p in (ROOT / "supabase" / "migrations").glob("*.sql") if re.fullmatch(r"\d{10}", p.stem)]
    return max(int(n) for n in names)


class SchemaVersionTest(unittest.TestCase):
    def check(self, rel, pattern):
        text = (ROOT / rel).read_text()
        versions = {int(v) for v in re.findall(r"\b(20\d{8})\b", text)}
        self.assertIn(latest_migration(), versions, f"{rel} må kreve {latest_migration()}")
        self.assertEqual(versions, {latest_migration()}, f"{rel} refererer til gammel schema-versjon")
        self.assertRegex(text, pattern)

    def test_demand(self):
        self.check("crawler/demand.py", r"version\",0\)<\d{10}")

    def test_crawler_function(self):
        self.check("functions/api/crawler.js", r"health\.version>=\d{10}")

    def test_frontend(self):
        self.check("web/app.js", r"const REQUIRED_SCHEMA_VERSION\s*=\s*\d{10}")


if __name__ == "__main__":
    unittest.main()
