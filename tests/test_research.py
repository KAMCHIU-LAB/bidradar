"""Offline contract checks; all research content below is deliberately fictional."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research


def fixture(count=1, *, body_limit=2000, item_limit=20):
    records, cards, triage = [], [], []
    for n in range(count):
        key = str(n)
        records.append({"id": key, "title": f"虚构研究{n}", "url": f"https://example.org/paper/{n}",
                        "company": "unassigned", "text": "采用条件扩散。离线成本下降。作者报告。",
                        "research_id": f"study-{n}", "content_hash": f"hash-{n}",
                        "related_urls": [f"https://example.org/paper/{n}"],
                        "kind": "abstract", "attribution": "归属未核实", "original_chars": 22, "truncated": False,
                        "novelty": {"allowed_types": ["first_seen"], "status": "not_in_published_history", "previous": None}})
        basis = {k: {"score": v, "reason": "虚构测试依据"} for k, v in
                 {"technology": 2, "evidence": 3, "industrial": 3, "business": 5, "technical_fit": 3, "transfer": 1}.items()}
        cards.append({"id": key, "title": f"虚构{n}", "change_type": "first_seen", "lane": "main",
                      "technology": "条件扩散出价", "outcome": "离线成本下降", "boundary": "作者报告",
                      "why_read": "借鉴出价轨迹生成",
                      "quality": 8, "relevance": 9, "score_basis": basis,
                      "evidence": [{"id": key, "quote": "采用条件扩散", "claim": "technology"},
                                   {"id": key, "quote": "离线成本下降", "claim": "outcome"}]})
        triage.append({"id": key, "decision": "include", "reason": "虚构测试入选"})
    inputs = {"records": records, "limits": {"max_items": item_limit, "max_chars_per_item": 100,
                                              "max_body_chars": body_limit, "body_overhead": 100}}
    result = {"cards": cards, "company_findings": [], "observations": [], "caveat": "", "triage": triage}
    coverage = [(key, "相关候选0，纳入0") for key in research.COMPANIES]
    return result, inputs, coverage


def database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE items(id TEXT PRIMARY KEY, stable_id TEXT, payload TEXT, first_seen TEXT);
    CREATE TABLE attempts(id INTEGER PRIMARY KEY,item_id TEXT,day TEXT,started_at TEXT,status TEXT);
    """)
    research.init_db(db)
    return db


