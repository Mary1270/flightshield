import unittest
from _bootstrap import make_contract


class TestExtractDomain(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_bare_domain(self):
        self.assertEqual(self.c._extract_domain("flightaware.com"), "flightaware.com")

    def test_full_url(self):
        self.assertEqual(
            self.c._extract_domain("https://www.flightaware.com/live/flight/AA100"),
            "flightaware.com",
        )

    def test_with_port(self):
        self.assertEqual(self.c._extract_domain("flightstats.com:8443/x"), "flightstats.com")

    def test_with_query_and_fragment(self):
        self.assertEqual(
            self.c._extract_domain("flightradar24.com/data?x=1#section"), "flightradar24.com"
        )

    def test_multi_part_suffix(self):
        self.assertEqual(self.c._extract_domain("https://flights.example.co.uk/x"), "example.co.uk")

    def test_case_insensitive(self):
        self.assertEqual(self.c._extract_domain("FlightAware.COM/x"), "flightaware.com")


class TestParseDelayMinutes(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_plain_minutes(self):
        self.assertEqual(self.c._parse_delay_minutes("47 minutes", "Delayed"), 47)

    def test_min_abbreviation(self):
        self.assertEqual(self.c._parse_delay_minutes("47 min late", "Delayed"), 47)

    def test_hours_and_minutes_no_space(self):
        self.assertEqual(self.c._parse_delay_minutes("1h 20m", "Delayed"), 80)

    def test_hours_and_minutes_with_words(self):
        self.assertEqual(self.c._parse_delay_minutes("1 hour 20 minutes", "Delayed"), 80)

    def test_hours_and_minutes_with_and(self):
        self.assertEqual(self.c._parse_delay_minutes("1 hour and 20 minutes", "Delayed"), 80)

    def test_hours_only(self):
        self.assertEqual(self.c._parse_delay_minutes("2h", "Delayed"), 120)

    def test_hours_only_with_word(self):
        self.assertEqual(self.c._parse_delay_minutes("2 hours", "Delayed"), 120)

    def test_decimal_hours_converted_precisely(self):
        # Real bug found by steward review: the old parser silently
        # truncated "1.5 hours" to 1 hour (60 min) via int(), or under
        # the old fallback path dropped the decimal point entirely
        # ("1.5" -> digits "15" -> 15 minutes). Must be exactly 90.
        self.assertEqual(self.c._parse_delay_minutes("1.5 hours", "Delayed"), 90)

    def test_decimal_minutes_rounds(self):
        self.assertEqual(self.c._parse_delay_minutes("45.5 minutes", "Delayed"), 46)

    def test_ontime_forces_zero_regardless_of_text(self):
        self.assertEqual(self.c._parse_delay_minutes("garbage", "OnTime"), 0)

    def test_cancelled_forces_zero_regardless_of_text(self):
        self.assertEqual(self.c._parse_delay_minutes("n/a", "Cancelled"), 0)

    def test_diverted_forces_zero_regardless_of_text(self):
        # Diverted triggers a payout regardless of any numeric delay
        # (see _deterministic_verdict) - it must never be excluded
        # from consensus just because delay_text is empty or "N/A".
        self.assertEqual(self.c._parse_delay_minutes("N/A", "Diverted"), 0)
        self.assertEqual(self.c._parse_delay_minutes("", "Diverted"), 0)

    def test_bare_number_fallback(self):
        self.assertEqual(self.c._parse_delay_minutes("75", "Delayed"), 75)

    def test_unparseable_returns_none(self):
        self.assertIsNone(self.c._parse_delay_minutes("delayed a bit", "Delayed"))

    def test_empty_text_unparseable_when_delayed(self):
        self.assertIsNone(self.c._parse_delay_minutes("", "Delayed"))

    def test_hyphen_range_is_unparseable_not_averaged_or_concatenated(self):
        # Real bug found by steward review: the old fallback concatenated
        # every digit with no regard for structure, turning "30-45
        # minutes" into 3045. Must now be safely Indeterminate instead.
        self.assertIsNone(self.c._parse_delay_minutes("30-45 minutes", "Delayed"))

    def test_word_range_is_unparseable(self):
        self.assertIsNone(self.c._parse_delay_minutes("1 to 2 hours", "Delayed"))

    def test_en_dash_range_is_unparseable(self):
        self.assertIsNone(self.c._parse_delay_minutes("30\u201345 minutes", "Delayed"))

    def test_compound_with_ambiguous_decimal_hour_is_unparseable(self):
        # "1.5 hours 30 minutes" self-contradicts (half an hour is
        # already 30 minutes) - refuse rather than silently pick one.
        self.assertIsNone(self.c._parse_delay_minutes("1.5 hours 30 minutes", "Delayed"))

    def test_old_bug_no_longer_concatenates_compound_digits(self):
        # Old fallback would have produced 130 (concatenating "1" and
        # "30"); correct answer is 90.
        result = self.c._parse_delay_minutes("1 hour 30 minutes", "Delayed")
        self.assertEqual(result, 90)
        self.assertNotEqual(result, 130)


class TestDeterministicVerdict(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_cancelled_always_triggers(self):
        self.assertEqual(self.c._deterministic_verdict("Cancelled", 0, 60), "PayoutTriggered")

    def test_diverted_always_triggers(self):
        self.assertEqual(self.c._deterministic_verdict("Diverted", 0, 60), "PayoutTriggered")

    def test_delayed_above_threshold_triggers(self):
        self.assertEqual(self.c._deterministic_verdict("Delayed", 90, 60), "PayoutTriggered")

    def test_delayed_exactly_at_threshold_triggers(self):
        self.assertEqual(self.c._deterministic_verdict("Delayed", 60, 60), "PayoutTriggered")

    def test_delayed_below_threshold_no_payout(self):
        self.assertEqual(self.c._deterministic_verdict("Delayed", 30, 60), "NoPayout")

    def test_ontime_no_payout(self):
        self.assertEqual(self.c._deterministic_verdict("OnTime", 0, 60), "NoPayout")


class TestValidateRequiredDomains(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_none_returns_empty(self):
        self.assertEqual(self.c._validate_and_normalize_required_domains(None), [])

    def test_empty_list_returns_empty(self):
        self.assertEqual(self.c._validate_and_normalize_required_domains([]), [])

    def test_too_few_rejected(self):
        with self.assertRaises(Exception):
            self.c._validate_and_normalize_required_domains(["flightaware.com"])

    def test_too_many_rejected(self):
        with self.assertRaises(Exception):
            self.c._validate_and_normalize_required_domains(
                ["flightaware.com", "flightstats.com", "flightradar24.com",
                 "flightview.com", "planefinder.net", "extra-not-real.com"]
            )

    def test_unreputable_domain_rejected(self):
        with self.assertRaises(Exception):
            self.c._validate_and_normalize_required_domains(
                ["flightaware.com", "not-a-real-tracker.com"]
            )

    def test_duplicate_rejected(self):
        with self.assertRaises(Exception):
            self.c._validate_and_normalize_required_domains(
                ["flightaware.com", "flightaware.com"]
            )

    def test_normalized_and_sorted(self):
        result = self.c._validate_and_normalize_required_domains(
            ["https://FlightStats.com/x", "flightaware.com"]
        )
        self.assertEqual(result, ["flightaware.com", "flightstats.com"])


class TestAnnotateSources(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_marks_reputable(self):
        out = self.c._annotate_sources(["https://flightaware.com/x"])
        self.assertTrue(out[0]["is_reputable"])

    def test_marks_non_reputable(self):
        out = self.c._annotate_sources(["https://randomblog.com/x"])
        self.assertFalse(out[0]["is_reputable"])

    def test_marks_duplicate_domain(self):
        out = self.c._annotate_sources(
            ["https://flightaware.com/a", "https://flightaware.com/b"]
        )
        self.assertFalse(out[0]["is_duplicate_domain"])
        self.assertTrue(out[1]["is_duplicate_domain"])

    def test_regional_subdomain_of_allowlisted_domain_is_reputable(self):
        # Real bug found during live testing: flightaware.com serves
        # regional subdomains (uk.flightaware.com, m.flightaware.com)
        # that are the same tracker, not a separate unlisted site.
        out = self.c._annotate_sources(["https://uk.flightaware.com/live/flight/BA286"])
        self.assertTrue(out[0]["is_reputable"])
        self.assertEqual(out[0]["canonical_domain"], "flightaware.com")

    def test_two_different_subdomains_of_same_tracker_dedupe_to_one_source(self):
        out = self.c._annotate_sources(
            [
                "https://uk.flightaware.com/live/flight/BA286",
                "https://m.flightaware.com/live/flight/BA286",
            ]
        )
        self.assertFalse(out[0]["is_duplicate_domain"])
        self.assertTrue(out[1]["is_duplicate_domain"])

    def test_unrelated_domain_containing_allowlisted_name_is_not_reputable(self):
        # e.g. "notflightaware.com" or "flightaware.com.evil.tld" must
        # NOT be treated as a subdomain of flightaware.com.
        out = self.c._annotate_sources(["https://flightaware.com.evil.tld/x"])
        self.assertFalse(out[0]["is_reputable"])


class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def _row(self, verdict, quality="ok"):
        return {"own_verdict": verdict, "quality_flag": quality}

    def test_indeterminate_below_min_sources(self):
        verdict, meta = self.c._aggregate([self._row("PayoutTriggered")])
        self.assertEqual(verdict, "Indeterminate")
        self.assertEqual(meta["independent_total"], 1)

    def test_two_agreeing_trigger(self):
        rows = [self._row("PayoutTriggered"), self._row("PayoutTriggered")]
        verdict, meta = self.c._aggregate(rows)
        self.assertEqual(verdict, "PayoutTriggered")
        self.assertEqual(meta["independent_total"], 2)

    def test_two_agreeing_no_payout(self):
        rows = [self._row("NoPayout"), self._row("NoPayout")]
        verdict, _ = self.c._aggregate(rows)
        self.assertEqual(verdict, "NoPayout")

    def test_tied_split_is_indeterminate(self):
        rows = [self._row("PayoutTriggered"), self._row("NoPayout")]
        verdict, _ = self.c._aggregate(rows)
        self.assertEqual(verdict, "Indeterminate")

    def test_majority_with_dissent_resolves(self):
        rows = [self._row("PayoutTriggered"), self._row("PayoutTriggered"), self._row("NoPayout")]
        verdict, _ = self.c._aggregate(rows)
        self.assertEqual(verdict, "PayoutTriggered")

    def test_non_ok_quality_excluded(self):
        rows = [
            self._row("PayoutTriggered"),
            self._row("PayoutTriggered", quality="stale_or_unknown_freshness"),
        ]
        verdict, meta = self.c._aggregate(rows)
        self.assertEqual(verdict, "Indeterminate")
        self.assertEqual(meta["independent_total"], 1)


class TestCanonicalAddress(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_valid_address_passes_through_lowercased(self):
        addr = "0x" + "A" * 40
        self.assertEqual(self.c._canonical_address(addr), "0x" + "a" * 40)

    def test_mixed_case_normalizes_to_same_canonical_form(self):
        upper = "0x" + "AB" * 20
        lower = "0x" + "ab" * 20
        self.assertEqual(self.c._canonical_address(upper), self.c._canonical_address(lower))

    def test_missing_0x_prefix_rejected(self):
        with self.assertRaises(Exception):
            self.c._canonical_address("A" * 42)

    def test_too_short_rejected(self):
        with self.assertRaises(Exception):
            self.c._canonical_address("0xA")

    def test_too_long_rejected(self):
        with self.assertRaises(Exception):
            self.c._canonical_address("0x" + "A" * 41)

    def test_non_hex_characters_rejected(self):
        with self.assertRaises(Exception):
            self.c._canonical_address("0x" + "G" * 40)

    def test_empty_rejected(self):
        with self.assertRaises(Exception):
            self.c._canonical_address("")

    def test_whitespace_only_rejected(self):
        with self.assertRaises(Exception):
            self.c._canonical_address("   ")


if __name__ == "__main__":
    unittest.main()
