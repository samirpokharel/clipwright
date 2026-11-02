import json
import unittest
from datetime import date

from clipwright import sources

TODAY = date(2026, 11, 2)
RULES = {"queries": ["q"], "watchlist": [], "min_minutes": 15, "min_views": 10000, "max_age_days": 365,
         "per_query": 10}

# shape of a real yt-dlp flat search entry (probed 2026-11-02)
FLAT = {"_type": "url", "ie_key": "Youtube", "id": "TBMMR7GBIKA",
        "title": "Unplugged ft. Akshat Gupta | Mahabharat | Ramayana | Spirituality",
        "channel": "Shubhankar Mishra ", "uploader": "Shubhankar Mishra ", "channel_id": "UCYalWwW79BdxmMTKUyBFj5g",
        "duration": 8680, "view_count": 5693697, "url": "https://www.youtube.com/watch?v=TBMMR7GBIKA"}


def cand(video_id="a", duration=3600, views=50000, channel="Chan", channel_id="UC1", **extra):
    out = {"id": video_id, "title": f"Talk {video_id}", "channel": channel, "channel_id": channel_id,
           "duration": duration, "views": views, "url": f"https://www.youtube.com/watch?v={video_id}"}
    out.update(extra)
    return out


CC_INFO = {"license": "Creative Commons Attribution license (reuse allowed)", "upload_date": "20261001",
           "channel_follower_count": 1200}


class CandidateTest(unittest.TestCase):
    def test_candidate_from_flat_maps_fields(self):
        c = sources.candidate_from_flat(FLAT)
        self.assertEqual(c, {"id": "TBMMR7GBIKA", "title": FLAT["title"], "channel": "Shubhankar Mishra",
                             "channel_id": "UCYalWwW79BdxmMTKUyBFj5g", "duration": 8680, "views": 5693697,
                             "url": "https://www.youtube.com/watch?v=TBMMR7GBIKA"})

    def test_candidate_without_id_is_none(self):
        self.assertIsNone(sources.candidate_from_flat({"title": "x"}))

    def test_candidate_missing_numbers_are_none_and_url_is_built(self):
        c = sources.candidate_from_flat({"id": "zz", "title": "t"})
        self.assertEqual((c["duration"], c["views"], c["url"]), (None, None, "https://www.youtube.com/watch?v=zz"))


class PrefilterTest(unittest.TestCase):
    def test_dedupes_across_queries(self):
        out = sources.prefilter([cand("a"), cand("b"), cand("a")], RULES, set(), [])
        self.assertEqual([c["id"] for c in out], ["a", "b"])

    def test_drops_seen_short_and_low_views(self):
        cands = [cand("seen"), cand("short", duration=600), cand("low", views=500), cand("ok")]
        out = sources.prefilter(cands, RULES, {"seen"}, [])
        self.assertEqual([c["id"] for c in out], ["ok"])

    def test_missing_views_kept_only_for_watchlist(self):
        cands = [cand("none", views=None), cand("wl", views=None, channel="Dr Podcast")]
        out = sources.prefilter(cands, RULES, set(), ["Dr Podcast"])
        self.assertEqual([c["id"] for c in out], ["wl"])
        self.assertTrue(out[0]["watchlist"])

    def test_watchlist_matches_channel_id_in_url(self):
        out = sources.prefilter([cand("x", views=None, channel_id="UCabc")], RULES, set(),
                                ["https://www.youtube.com/channel/UCabc/videos"])
        self.assertEqual([c["id"] for c in out], ["x"])

    def test_missing_duration_dropped(self):
        self.assertEqual(sources.prefilter([cand("d", duration=None)], RULES, set(), []), [])

    def test_non_watchlist_flagged_false(self):
        self.assertFalse(sources.prefilter([cand("a")], RULES, set(), [])[0]["watchlist"])


