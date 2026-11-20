"""Offline runtime checks: fictional inputs, temporary state, no external calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bidradar
import research
from test_research import fixture


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state = patch.object(bidradar, "STATE", Path(temporary.name))
        state.start()
        self.addCleanup(state.stop)
        self.db = bidradar.connect()
        self.addCleanup(self.db.close)
        self.cfg = {
            "selection": {"timezone": "Asia/Shanghai"},
            "review": {"model": "test-primary", "daily_limit": 6, "lookback_days": 15},
            "brief": {"max_items": 20, "max_body_chars": 2000, "body_overhead": 100},
            "feishu": {"keyword": "测试出价情报"},
            "sources": [], "capture": {"daily_feeds": []},
            "_window_start": "2026-11-05T00:00:00+00:00",
            "_window_end": "2026-11-20T00:00:00+00:00",
        }
        self.result, self.inputs, self.coverage = fixture()
        self.inputs["records"][0]["url"] = "https://arxiv.org/abs/2611.00001"
        self.inputs["candidate_count"] = 1
        self.records = []
        self.key = "f" * 64
        for target, value in [
            ("brief_inputs", (self.key, self.inputs, self.records)),
            ("source_issues", []),
        ]:
            mocked = patch.object(bidradar, target, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        coverage = patch.object(research, "coverage_lines", return_value=self.coverage)
        coverage.start()
        self.addCleanup(coverage.stop)
        preflight = patch.object(bidradar, "reviewer_preflight")
        preflight.start()
        self.addCleanup(preflight.stop)

    def model_response(self, *, reject_audits=0):
        audits = 0

        def respond(public, cfg, schema, prompt, phase):
            nonlocal audits
            if schema == "brief-audit.schema.json":
                audits += 1
                issues = ["虚构测试：结果条件需要明确"] if audits <= reject_audits else []
                return {"candidate_sha256": public["candidate_sha256"],
                        "approve": not issues, "issues": issues}, {}
            draft = copy.deepcopy(self.result)
            if phase.startswith("revision:"):
                draft["cards"][0]["title"] = "修订虚构"
            return draft, {}

        return respond

    def store_approval(self):
        lines, _, _ = bidradar.brief_layout(self.db, self.cfg, self.result, self.inputs, self.records)
        signature, public = bidradar.audit_signature(self.result, self.inputs, lines)
        audit = {"candidate_sha256": public["candidate_sha256"], "approve": True, "issues": []}
        self.db.execute("INSERT OR REPLACE INTO brief_audits VALUES(?,?,?,?)",
                        (signature, self.key, json.dumps(audit), bidradar.now()))
        self.db.execute("INSERT OR REPLACE INTO briefs VALUES(?,?,?,?)",
                        (self.key, json.dumps(self.result), json.dumps(self.inputs), bidradar.now()))
        self.db.commit()
        return lines, signature, audit

    def test_cache_requires_approval_for_exact_draft_and_input_key(self):
        lines, _, _ = self.store_approval()
        self.assertIsNotNone(bidradar.cached_brief(self.db, self.cfg))
        self.assertFalse(bidradar.approved_brief(self.db, "different-key", self.result, self.inputs, lines))
        changed = copy.deepcopy(self.result)
        changed["cards"][0]["title"] = "已修改虚构"
        self.db.execute("UPDATE briefs SET result=? WHERE input_hash=?", (json.dumps(changed), self.key))
        self.assertIsNone(bidradar.cached_brief(self.db, self.cfg))

    def test_render_change_invalidates_approval_even_for_same_result(self):
        lines, _, audit = self.store_approval()
        changed_lines = lines + ["新的可见结论"]
        signature, _ = bidradar.audit_signature(self.result, self.inputs, changed_lines)
        self.db.execute("INSERT INTO brief_audits VALUES(?,?,?,?)",
                        (signature, self.key, json.dumps(audit), bidradar.now()))
        self.assertFalse(bidradar.approved_brief(self.db, self.key, self.result, self.inputs, changed_lines))

    def test_passed_audit_publishes_cache_and_restart_costs_no_calls(self):
        with patch.object(bidradar, "model_json", side_effect=self.model_response()) as model:
            self.assertTrue(bidradar.build_brief(self.db, self.cfg))
            self.assertEqual(model.call_count, 2)
            self.assertTrue(bidradar.build_brief(self.db, self.cfg))
            self.assertEqual(model.call_count, 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM briefs").fetchone()[0], 1)

    def test_rejected_draft_is_revised_once_and_must_be_reviewed_again(self):
        with patch.object(bidradar, "model_json", side_effect=self.model_response(reject_audits=1)) as model:
            self.assertTrue(bidradar.build_brief(self.db, self.cfg))
        self.assertEqual(model.call_count, 4)
        phases = [call.args[4].split(":", 1)[0] for call in model.call_args_list]
        self.assertEqual(phases[0], "draft")
        self.assertTrue(phases[1].startswith("audit-"))
        self.assertEqual(phases[2], "revision")
        self.assertTrue(phases[3].startswith("audit-"))
        saved = bidradar.cached_brief(self.db, self.cfg)
        self.assertEqual(saved[0]["cards"][0]["title"], "修订虚构")

    def test_second_rejection_stops_and_restart_cannot_reset_revision_limit(self):
        with patch.object(bidradar, "model_json", side_effect=self.model_response(reject_audits=2)) as model:
            self.assertFalse(bidradar.build_brief(self.db, self.cfg))
            self.assertEqual(model.call_count, 4)
            self.assertFalse(bidradar.build_brief(self.db, self.cfg))
            self.assertEqual(model.call_count, 4)
        self.assertEqual(self.db.execute("SELECT revisions FROM brief_drafts").fetchone()[0], 1)
        self.assertIsNone(bidradar.cached_brief(self.db, self.cfg))

    def test_unapproved_draft_has_no_technical_fallback(self):
        with patch.object(bidradar, "cached_brief", return_value=None):
            payload, ids, markdown = bidradar.make_digest(self.db, self.cfg)
        self.assertEqual(ids, [])
        self.assertIn("没有通过成稿复审", markdown)
        self.assertNotIn("虚构0", json.dumps(payload, ensure_ascii=False))

    def test_manual_budget_counts_failed_primary_and_fallback_across_phases(self):
        cfg = bidradar.register_evaluation(self.db, self.cfg, 4, "gpt-6-luna")

        def quota_then_fallback(public, call_cfg, schema, prompt, phase):
            if call_cfg["review"]["model"] == "test-primary":
                raise ValueError("codex_quota_exhausted")
            return {"fictional": True}, {}

        with patch.object(bidradar, "model_json", side_effect=quota_then_fallback) as model:
            for phase in ["draft", "audit"]:
                self.assertEqual(bidradar.brief_model_call(self.db, cfg, self.key, phase, {}, "schema", "prompt"),
                                 {"fictional": True})
            self.assertIsNone(bidradar.brief_model_call(self.db, cfg, self.key, "revision", {}, "schema", "prompt"))
            self.assertEqual(model.call_count, 4)
        self.assertEqual(research.remaining_calls(self.db, cfg), 0)
        statuses = [r[0] for r in self.db.execute("SELECT status FROM brief_attempts ORDER BY id")]
        self.assertEqual(statuses, ["failed", "ok", "failed", "ok"])

    def test_manual_budget_survives_restart_and_day_change_without_changing_schedule(self):
        schedule = {"window_start": "2026-10-01T00:00:00+00:00",
                    "window_end": "2026-10-16T00:00:00+00:00", "status": "partial"}
        stored = json.dumps(schedule)
        self.db.execute("INSERT INTO meta VALUES('schedule_state',?)", (stored,))
        cfg = {key: value for key, value in self.cfg.items() if not key.startswith("_window_")}
        first = bidradar.register_evaluation(self.db, cfg, 4)
        key = first["_evaluation_budget"]["id"]
        self.db.execute("INSERT INTO brief_attempts(input_hash,day,started_at,status) VALUES(?,?,?,?)",
                        ("evaluation:" + key + ":draft", "2026-11-20", bidradar.now(), "failed"))
        with patch.object(bidradar, "local_day", return_value="2026-11-21"):
            resumed = bidradar.register_evaluation(self.db, cfg, 4)
        self.assertEqual(research.remaining_calls(self.db, resumed), 3)
        self.assertEqual(first["_evaluation_budget"], resumed["_evaluation_budget"])
        self.assertEqual(resumed["_window_start"], schedule["window_start"])
        self.assertEqual(resumed["_window_end"], schedule["window_end"])
        self.assertEqual(self.db.execute("SELECT value FROM meta WHERE key='schedule_state'").fetchone()[0], stored)
        self.assertNotIn("_evaluation_budget", self.cfg)
        self.assertEqual(self.cfg["review"]["daily_limit"], 6)

    def test_explicit_preview_window_is_preserved(self):
        self.db.execute("INSERT INTO meta VALUES('schedule_state',?)",
                        (json.dumps({"window_start": "2026-10-01", "window_end": "2026-10-16"}),))
        cfg = bidradar.register_evaluation(self.db, self.cfg, 4)
        self.assertEqual(cfg["_window_start"], self.cfg["_window_start"])
        self.assertEqual(cfg["_window_end"], self.cfg["_window_end"])

    def test_duplicate_send_returns_skipped_and_never_calls_transport(self):
        self.db.execute("INSERT INTO outbox VALUES(?,?,?,'sent',?,?,?,NULL,NULL)",
                        ("old", "digest", bidradar.local_day(self.cfg), "{}", "[]", bidradar.now()))
        with patch.object(bidradar, "feishu_settings", return_value=("https://example.invalid", "fictional")), \
                patch.object(bidradar, "curl_request") as transport:
            self.assertEqual(bidradar.send(self.db, self.cfg, {}, ["0"], kind="digest"), "skipped_sent")
        transport.assert_not_called()

    def test_skipped_delivery_does_not_record_publication(self):
        with patch.object(bidradar, "make_digest", return_value=({}, ["0"], "fictional preview")), \
                patch.object(bidradar, "connected", return_value=True), \
                patch.object(bidradar, "send", return_value="skipped_sent"), \
                patch.object(research, "record_published") as published:
            bidradar.report_digest(self.db, self.cfg, deliver=True)
        published.assert_not_called()
        self.assertFalse((bidradar.STATE / "digests" / (bidradar.local_day(self.cfg) + "-sent.md")).exists())

    def send_fixture(self):
        self.store_approval()
        payload, ids, _ = bidradar.research_digest(self.db, self.cfg, (self.result, self.inputs, []))
        return payload, ids

    def test_confirmed_send_snapshots_exact_brief_before_transport_and_records_publication(self):
        payload, ids = self.send_fixture()

        def transport(*args, **kwargs):
            queued = self.db.execute("SELECT o.status,b.* FROM outbox o JOIN outbox_briefs b ON b.outbox_id=o.id").fetchone()
            self.assertIsNotNone(queued)
            self.assertEqual(queued["status"], "sending")
            self.assertEqual(json.loads(queued["result"]), self.result)
            self.assertEqual(json.loads(queued["inputs"]), self.inputs)
            self.assertIsNone(queued["recorded_at"])
            return 200, {}, b'{"code":0}'

        with patch.object(bidradar, "feishu_settings", return_value=("https://example.invalid", "fictional")), \
                patch.object(bidradar, "curl_request", side_effect=transport):
            self.assertEqual(bidradar.send(self.db, self.cfg, payload, ids, kind="digest"), "sent")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM research_publications").fetchone()[0], 1)
        self.assertIsNotNone(self.db.execute("SELECT recorded_at FROM outbox_briefs").fetchone()[0])

    def test_mismatched_digest_cannot_be_sent_or_associated_with_approved_brief(self):
        payload, ids = self.send_fixture()
        payload["content"]["post"]["zh_cn"]["content"][0][0]["text"] += "未审核内容"
        with patch.object(bidradar, "feishu_settings", return_value=("https://example.invalid", "fictional")), \
                patch.object(bidradar, "curl_request") as transport:
            with self.assertRaises(ValueError):
                bidradar.send(self.db, self.cfg, payload, ids, kind="digest")
        transport.assert_not_called()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def confirmed_without_publication_replay(self):
        payload, ids = self.send_fixture()
        with patch.object(bidradar, "feishu_settings", return_value=("https://example.invalid", "fictional")), \
                patch.object(bidradar, "curl_request", return_value=(200, {}, b'{"code":0}')), \
                patch.object(bidradar, "reconcile_publications"):
            self.assertEqual(bidradar.send(self.db, self.cfg, payload, ids, kind="digest"), "sent")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM research_publications").fetchone()[0], 0)
        return self.db.execute("SELECT id FROM outbox").fetchone()[0]

    def test_connect_replays_confirmed_snapshot_after_crash_and_ignores_new_draft(self):
        self.confirmed_without_publication_replay()
        original_technology = self.result["cards"][0]["technology"]
        self.result["cards"][0]["technology"] = "另一个未发送草稿"
        self.store_approval()
        self.db.close()
        self.db = bidradar.connect()
        self.addCleanup(self.db.close)
        rows = self.db.execute("SELECT public_record FROM research_publications").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["public_record"])["technology"], original_technology)
        bidradar.reconcile_publications(self.db)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM research_publications").fetchone()[0], 1)

    def test_manual_delivery_yes_replays_only_the_associated_snapshot(self):
        out_id = self.confirmed_without_publication_replay()
        self.db.execute("UPDATE outbox SET status='uncertain',delivered_at=NULL WHERE id=?", (out_id,))
        bidradar.resolve_delivery(self.db, out_id, True)
        self.assertEqual(self.db.execute("SELECT status FROM outbox WHERE id=?", (out_id,)).fetchone()[0], "sent")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM research_publications").fetchone()[0], 1)
        self.assertIsNotNone(self.db.execute("SELECT recorded_at FROM outbox_briefs").fetchone()[0])

    def test_manual_delivery_no_does_not_create_publication_history(self):
        out_id = self.confirmed_without_publication_replay()
        self.db.execute("UPDATE outbox SET status='uncertain',delivered_at=NULL WHERE id=?", (out_id,))
        bidradar.resolve_delivery(self.db, out_id, False)
        self.assertEqual(self.db.execute("SELECT status FROM outbox WHERE id=?", (out_id,)).fetchone()[0], "failed")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM research_publications").fetchone()[0], 0)

    def test_publication_commit_then_crash_replays_idempotently_on_connect(self):
        self.confirmed_without_publication_replay()
        record = research.record_published

        def commit_then_crash(*args, **kwargs):
            record(*args, **kwargs)
            raise RuntimeError("fictional crash after publication commit")

        with patch.object(research, "record_published", side_effect=commit_then_crash):
            with self.assertRaisesRegex(RuntimeError, "fictional crash"):
                bidradar.reconcile_publications(self.db)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM research_publications").fetchone()[0], 1)
        self.assertIsNone(self.db.execute("SELECT recorded_at FROM outbox_briefs").fetchone()[0])
        self.db.close()
        self.db = bidradar.connect()
        self.addCleanup(self.db.close)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM research_publications").fetchone()[0], 1)
        self.assertIsNotNone(self.db.execute("SELECT recorded_at FROM outbox_briefs").fetchone()[0])

    def test_manual_yes_on_legacy_unassociated_outbox_does_not_invent_history(self):
        self.db.execute("INSERT INTO outbox VALUES(?,?,?,'uncertain',?,?,?,NULL,NULL)",
                        ("legacy", "digest", bidradar.local_day(self.cfg), "{}", '["0"]', bidradar.now()))
        self.assertEqual(bidradar.resolve_delivery(self.db, "legacy", True), "sent")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM research_publications").fetchone()[0], 0)

    def test_skipped_digest_never_associates_or_publishes_current_draft(self):
        payload, ids = self.send_fixture()
        self.db.execute("INSERT INTO outbox VALUES(?,?,?,'sent',?,?,?,NULL,NULL)",
                        ("old-unassociated", "digest", bidradar.local_day(self.cfg), "{}", "[]", bidradar.now()))
        with patch.object(bidradar, "feishu_settings", return_value=("https://example.invalid", "fictional")), \
                patch.object(bidradar, "curl_request") as transport:
            self.assertEqual(bidradar.send(self.db, self.cfg, payload, ids, kind="digest"), "skipped_sent")
        transport.assert_not_called()
        bidradar.reconcile_publications(self.db)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox_briefs").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM research_publications").fetchone()[0], 0)

    def test_title_link_becomes_feishu_anchor_and_url_is_not_visible_text(self):
        with patch.object(research, "selection_appendix", return_value=[]):
            payload, ids, _ = bidradar.research_digest(self.db, self.cfg, (self.result, self.inputs, []))
        paragraphs = payload["content"]["post"]["zh_cn"]["content"]
        anchors = [node for paragraph in paragraphs for node in paragraph if node["tag"] == "a"]
        self.assertEqual(anchors, [{"tag": "a", "text": "虚构0", "href": "https://arxiv.org/abs/2611.00001"}])
        visible = "\n".join("".join(node["text"] for node in paragraph) for paragraph in paragraphs)
        self.assertNotIn("https://", visible)
        self.assertNotIn("[虚构0]", visible)
        self.assertLessEqual(len(visible), 2000)
        self.assertEqual(ids, ["0"])

    def test_reading_preview_excludes_local_evidence_and_runtime_logs(self):
        with patch.object(research, "selection_appendix", return_value=["LOCAL_ONLY_EVIDENCE"]), \
                patch.object(bidradar, "source_issues", return_value=["raw_http_failure"]):
            _, _, markdown = bidradar.research_digest(self.db, self.cfg, (self.result, self.inputs, []))
        self.assertNotIn("LOCAL_ONLY_EVIDENCE", markdown)
        self.assertNotIn("raw_http_failure", markdown)
        self.assertNotIn("完整覆盖提示", markdown)
        self.assertIn("含金量8/10", markdown)
        self.assertNotIn("技：", markdown)

    def test_markdown_title_at_item_limit_matches_feishu_visible_length(self):
        card = self.result["cards"][0]
        card["title"] = "**虚构**"
        line = research._card_line(card, 1, self.inputs["records"][0])
        card["technology"] += "术" * (100 - research.visible_chars(line))
        research.validate_brief(self.result, self.inputs)
        lines, _, quality = bidradar.brief_layout(self.db, self.cfg, self.result, self.inputs, [])
        self.assertEqual(quality["item_chars"], [100])
        with patch.object(research, "selection_appendix", return_value=[]):
            payload, _, _ = bidradar.research_digest(self.db, self.cfg, (self.result, self.inputs, []))
        paragraphs = payload["content"]["post"]["zh_cn"]["content"][1:4]
        visible = "\n".join("".join(node["text"] for node in p) for p in paragraphs)
        self.assertEqual(visible, research.visible_text(lines[0]))
        self.assertEqual(len(visible), 100)
        anchor = next(node for paragraph in paragraphs for node in paragraph if node["tag"] == "a")
        self.assertEqual(anchor["text"], "虚构")

    def test_total_body_limit_includes_header_and_newline(self):
        with patch.object(research, "selection_appendix", return_value=[]), \
                patch.object(bidradar, "brief_layout", return_value=([], [], {})):
            payload, _, _ = bidradar.research_digest(self.db, self.cfg, (self.result, self.inputs, []))
        header = payload["content"]["post"]["zh_cn"]["content"][0][0]["text"]
        exact_line = "字" * (2000 - len(header) - 1)
        with patch.object(research, "selection_appendix", return_value=[]), \
                patch.object(bidradar, "brief_layout", return_value=([exact_line], [], {})):
            payload, _, _ = bidradar.research_digest(self.db, self.cfg, (self.result, self.inputs, []))
        visible = "\n".join("".join(n["text"] for n in p)
                            for p in payload["content"]["post"]["zh_cn"]["content"])
        self.assertEqual(len(visible), 2000)
        with patch.object(bidradar, "brief_layout", return_value=([exact_line + "字"], [], {})):
            with self.assertRaisesRegex(ValueError, "digest_body_too_long"):
                bidradar.research_digest(self.db, self.cfg, (self.result, self.inputs, []))

    def run_all_defer_cycle(self, *, source_error=False, unresolved=False, approved=True):
        self.result["cards"] = []
        self.result["triage"][0].update(decision="defer", reason="虚构测试资料不满足推荐门槛")
        if approved:
            self.store_approval()
        cfg = {**self.cfg, "schedule": {"hour": 0, "interval_days": 15,
                                         "max_catchup_days": 30, "retry_days": 2}}
        bidradar.save_schedule_state(self.db, {"next_due": "2020-01-01T00:00:00+08:00", "status": "pending"})
        if unresolved:
            self.db.execute("INSERT INTO outbox VALUES(?,?,?,'uncertain',?,?,?,NULL,NULL)",
                            ("unresolved", "digest", bidradar.local_day(cfg), "{}", "[]", "2099-01-01T00:00:00+00:00"))
        with patch.object(bidradar, "capture_feeds"), \
                patch.object(bidradar, "run_pipeline", return_value=approved), \
                patch.object(bidradar, "source_issues", return_value=["测试源失败"] if source_error else []):
            bidradar.scheduled_run(self.db, cfg)
        row = self.db.execute("SELECT value FROM meta WHERE key='schedule_state'").fetchone()
        return json.loads(row[0])["status"]

    def test_approved_all_defer_cycle_completes_without_sending_empty_recommendations(self):
        self.assertEqual(self.run_all_defer_cycle(), "complete")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)

    def test_all_defer_cycle_remains_partial_with_source_errors(self):
        self.assertEqual(self.run_all_defer_cycle(source_error=True), "partial")

    def test_all_defer_cycle_remains_partial_with_unresolved_delivery(self):
        self.assertEqual(self.run_all_defer_cycle(unresolved=True), "partial")

    def test_unapproved_all_defer_cycle_does_not_complete(self):
        self.assertEqual(self.run_all_defer_cycle(approved=False), "partial")


if __name__ == "__main__":
    unittest.main()
