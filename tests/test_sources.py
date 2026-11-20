"""Source adapter tests use fictional Atom/README responses and no network or state."""
from pathlib import Path
import sys
import sqlite3
from unittest.mock import patch
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bidradar
import research

SHA = "a" * 40
ATOM_URL = "https://github.com/example/research/commits/main.atom"
RAW_URL = f"https://raw.githubusercontent.com/example/research/{SHA}/README.md"


def atom(url=None, date="2026-11-10T01:00:00Z"):
    url = url or f"https://github.com/example/research/commit/{SHA}"
    return (f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>{url}</id>'
            f'<title>Update research</title><updated>{date}</updated>'
            f'<link href="{url}"/><content type="html">README updated</content>'
            '</entry></feed>').encode()


class FakeFetcher:
    def __init__(self, responses):
        self.responses, self.urls = responses, []

    def get(self, url, accept="application/json"):
        self.urls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.source = {"id": "fictional", "kind": "github_curated", "publisher": "Example research",
                       "repos": [{"name": "example/research", "ref": "main", "readme": "README.md"}]}
        self.fetch = FakeFetcher({ATOM_URL: atom(), RAW_URL: b"# Research\nFull README evidence."})

    def test_readme_is_pinned_to_atom_commit_and_not_a_new_paper(self):
        items, note = bidradar.source_articles(self.source, self.fetch, "2026-11-01T00:00:00+00:00")
        self.assertEqual(self.fetch.urls, [ATOM_URL, RAW_URL])
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["text"], "# Research\nFull README evidence.")
        self.assertEqual(item["published"], "")
        self.assertEqual(item["updated"], "2026-11-10T01:00:00+00:00")
        self.assertEqual(item["date_basis"], "repository_commit")
        self.assertEqual(item["stable_id"], "github:example/research")
        record = {**item, "related_urls": [item["url"]], "research_id": "test", "content_hash": "test"}
        novelty = research._novelty(record, [], "2026-11-01", "2026-11-20")
        self.assertNotIn("new_research", novelty["allowed_types"])
        self.assertIn("精选", note)

    def test_stale_commit_does_not_fetch_readme(self):
        items, note = bidradar.source_articles(self.source, self.fetch, "2026-11-11T00:00:00+00:00")
        self.assertEqual(items, [])
        self.assertEqual(self.fetch.urls, [ATOM_URL])
        self.assertIn("早于", note)

    def test_forged_atom_commit_cannot_choose_a_different_repo(self):
        self.fetch.responses[ATOM_URL] = atom(f"https://github.com/other/research/commit/{SHA}")
        with self.assertRaisesRegex(bidradar.NetworkError, "curated_repositories_unavailable"):
            bidradar.source_articles(self.source, self.fetch, "2026-11-01T00:00:00+00:00", "2026-11-20T00:00:00+00:00")
        self.assertEqual(self.fetch.urls, [ATOM_URL])

    def test_invalid_repo_paths_are_rejected_before_network(self):
        for field, value in [("name", "example/.."), ("name", "https://evil.test/x"),
                             ("ref", "../../main"), ("readme", "../README.md")]:
            with self.subTest(field=field, value=value):
                self.source["repos"] = [{"name": "example/research", field: value}]
                with self.assertRaises(ValueError):
                    bidradar.source_articles(self.source, self.fetch, "2026-11-01T00:00:00+00:00", "2026-11-20T00:00:00+00:00")
                self.assertEqual(self.fetch.urls, [])

    def test_html_error_body_is_not_repository_text(self):
        self.fetch.responses[RAW_URL] = b"<!DOCTYPE html><html>Error</html>"
        with self.assertRaises(bidradar.NetworkError):
            bidradar.source_articles(self.source, self.fetch, "2026-11-01T00:00:00+00:00", "2026-11-20T00:00:00+00:00")

    def test_partial_failure_is_reported_and_success_preserved(self):
        self.source["repos"].append({"name": "example/missing"})
        self.fetch.responses["https://github.com/example/missing/commits/main.atom"] = bidradar.NetworkError("http_404")
        with self.assertRaises(bidradar.SourcePartialError) as caught:
            bidradar.source_articles(self.source, self.fetch, "2026-11-01T00:00:00+00:00", "2026-11-20T00:00:00+00:00")
        self.assertEqual(len(caught.exception.items), 1)
        self.assertIn("1 个仓库读取失败", caught.exception.note)

    def test_frozen_window_uses_older_in_window_commit(self):
        future = atom(f"https://github.com/example/research/commit/{'b' * 40}", "2026-11-21T01:00:00Z")
        self.fetch.responses[ATOM_URL] = future.replace(b'</feed>', b'') + atom().split(b'>', 1)[1]
        items, _ = bidradar.source_articles(self.source, self.fetch,
                                            "2026-11-05T00:00:00+00:00", "2026-11-20T00:00:00+00:00")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["updated"], "2026-11-10T01:00:00+00:00")
        self.assertEqual(self.fetch.urls, [ATOM_URL, RAW_URL])

    def test_window_includes_exact_timestamp_boundaries(self):
        for boundary in ["2026-11-05T00:00:00Z", "2026-11-20T00:00:00Z"]:
            with self.subTest(boundary=boundary):
                self.fetch.responses[ATOM_URL] = atom(date=boundary)
                items, _ = bidradar.source_articles(self.source, self.fetch,
                                                    "2026-11-05T00:00:00+00:00", "2026-11-20T00:00:00+00:00")
                self.assertEqual(len(items), 1)

    def test_collect_keeps_partial_items_and_marks_error_until_recovery(self):
        # Minimal in-memory schema only; never call connect() or touch user state.
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        db.executescript("""
          CREATE TABLE items (id TEXT PRIMARY KEY,stable_id TEXT,title_key TEXT,content_hash TEXT,
                              payload TEXT,priority INTEGER,eligible INTEGER,first_seen TEXT);
          CREATE TABLE item_sources (item_id TEXT,source_id TEXT,first_seen TEXT,PRIMARY KEY(item_id,source_id));
          CREATE TABLE sources (id TEXT PRIMARY KEY,last_attempt TEXT,last_success TEXT,last_error TEXT,
                                item_count INTEGER,note TEXT);
        """)
        db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                   ("fictional", "2026-11-01", "2026-11-01", None, 0, ""))
        self.source["repos"].append({"name": "example/missing"})
        self.fetch.responses["https://github.com/example/missing/commits/main.atom"] = bidradar.NetworkError("http_404")
        cfg = {"sources": [self.source], "_window_start": "2026-11-05T00:00:00+00:00",
               "_window_end": "2026-11-20T00:00:00+00:00"}
        with patch.object(bidradar, "Fetcher", return_value=self.fetch):
            bidradar.collect(db, cfg)
        row = db.execute("SELECT * FROM sources").fetchone()
        self.assertEqual(row["last_error"], "curated_repositories_partial_1_of_2")
        self.assertEqual(row["last_success"], "2026-11-01")
        self.assertEqual(row["item_count"], 1)
        self.assertEqual(db.execute("SELECT count(*) FROM items").fetchone()[0], 1)
        self.assertIn("curated_repositories_partial", bidradar.source_issues(db, cfg, errors_only=True)[0])
        # A resumed pipeline must retry this partial source; forbid downstream delivery/model work.
        self.fetch.responses["https://github.com/example/missing/commits/main.atom"] = atom().replace(
            b"example/research", b"example/missing")
        self.fetch.responses[f"https://raw.githubusercontent.com/example/missing/{SHA}/README.md"] = b"# Recovered README"
        with patch.object(bidradar, "Fetcher", return_value=self.fetch), patch.object(
                bidradar, "connected", return_value=False):
            self.assertFalse(bidradar.run_pipeline(db, cfg, resume=True))
        row = db.execute("SELECT * FROM sources").fetchone()
        self.assertIsNone(row["last_error"])
        self.assertNotEqual(row["last_success"], "2026-11-01")
        self.assertEqual(bidradar.source_issues(db, cfg, errors_only=True), [])
        self.assertEqual(db.execute("SELECT count(*) FROM items").fetchone()[0], 2)

    def test_exact_host_allowlist_and_example_sources(self):
        self.assertIn("github.com", bidradar.ALLOWED_HOSTS)
        self.assertIn("raw.githubusercontent.com", bidradar.ALLOWED_HOSTS)
        self.assertFalse(bidradar.public_link(RAW_URL))
        self.assertFalse(bidradar.public_link("https://github.com.evil.test/example/research"))
        cfg = tomllib.loads((Path(bidradar.__file__).parent / "config.example.toml").read_text())
        sources = {s["id"]: s for s in cfg["sources"]}
        self.assertNotIn("kuaishou-tech", sources)
        for source_id in ["alimama-public", "kuaishou-research", "tencent-ads-research", "bytedance-public"]:
            self.assertEqual(sources[source_id]["kind"], "github_curated")
        self.assertIn("alimama-tech/ISGE", {r["name"] for r in sources["alimama-public"]["repos"]})


if __name__ == "__main__":
    unittest.main()