class BriefTests(unittest.TestCase):
    def test_visible_length_does_not_count_link_destination(self):
        self.assertEqual(research.visible_chars("1. [标题](https://example.org/very-long-url) 技术"), len("1. 标题 技术"))

    def test_cards_are_concise_and_body_reserves_header(self):
        result, inputs, coverage = fixture(20)
        lines, ids = research.render(result, inputs, coverage)
        report = research.quality_report(result, inputs, lines)
        self.assertTrue(report["structural_pass"])
        self.assertTrue(all(n <= 100 for n in report["item_chars"]))
        self.assertLessEqual(report["body_chars"] + 100, 2000)
        self.assertEqual(len(ids), report["items"])

    def test_n_and_total_limits_remove_whole_cards(self):
        result, inputs, coverage = fixture(5, body_limit=380, item_limit=2)
        lines, ids = research.render(result, inputs, coverage)
        self.assertLessEqual(len(ids), 2)
        self.assertLess(len(ids), 5)
        self.assertTrue(all("作者报告。" in line and line.endswith("相关性9/10")
                            for line in lines if line[:1].isdigit()))
        self.assertTrue(research.quality_report(result, inputs, lines)["structural_pass"])

    def test_card_reads_as_sentences_and_names_both_scores(self):
        result, inputs, coverage = fixture()
        lines, _ = research.render(result, inputs, coverage)
        card = next(line for line in lines if line.startswith("1. "))
        self.assertEqual(len(card.splitlines()), 4)
        self.assertIn("条件扩散出价。离线成本下降。作者报告。", card)
        self.assertIn("含金量8/10 · 相关性9/10", card)
        self.assertIn("借鉴出价轨迹生成。", card)
        for shorthand in ("技：", "果：", "；含", " 相9"):
            self.assertNotIn(shorthand, card)

    def test_sentence_punctuation_is_not_duplicated(self):
        result, inputs, coverage = fixture()
        result["cards"][0].update(technology="条件扩散出价。", outcome="离线成本下降！", why_read="借鉴轨迹生成！")
        lines, _ = research.render(result, inputs, coverage)
        card = next(line for line in lines if line.startswith("1. "))
        self.assertNotIn("。。", card)
        self.assertNotIn("！。", card)

    def test_reading_value_is_required_and_cannot_be_empty_praise(self):
        for value in ("", "  ", "。", "值得关注", "很有价值", "对工作有帮助"):
            with self.subTest(value=value):
                result, inputs, _ = fixture()
                result["cards"][0]["why_read"] = value
                with self.assertRaises(ValueError):
                    research.validate_brief(result, inputs)
        schema = json.loads(Path(research.__file__).with_name("brief.schema.json").read_text())
        self.assertIn("why_read", schema["properties"]["cards"]["items"]["required"])

    def test_fresh_reading_precedes_old_discovery_even_if_old_score_is_high(self):
        result, inputs, coverage = fixture(3, item_limit=2)
        result["cards"][0]["change_type"] = "old_discovery"
        inputs["records"][0].update(published="2025-10-01", novelty={"allowed_types": ["old_discovery"]})
        result["cards"][2]["lane"] = "watch"
        result["triage"][2]["decision"] = "watch"
        lines, ids = research.render(result, inputs, coverage)
        self.assertEqual(ids, ["1", "2"])
        self.assertLess(lines.index("## 重点阅读"), lines.index("## 值得跟进"))
        self.assertNotIn("## 旧文补读", lines)

    def test_period_takeaway_comes_first_without_claiming_industry_consensus(self):
        result, inputs, coverage = fixture(2)
        result["observations"] = [{"conclusion": "两项方法都使用轨迹生成，尚未比较效果", "cross_company": False,
                                   "evidence": [{"id": "0", "quote": "采用条件扩散"},
                                                {"id": "1", "quote": "采用条件扩散"}]}]
        lines, _ = research.render(result, inputs, coverage)
        self.assertEqual(lines[0], "## 本期看点")
        self.assertLess(lines.index("## 本期看点"), lines.index("## 重点阅读"))
        self.assertEqual("\n".join(lines).count("两项方法都使用轨迹生成"), 1)

    def test_watch_only_digest_does_not_display_a_main_recommendation_heading(self):
        result, inputs, coverage = fixture()
        result["cards"][0]["lane"] = "watch"
        result["triage"][0]["decision"] = "watch"
        lines, _ = research.render(result, inputs, coverage)
        self.assertIn("## 值得跟进", lines)
        self.assertNotIn("## 重点阅读", lines)

    def test_overlong_card_is_rejected_not_sliced(self):
        result, inputs, _ = fixture()
        result["cards"][0]["technology"] = "精" * 65
        with self.assertRaisesRegex(ValueError, "brief_card_too_long"):
            research.validate_brief(result, inputs)

    def test_score_sums_and_thresholds(self):
        result, inputs, _ = fixture()
        result["cards"][0]["quality"] = 9
        with self.assertRaisesRegex(ValueError, "sum_mismatch"):
            research.validate_brief(result, inputs)
        result, inputs, _ = fixture()
        result["cards"][0]["score_basis"]["business"]["score"] = 1
        result["cards"][0]["relevance"] = 5
        with self.assertRaisesRegex(ValueError, "below_threshold"):
            research.validate_brief(result, inputs)

    def test_missing_evidence_can_be_watch_without_low_quality_score(self):
        result, inputs, _ = fixture()
        card = result["cards"][0]
        card["quality"] = None
        card["score_basis"]["evidence"]["score"] = None
        card["lane"] = "watch"
        result["triage"][0]["decision"] = "watch"
        research.validate_brief(result, inputs)
        card["lane"] = "main"
        result["triage"][0]["decision"] = "include"
        with self.assertRaisesRegex(ValueError, "below_threshold"):
            research.validate_brief(result, inputs)

    def test_watch_limit(self):
        result, inputs, _ = fixture(3)
        for card in result["cards"]:
            card["lane"] = "watch"
        for row in result["triage"]:
            row["decision"] = "watch"
        with self.assertRaisesRegex(ValueError, "supplemental"):
            research.validate_brief(result, inputs)

    def test_quotes_are_real_and_claims_are_explicit(self):
        result, inputs, _ = fixture()
        result["cards"][0]["evidence"][1]["quote"] = "不在原文的收益"
        with self.assertRaisesRegex(ValueError, "quote_not_in_input"):
            research.validate_brief(result, inputs)
        result, inputs, _ = fixture()
        result["cards"][0]["evidence"][1]["claim"] = "technology"
        with self.assertRaisesRegex(ValueError, "claims_missing"):
            research.validate_brief(result, inputs)

    def test_card_cannot_borrow_another_studys_results(self):
        result, inputs, _ = fixture(2)
        result["cards"][0]["evidence"][1]["id"] = "1"
        with self.assertRaisesRegex(ValueError, "own_source"):
            research.validate_brief(result, inputs)

    def test_old_discovery_keeps_original_month_in_visible_card(self):
        result, inputs, coverage = fixture()
        result["cards"][0]["change_type"] = "old_discovery"
        inputs["records"][0]["novelty"]["allowed_types"] = ["old_discovery"]
        inputs["records"][0]["published"] = "2025-10-01T00:00:00Z"
        lines, _ = research.render(result, inputs, coverage)
        card = next(line for line in lines if line.startswith("1. "))
        self.assertIn("旧文补读(2025-10)", card)
        self.assertLessEqual(research.visible_chars(card), 100)

    def test_same_study_does_not_support_joint_observation(self):
        result, inputs, _ = fixture(2)
        inputs["records"][1]["research_id"] = inputs["records"][0]["research_id"]
        result["cards"] = result["cards"][:1]
        result["triage"][1]["decision"] = "defer"
        result["observations"] = [{"conclusion": "虚构比较", "cross_company": False,
                                   "evidence": [{"id": "0", "quote": "采用条件扩散"}, {"id": "1", "quote": "采用条件扩散"}]}]
        with self.assertRaisesRegex(ValueError, "independent_research"):
            research.validate_brief(result, inputs)

    def test_duplicate_research_cards_are_rejected(self):
        result, inputs, _ = fixture(2)
        inputs["records"][1]["research_id"] = inputs["records"][0]["research_id"]
        with self.assertRaisesRegex(ValueError, "duplicate_research"):
            research.validate_brief(result, inputs)

    def test_english_quote_word_limit(self):
        result, inputs, _ = fixture()
        quote = " ".join("word" + str(n) for n in range(26))
        inputs["records"][0]["text"] = quote
        for entry in result["cards"][0]["evidence"]:
            entry["quote"] = quote
        # Stay below 160 characters while exceeding 25 English words.
        quote = " ".join(["a"] * 26)
        inputs["records"][0]["text"] = quote
        for entry in result["cards"][0]["evidence"]:
            entry["quote"] = quote
        with self.assertRaisesRegex(ValueError, "quotes_too_long"):
            research.validate_brief(result, inputs)

    def test_audit_is_bound_to_exact_draft_and_has_no_private_fields(self):
        result, inputs, coverage = fixture()
        inputs["records"][0]["private_note"] = "private-marker"
        inputs["records"][0]["review"] = {"private_note": "private-marker"}
        lines, _ = research.render(result, inputs, coverage)
        payload = research.audit_public(result, inputs, lines)
        self.assertNotIn("private-marker", json.dumps(payload, ensure_ascii=False))
        audit = {"candidate_sha256": payload["candidate_sha256"], "approve": True, "issues": []}
        self.assertTrue(research.validate_audit(audit, result, inputs, lines))
        with self.assertRaisesRegex(ValueError, "candidate_mismatch"):
            research.validate_audit(audit, result, inputs, lines + ["新文字"])
        audit["issues"] = ["有实质问题"]
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            research.validate_audit(audit, result, inputs, lines)

    def test_history_only_changes_after_confirmed_publication_and_next_window(self):
        db = database()
        self.addCleanup(db.close)
        result, inputs, _ = fixture()
        self.assertEqual(research._publication_history(db, "2026-11-05"), [])
        research.record_published(db, result, inputs, ["0"], "2026-11-20T01:00:00+00:00")
        self.assertEqual(research._publication_history(db, "2026-11-05"), [])
        history = research._publication_history(db, "2026-12-05")
        self.assertEqual(len(history), 1)
        novelty = research._novelty(inputs["records"][0], history, "2026-12-05", "2026-12-20")
        self.assertEqual(novelty["allowed_types"], ["repost_update"])
        self.assertNotIn("score_basis", history[0])

    def test_history_window_end_includes_prior_delivery_and_excludes_current(self):
        db = database()
        self.addCleanup(db.close)
        result, inputs, _ = fixture()
        # A Nov 20 delivery happens after the next cycle's Nov 20 00:00 start.
        prior_send = "2026-11-20T09:00:00+08:00"
        current_start = "2026-11-20T00:00:00+08:00"
        current_end = "2026-12-05T00:00:00+08:00"
        research.record_published(db, result, inputs, ["0"], prior_send)
        self.assertEqual(research._publication_history(db, current_start), [])
        frozen = research._publication_history(db, current_end)
        self.assertEqual([row["published_at"] for row in frozen], [prior_send])
        research.record_published(db, result, inputs, ["0"], "2026-12-05T09:00:00+08:00")
        self.assertEqual(research._publication_history(db, current_end), frozen)
        self.assertEqual(len(research._publication_history(db, "2026-12-20T00:00:00+08:00")), 2)
        cfg = {"brief": {"max_items": 20}, "review": {"model": "test"}}
        _, prepared = research.prepare(db, cfg, [], current_start, current_end)
        self.assertEqual(prepared["published_history_cutoff"], current_end)

    def test_history_cutoff_compares_instants_across_timezones(self):
        db = database()
        self.addCleanup(db.close)
        result, inputs, _ = fixture()
        research.record_published(db, result, inputs, ["0"], "2026-12-05T01:00:00+00:00")
        # This local cutoff is midnight UTC; the 01:00 UTC delivery must remain excluded.
        self.assertEqual(research._publication_history(db, "2026-12-05T08:00:00+08:00"), [])
        self.assertEqual(len(research._publication_history(db, "2026-12-05T10:00:00+08:00")), 1)

    def test_quote_compaction_reuses_existing_containing_quote_and_preserves_claims(self):
        result, inputs, _ = fixture()
        long_quote = "采用条件扩散。离线成本下降"
        result["cards"][0]["evidence"].append({"id": "0", "quote": long_quote, "claim": "boundary"})
        original = copy.deepcopy(result)
        compacted = research.compact_evidence(result)
        self.assertEqual(result, original)
        self.assertEqual({row["quote"] for row in compacted["cards"][0]["evidence"]}, {long_quote})
        self.assertEqual({row["claim"] for row in compacted["cards"][0]["evidence"]}, {"technology", "outcome", "boundary"})
        research.validate_brief(compacted, inputs)
        self.assertEqual(research.compact_evidence(compacted), compacted)

    def test_quote_compaction_rejects_malformed_top_level(self):
        for value in (None, [], "invalid", 1):
            with self.assertRaisesRegex(ValueError, "brief_invalid_shape"):
                research.compact_evidence(value)

    def test_quote_compaction_never_merges_different_sources_or_cuts_quote(self):
        result, _, _ = fixture(2)
        original = copy.deepcopy(result)
        result["cards"][1]["evidence"][0]["quote"] = "采用条件扩散以及更多内容"
        compacted = research.compact_evidence(result)
        self.assertEqual(compacted["cards"][0], original["cards"][0])
        self.assertEqual(compacted["cards"][1]["evidence"][0]["quote"], "采用条件扩散以及更多内容")

    def test_quote_compaction_drops_only_new_research_date_citation_when_required(self):
        result, _, _ = fixture()
        card = result["cards"][0]
        card["change_type"] = "new_research"
        card["evidence"].append({"id": "0", "quote": "新" * 150, "claim": "change"})
        compacted = research.compact_evidence(result)
        self.assertEqual({row["claim"] for row in compacted["cards"][0]["evidence"]}, {"technology", "outcome"})
        card["change_type"] = "new_experiments"
        self.assertIn("change", {row["claim"] for row in research.compact_evidence(result)["cards"][0]["evidence"]})
        card["change_type"] = "new_research"
        card["evidence"][-1]["quote"] = "短日期"
        self.assertIn("change", {row["claim"] for row in research.compact_evidence(result)["cards"][0]["evidence"]})

    def test_original_dates_and_community_dates_are_not_confused(self):
        _, inputs, _ = fixture()
        row = inputs["records"][0]
        row.update(published="2026-10-01T00:00:00Z", date_basis="", kind="abstract")
        old = research._novelty(row, [], "2026-11-05", "2026-11-20")
        self.assertIn("old_discovery", old["allowed_types"])
        self.assertNotIn("first_seen", old["allowed_types"])
        row.update(published="2026-11-10T00:00:00Z", date_basis="community_shared")
        unknown = research._novelty(row, [], "2026-11-05", "2026-11-20")
        self.assertNotIn("new_research", unknown["allowed_types"])
        row["date_basis"] = ""
        self.assertIn("new_research", research._novelty(row, [], "2026-11-05", "2026-11-20")["allowed_types"])

    def test_company_status_distinguishes_candidates_failure_and_no_update(self):
        result, _, _ = fixture()
        lines = research._summary_lines(result, [("alimama", "相关候选1，纳入0"),
                                                 ("kuaishou", "相关候选0，纳入0；1入口失败/未采集"),
                                                 ("meituan", "相关候选0，纳入0")])
        text = "\n".join(lines)
        self.assertIn("阿里妈妈：有相关资料，本期未推荐。", text)
        self.assertIn("快手：采集未完成，暂不下结论。", text)
        self.assertIn("美团：本期未取得可核查资料。", text)
        self.assertNotIn("公司：", text)

    def test_removed_sources_do_not_leave_company_failures(self):
        db = database()
        db.execute("CREATE TABLE sources(id TEXT PRIMARY KEY,last_error TEXT)")
        db.execute("INSERT INTO sources VALUES('tencent-articles','old_error')")
        coverage = dict(research.coverage_lines(db, {"sources": []}, [], []))
        self.assertNotIn("失败", coverage["tencent"])

    def test_company_recommendations_match_visible_cards_after_n_trimming(self):
        result, inputs, _ = fixture(2, item_limit=1)
        inputs["records"][0]["company"] = "alimama"
        inputs["records"][1]["company"] = "kuaishou"
        lines, ids = research.render(result, inputs, [("alimama", "相关候选1，纳入0"),
                                                      ("kuaishou", "相关候选1，纳入0")])
        text = "\n".join(lines)
        self.assertEqual(ids, ["0"])
        self.assertIn("阿里妈妈：已列入推荐1篇。", text)
        self.assertIn("快手：有相关资料，本期未推荐。", text)

    def test_historical_publication_does_not_apply_current_rendering_limit(self):
        db = database()
        result, inputs, _ = fixture()
        card = result["cards"][0]
        card["technology"] += "术" * (101 - research.visible_chars(research._card_line(card, 1, inputs["records"][0])))
        self.assertLessEqual(len(card["technology"]), 70)
        with self.assertRaisesRegex(ValueError, "brief_card_too_long"):
            research.validate_brief(result, inputs)
        research.record_published(db, result, inputs, ["0"], "2026-11-20T00:00:00Z")
        self.assertEqual(db.execute("SELECT count(*) FROM research_publications").fetchone()[0], 1)

    def test_publication_keeps_raw_comparison_symbols_in_source_title(self):
        db = database()
        result, inputs, _ = fixture()
        inputs["records"][0]["title"] = "CTR < 1% and ROI > 2: bidding policy"
        research.validate_brief(result, inputs)
        research.record_published(db, result, inputs, ["0"], "2026-11-20T00:00:00Z")
        saved = json.loads(db.execute("SELECT public_record FROM research_publications").fetchone()[0])
        self.assertEqual(saved["title"], inputs["records"][0]["title"])

    def test_invalid_publication_projection_writes_nothing(self):
        db = database()
        result, inputs, _ = fixture(2)
        del inputs["records"][1]["url"]
        with self.assertRaises(KeyError):
            research.record_published(db, result, inputs, ["0", "1"], "2026-11-20T00:00:00Z")
        db.commit()
        self.assertEqual(db.execute("SELECT count(*) FROM research_publications").fetchone()[0], 0)
        with self.assertRaisesRegex(ValueError, "publication_unknown_item"):
            research.record_published(db, result, inputs, ["missing"], "2026-11-20T00:00:00Z")

    def test_repost_cannot_be_recommended(self):
        result, inputs, _ = fixture()
        inputs["records"][0]["novelty"]["allowed_types"] = ["repost_update"]
        result["cards"][0]["change_type"] = "repost_update"
        with self.assertRaisesRegex(ValueError, "repost_not_recommendable"):
            research.validate_brief(result, inputs)

    def test_canonical_identifiers_do_not_depend_on_tracking_or_arxiv_version(self):
        self.assertEqual(research.canonical_url("http://arxiv.org/pdf/2611.12345v2.pdf?utm_source=x"), "https://arxiv.org/abs/2611.12345")
        self.assertEqual(research.research_id(["https://github.com/Org/Repo/tree/main"]), research.research_id(["https://github.com/org/repo"]))
        with self.assertRaisesRegex(ValueError, "public_url"):
            research.canonical_url("file:///private/file")

    def test_input_budget_and_excerpt_are_hard_limits(self):
        text = "条件扩散机制。" * 1000
        for limit in [10, 100, 1440]:
            self.assertLessEqual(len(research.evidence_excerpt(text, limit)["text"]), limit)
        db = database()
        self.addCleanup(db.close)
        cfg = {"brief": {"max_items": 20, "chars_per_item": 2400, "max_input_chars": 28800}, "review": {"model": "test"}}
        records = []
        for n in range(20):
            item = {"title": f"研究{n}", "url": f"https://example.org/{n}", "text": text,
                    "published": "2026-11-06T00:00:00+00:00", "updated": "2026-11-06T00:00:00+00:00", "source": "test", "kind": "abstract"}
            records.append({"id": str(n), "item": item, "company": "unassigned", "attribution": "未知", "sources": ["test"],
                            "feedback": "", "review": None, "priority": 1})
        key, inputs = research.prepare(db, cfg, records, "2026-11-05", "2026-11-20")
        self.assertEqual(len(key), 64)
        self.assertEqual(len(inputs["records"]), 20)
        self.assertLessEqual(sum(len(row["text"]) for row in inputs["records"]), 28800)

    def test_manual_evaluation_budget_does_not_reset_normal_counts(self):
        db = database()
        self.addCleanup(db.close)
        for n in range(8):
            db.execute("INSERT INTO brief_attempts(input_hash,day,started_at,status) VALUES(?,?,?,?)",
                       (f"old-{n}", "2026-11-20", "2026-11-20T00:00:00Z", "done"))
        cfg = {"selection": {"timezone": "Asia/Shanghai"}, "review": {"daily_limit": 6}}
        self.assertEqual(research.remaining_calls(db, cfg, day="2026-11-20"), 0)
        cfg["_evaluation_budget"] = {"id": "abc123", "limit": 4}
        self.assertEqual(research.remaining_calls(db, cfg, day="2026-11-20"), 4)
        db.execute("INSERT INTO brief_attempts(input_hash,day,started_at,status) VALUES(?,?,?,?)",
                   ("evaluation:abc123:draft", "2026-11-20", "2026-11-20T01:00:00Z", "failed"))
        self.assertEqual(research.remaining_calls(db, cfg, day="2026-11-20"), 3)
        del cfg["_evaluation_budget"]
        self.assertEqual(research.remaining_calls(db, cfg, day="2026-11-20"), 0)


if __name__ == "__main__":
    unittest.main()
