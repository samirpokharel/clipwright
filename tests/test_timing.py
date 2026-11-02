import unittest

from clipwright.timing import match_key_words, to_clip_time


def w(text, start_s, end_s):
    return {"text": text, "start": int(start_s * 1000), "end": int(end_s * 1000)}


WORDS = [
    w(" He", 10.0, 10.2), w(" was", 10.2, 10.4), w(" powerful,", 10.4, 11.0),
    w(" and", 11.0, 11.2), w(" had", 11.2, 11.4), w(" an", 11.4, 11.5),
    w(" iron", 20.0, 20.3), w(" core.", 20.3, 20.8), w(" Really", 21.0, 21.5),
]


class ToClipTimeTest(unittest.TestCase):
    def test_single_range_offsets_from_range_start(self):
        self.assertAlmostEqual(to_clip_time(12.0, [(10.0, 20.0)]), 2.0)

    def test_two_ranges_skip_the_cut(self):
        ranges = [(10.0, 12.0), (20.0, 25.0)]
        self.assertAlmostEqual(to_clip_time(21.0, ranges), 3.0)

    def test_time_in_cut_returns_none(self):
        self.assertIsNone(to_clip_time(15.0, [(10.0, 12.0), (20.0, 25.0)]))

    def test_offsets_replace_cumulative_sum_for_crossfaded_ranges(self):
        # a 0.2 s crossfade pulls the second range 0.2 s earlier than plain concatenation
        ranges = [(10.0, 12.0), (20.0, 25.0)]
        self.assertAlmostEqual(to_clip_time(21.0, ranges, offsets=[0.0, 1.8]), 2.8)
        self.assertAlmostEqual(to_clip_time(11.0, ranges, offsets=[0.0, 1.8]), 1.0)


class MatchKeyWordsTest(unittest.TestCase):
    def test_match_is_case_and_punctuation_insensitive(self):
        matches, unmatched = match_key_words(WORDS, ["Powerful"], [(10.0, 25.0)])
        self.assertEqual(unmatched, [])
        self.assertAlmostEqual(matches[0][0], 0.4)
        self.assertEqual(matches[0][1], "Powerful")

    def test_phrase_matches_consecutive_words(self):
        matches, unmatched = match_key_words(WORDS, ["iron core"], [(10.0, 25.0)])
        self.assertEqual(unmatched, [])
        self.assertEqual(len(matches), 1)

    def test_unmatched_key_word_listed(self):
        matches, unmatched = match_key_words(WORDS, ["powerful", "nonsense"], [(10.0, 25.0)])
        self.assertEqual([k for _, k in matches], ["powerful"])
        self.assertEqual(unmatched, ["nonsense"])

    def test_match_times_map_through_cuts(self):
        # keep 10-12 s and 20-25 s: "iron" starts at source 20.0, clip time 2.0
        ranges = [(10.0, 12.0), (20.0, 25.0)]
        matches, _ = match_key_words(WORDS, ["iron core"], ranges)
        self.assertAlmostEqual(matches[0][0], 2.0)

    def test_match_uses_offsets(self):
        ranges = [(10.0, 12.0), (20.0, 25.0)]
        matches, _ = match_key_words(WORDS, ["iron core"], ranges, offsets=[0.0, 1.8])
        self.assertAlmostEqual(matches[0][0], 1.8)

    def test_words_in_a_cut_do_not_match(self):
        matches, unmatched = match_key_words(WORDS, ["iron"], [(10.0, 12.0)])
        self.assertEqual(matches, [])
        self.assertEqual(unmatched, ["iron"])

    def test_first_occurrence_only(self):
        words = [w("go", 1.0, 1.2), w("go", 2.0, 2.2)]
        matches, _ = match_key_words(words, ["go"], [(0.0, 5.0)])
        self.assertEqual(len(matches), 1)
        self.assertAlmostEqual(matches[0][0], 1.0)


if __name__ == "__main__":
    unittest.main()
