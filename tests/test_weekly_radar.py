import datetime as dt
import unittest
from unittest.mock import patch

import weekly_radar as radar


class WeeklyRadarTests(unittest.TestCase):
    def test_atom_canonicalizes_arxiv_versions_and_keeps_first_publication(self):
        raw = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <title>Automated bidding</title><id>http://arxiv.org/abs/2611.12345v2</id>
        <published>2026-11-01T00:00:00Z</published><updated>2026-11-24T00:00:00Z</updated>
        <summary>A method</summary></entry></feed>'''
        row = radar.parse_feed(raw)[0]
        self.assertEqual(row['url'], 'https://arxiv.org/abs/2611.12345')
        self.assertTrue(row['date'].startswith('2026-11-01'))

    def test_collect_excludes_old_future_invalid_and_undated_items(self):
        items = ''.join('<item><title>LLM reasoning</title><link>https://example.com/{}</link>{}</item>'.format(
            i, '<pubDate>' + date + '</pubDate>' if date else '')
            for i, date in enumerate(['2026-11-20T00:00:00Z', '2026-11-01T00:00:00Z',
                                      '2026-11-30T00:00:00Z', '', 'invalid']))
        raw = ('<rss><channel>' + items + '</channel></rss>').encode()
        start = dt.datetime(2026, 11, 17, tzinfo=dt.timezone.utc)
        end = start + dt.timedelta(days=7)
        with patch.object(radar, 'curl_request', return_value=(200, {}, raw)):
            rows, status = radar.collect(radar.SOURCES[1], start, end)
        self.assertTrue(status['ok'])
        self.assertEqual(len(rows), 1)
        self.assertIn('缺日期 2', status['note'])

    def test_http_failure_is_not_reported_as_no_updates(self):
        end = dt.datetime.now(dt.timezone.utc)
        with patch.object(radar, 'curl_request', return_value=(429, {}, b'')):
            rows, status = radar.collect(radar.SOURCES[1], end, end)
        self.assertFalse(status['ok'])
        self.assertIn('http_429', status['note'])
        self.assertEqual(rows, [])

    def test_selection_deduplicates_caps_sources_and_excludes_prereleases(self):
        self.assertIsNone(radar.classify(dict(title='0.9.0-alpha.1', text='coding'), 'tools'))
        self.assertIsNone(radar.classify(dict(title='A new bidirectional encoder', text=''), 'research'))
        rows = [dict(url='https://x/' + str(i), lane='tools', score=3,
                     date='2026-11-20', source_id='repo') for i in range(10)]
        rows += [dict(rows[0])]
        self.assertEqual(len(radar.select(rows)), 2)

    def test_arxiv_query_contains_explicit_week_window(self):
        start = dt.datetime(2026, 11, 17, tzinfo=dt.timezone.utc)
        query = radar.urllib.parse.parse_qs(radar.urllib.parse.urlsplit(
            radar.source_url(radar.SOURCES[0], start, start + dt.timedelta(days=7))).query)
        self.assertIn('submittedDate:[202611170000 TO 202611240000]', query['search_query'][0])


if __name__ == '__main__':
    unittest.main()
