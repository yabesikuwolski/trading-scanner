import unittest

from dashboard.ai_advisory import build_ai_advisory_view


class DashboardAiAdvisoryTests(unittest.TestCase):
    def test_available_review_exposes_persisted_fields(self):
        view = build_ai_advisory_view({
            "ai_status": "available",
            "ai_decision": "WATCH",
            "ai_quality_score": 62,
            "ai_confidence": "MEDIUM",
            "ai_summary": "Wait for confirmation.",
            "ai_reasons": '["Structure is mixed"]',
            "ai_invalidations": ["H1 level breaks"],
            "ai_risk_note": "Size is feasible under configured rules.",
            "ai_reviewed_at": "2026-10-09T12:00:00+00:00",
        })
        self.assertTrue(view["available"])
        self.assertEqual(view["decision"], "WATCH")
        self.assertEqual(view["reasons"], ["Structure is mixed"])
        self.assertEqual(view["invalidations"], ["H1 level breaks"])
        self.assertIn("completed", view["status_text"])

    def test_disabled_unavailable_and_invalid_are_distinct(self):
        labels = {
            status: build_ai_advisory_view({"ai_status": status})["status_text"]
            for status in ("disabled", "unavailable", "invalid_response")
        }
        self.assertEqual(len(set(labels.values())), 3)
        self.assertEqual(build_ai_advisory_view({})["status"], "not_reviewed")


if __name__ == "__main__":
    unittest.main()