class EnrichTest(unittest.TestCase):
    def test_cc_by_flags_reuse_ok(self):
        c = sources.enrich(cand(), CC_INFO, TODAY)
        self.assertEqual((c["license_kind"], c["reuse_ok"]), ("cc-by", True))
        self.assertEqual(c["upload_date"], "2026-10-01")
        self.assertEqual((c["age_days"], c["followers"]), (32, 1200))

    def test_standard_licence_when_info_has_none(self):
        c = sources.enrich(cand(), {"license": None, "upload_date": "20250101"}, TODAY)
        self.assertEqual((c["license_kind"], c["reuse_ok"]), ("standard", False))

    def test_without_info_is_unchecked(self):
        c = sources.enrich(cand(), None, TODAY)
        self.assertEqual(c["license_kind"], "unchecked")
        self.assertEqual(c["license_label"], "Licence not checked")
        self.assertFalse(c["reuse_ok"])
        self.assertIsNone(c["age_days"])

    def test_bad_upload_date_gives_unknown_age(self):
        self.assertIsNone(sources.enrich(cand(), {"upload_date": "soon"}, TODAY)["age_days"])


class PostfilterRankTest(unittest.TestCase):
    def test_age_filter_and_unknown_age(self):
        old = sources.enrich(cand("old"), {"upload_date": "20240101"}, TODAY)
        new = sources.enrich(cand("new"), {"upload_date": "20261001"}, TODAY)
        unknown = sources.enrich(cand("unk"), None, TODAY)
        out = sources.postfilter([old, new, unknown], RULES)
        self.assertEqual([c["id"] for c in out], ["new", "unk"])

    def test_no_age_limit_keeps_everything(self):
        old = sources.enrich(cand("old"), {"upload_date": "20100101"}, TODAY)
        self.assertEqual(len(sources.postfilter([old], dict(RULES, max_age_days=None))), 1)

    def test_select_for_enrichment_takes_watchlist_then_views(self):
        cands = [cand("a", views=10), cand("b", views=999), dict(cand("c", views=5), watchlist=True)]
        self.assertEqual([c["id"] for c in sources.select_for_enrichment(cands, 2)], ["c", "b"])

    def test_rank_order(self):
        cc = sources.enrich(cand("cc", views=10), CC_INFO, TODAY)
        wl = dict(sources.enrich(cand("wl", views=20), {"upload_date": "20261001"}, TODAY), watchlist=True)
        big = sources.enrich(cand("big", views=900000), {"upload_date": "20261001"}, TODAY)
        small = sources.enrich(cand("small", views=50000), {"upload_date": "20261001"}, TODAY)
        ranked = sources.rank([small, big, wl, cc])
        self.assertEqual([c["id"] for c in ranked], ["cc", "wl", "big", "small"])


class OutputTest(unittest.TestCase):
    def enriched(self):
        return [sources.enrich(dict(cand("cc", duration=8680, views=5693697, title="Ramayana, Rāma kathā"),
                                    watchlist=False), CC_INFO, TODAY)]

    def test_markdown_rows(self):
        md = sources.to_markdown("mythology", self.enriched(), "2026-11-02 10:00")
        for expected in ("Ramayana, Rāma kathā", "Chan", "https://www.youtube.com/watch?v=cc", "2:24",
                         "5,693,697", "Creative Commons Attribution (CC BY)", "permission: unchecked", "- [ ]"):
            self.assertIn(expected, md)

    def test_health_markdown_has_credentials_reminder(self):
        md = sources.to_markdown("health", self.enriched(), "now")
        self.assertIn("credentials", md)
        self.assertNotIn("credentials", sources.to_markdown("tech", self.enriched(), "now"))

    def test_markdown_for_nothing_found(self):
        self.assertIn("No videos", sources.to_markdown("tech", [], "now"))

    def test_json_round_trip_non_ascii(self):
        cands = self.enriched()
        text = sources.to_json(cands)
        self.assertIn("Rāma", text)
        self.assertEqual(json.loads(text), cands)


if __name__ == "__main__":
    unittest.main()
