import json
import unittest
from datetime import datetime, timedelta

from _bootstrap import make_contract, gl, transfers, reset_transfers, set_now, reset_now
from genlayer import tx_context

PARTY_A = "0x" + "a" * 40
PARTY_B = "0x" + "b" * 40
PARTY_B_UPPER = "0x" + "B" * 40  # same address as PARTY_B, different casing
INTRUDER = "0x" + "c" * 40
SOMEONE_ELSE = "0x" + "d" * 40

T0 = datetime(2026, 9, 1, 12, 0, 0)


def set_pipeline(render_value, prompt_value):
    gl.nondet.web.render = lambda url, mode="text": render_value
    gl.nondet.exec_prompt = lambda prompt, response_format="json": prompt_value


GOOD_PROMPT_TRIGGERED = {
    "FLIGHT_MATCH": "Match",
    "FRESHNESS": "Current",
    "STATUS": "Delayed",
    "DELAY_TEXT": "75 minutes",
}
GOOD_PROMPT_ONTIME = {
    "FLIGHT_MATCH": "Match",
    "FRESHNESS": "Current",
    "STATUS": "OnTime",
    "DELAY_TEXT": "N/A",
}

THREE_URLS = [
    "https://flightaware.com/live/AA100",
    "https://flightstats.com/AA100",
    "https://planefinder.net/AA100",
]


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        reset_transfers()
        set_now(T0)

    def tearDown(self):
        reset_now()

    def create(
        self,
        side_a="PayoutTriggered",
        stake=1000,
        required=None,
        threshold=60,
        party_b=PARTY_B,
        sender=PARTY_A,
    ):
        with tx_context(sender, stake):
            raw = self.c.create_agreement(
                party_b, "AA100", "2026-09-10", threshold, side_a, "test agreement", required
            )
        return json.loads(raw)

    def fund(self, agreement_id, stake=1000, sender=PARTY_B):
        with tx_context(sender, stake):
            raw = self.c.fund_agreement(agreement_id)
        return json.loads(raw)


class TestCreateAgreementValidation(BaseCase):
    def test_requires_positive_stake(self):
        with self.assertRaises(Exception):
            with tx_context(PARTY_A, 0):
                self.c.create_agreement(
                    PARTY_B, "AA100", "2026-09-10", 60, "PayoutTriggered", "x"
                )

    def test_party_b_cannot_equal_sender(self):
        with self.assertRaises(Exception):
            with tx_context(PARTY_A, 100):
                self.c.create_agreement(
                    PARTY_A, "AA100", "2026-09-10", 60, "PayoutTriggered", "x"
                )

    def test_party_b_cannot_equal_sender_different_casing(self):
        # Same real address as sender, just different letter-casing -
        # must still be caught, since canonicalization happens first.
        with self.assertRaises(Exception):
            with tx_context(PARTY_A, 100):
                self.c.create_agreement(
                    PARTY_A.upper().replace("0X", "0x"),
                    "AA100",
                    "2026-09-10",
                    60,
                    "PayoutTriggered",
                    "x",
                )

    def test_malformed_party_b_rejected(self):
        with self.assertRaises(Exception):
            with tx_context(PARTY_A, 100):
                self.c.create_agreement(
                    "not-an-address", "AA100", "2026-09-10", 60, "PayoutTriggered", "x"
                )

    def test_requires_flight_number(self):
        with self.assertRaises(Exception):
            with tx_context(PARTY_A, 100):
                self.c.create_agreement(PARTY_B, "  ", "2026-09-10", 60, "PayoutTriggered", "x")

    def test_rejects_negative_threshold(self):
        with self.assertRaises(Exception):
            with tx_context(PARTY_A, 100):
                self.c.create_agreement(PARTY_B, "AA100", "2026-09-10", -5, "PayoutTriggered", "x")

    def test_rejects_bad_side(self):
        with self.assertRaises(Exception):
            with tx_context(PARTY_A, 100):
                self.c.create_agreement(PARTY_B, "AA100", "2026-09-10", 60, "Sideways", "x")

    def test_success_locks_stake_and_status(self):
        rec = self.create(stake=500)
        self.assertEqual(rec["status"], "awaiting_funding")
        self.assertEqual(rec["stake"], "500")
        self.assertEqual(rec["party_a_address"], PARTY_A)
        self.assertEqual(rec["party_b_address"], PARTY_B)
        self.assertTrue(rec["funded_a"])
        self.assertFalse(rec["funded_b"])
        self.assertEqual(rec["created_at"], T0.isoformat())
        self.assertIsNone(rec["funded_at"])
        self.assertIsNone(rec["cancel_reason"])

    def test_party_b_stored_canonically_regardless_of_input_casing(self):
        rec = self.create(party_b=PARTY_B_UPPER)
        self.assertEqual(rec["party_b_address"], PARTY_B)  # stored lowercased

    def test_agreement_count_increments(self):
        self.create()
        self.create()
        self.assertEqual(self.c.total_agreements(), 2)


class TestFundAgreement(BaseCase):
    def test_wrong_sender_rejected(self):
        self.create()
        with self.assertRaises(Exception):
            self.fund("0", sender=INTRUDER)

    def test_wrong_amount_too_low_rejected(self):
        self.create(stake=1000)
        with self.assertRaises(Exception):
            self.fund("0", stake=500)

    def test_wrong_amount_too_high_rejected(self):
        self.create(stake=1000)
        with self.assertRaises(Exception):
            self.fund("0", stake=1500)

    def test_exact_match_succeeds(self):
        self.create(stake=1000)
        rec = self.fund("0", stake=1000)
        self.assertEqual(rec["status"], "funded")
        self.assertTrue(rec["funded_b"])
        self.assertEqual(rec["funded_at"], T0.isoformat())

    def test_funding_from_differently_cased_party_b_succeeds(self):
        # party_b was stored canonically lowercased; the real party_b
        # wallet funding with a different-cased signature must still
        # match, since the sender is canonicalized the same way.
        self.create(stake=1000, party_b=PARTY_B)
        rec = self.fund("0", stake=1000, sender=PARTY_B_UPPER)
        self.assertEqual(rec["status"], "funded")

    def test_double_funding_rejected(self):
        self.create(stake=1000)
        self.fund("0", stake=1000)
        with self.assertRaises(Exception):
            self.fund("0", stake=1000)

    def test_funding_nonexistent_agreement_rejected(self):
        with self.assertRaises(Exception):
            self.fund("999", stake=1000)


class TestReclaimUnfundedStake(BaseCase):
    def test_cannot_reclaim_before_timeout(self):
        self.create(stake=1000)
        with self.assertRaises(Exception):
            with tx_context(PARTY_A):
                self.c.reclaim_unfunded_stake("0")

    def test_cannot_reclaim_just_under_timeout(self):
        self.create(stake=1000)
        set_now(T0 + self.c.UNFUNDED_TIMEOUT - timedelta(seconds=1))
        with self.assertRaises(Exception):
            with tx_context(PARTY_A):
                self.c.reclaim_unfunded_stake("0")

    def test_can_reclaim_exactly_at_timeout(self):
        self.create(stake=1000)
        set_now(T0 + self.c.UNFUNDED_TIMEOUT)
        with tx_context(PARTY_A):
            rec = json.loads(self.c.reclaim_unfunded_stake("0"))
        self.assertEqual(rec["status"], "cancelled")
        self.assertEqual(rec["cancel_reason"], "unfunded_timeout")
        self.assertEqual(transfers(), [{"to": PARTY_A, "value": 1000}])

    def test_can_reclaim_well_after_timeout(self):
        self.create(stake=1000)
        set_now(T0 + self.c.UNFUNDED_TIMEOUT + timedelta(days=30))
        with tx_context(PARTY_A):
            rec = json.loads(self.c.reclaim_unfunded_stake("0"))
        self.assertEqual(rec["status"], "cancelled")

    def test_only_party_a_can_reclaim(self):
        self.create(stake=1000)
        set_now(T0 + self.c.UNFUNDED_TIMEOUT)
        with self.assertRaises(Exception):
            with tx_context(PARTY_B):
                self.c.reclaim_unfunded_stake("0")
        with self.assertRaises(Exception):
            with tx_context(INTRUDER):
                self.c.reclaim_unfunded_stake("0")

    def test_cannot_reclaim_once_funded(self):
        self.create(stake=1000)
        self.fund("0", stake=1000)
        set_now(T0 + self.c.UNFUNDED_TIMEOUT + timedelta(days=1))
        with self.assertRaises(Exception):
            with tx_context(PARTY_A):
                self.c.reclaim_unfunded_stake("0")

    def test_cannot_reclaim_twice(self):
        self.create(stake=1000)
        set_now(T0 + self.c.UNFUNDED_TIMEOUT)
        with tx_context(PARTY_A):
            self.c.reclaim_unfunded_stake("0")
        with self.assertRaises(Exception):
            with tx_context(PARTY_A):
                self.c.reclaim_unfunded_stake("0")


class TestForceCloseStalemate(BaseCase):
    def _fund_and_attempt_once(self):
        self.create(stake=1000)
        self.fund("0", stake=1000)
        stale_prompt = dict(GOOD_PROMPT_TRIGGERED, FRESHNESS="Stale")
        set_pipeline("page", stale_prompt)
        self.c.resolve_agreement("0", THREE_URLS)  # -> Indeterminate

    def test_cannot_close_without_any_resolution_attempt(self):
        self.create(stake=1000)
        self.fund("0", stake=1000)
        set_now(T0 + self.c.STALEMATE_TIMEOUT + timedelta(days=1))
        with self.assertRaises(Exception):
            self.c.force_close_stalemate("0")

    def test_cannot_close_before_timeout_even_with_attempt(self):
        self._fund_and_attempt_once()
        with self.assertRaises(Exception):
            self.c.force_close_stalemate("0")

    def test_can_close_after_timeout_with_attempt(self):
        self._fund_and_attempt_once()
        set_now(T0 + self.c.STALEMATE_TIMEOUT)
        rec = json.loads(self.c.force_close_stalemate("0"))
        self.assertEqual(rec["status"], "cancelled")
        self.assertEqual(rec["cancel_reason"], "stalemate_timeout")
        self.assertCountEqual(
            transfers(),
            [{"to": PARTY_A, "value": 1000}, {"to": PARTY_B, "value": 1000}],
        )

    def test_callable_by_anyone_since_outcome_is_fixed(self):
        self._fund_and_attempt_once()
        set_now(T0 + self.c.STALEMATE_TIMEOUT)
        with tx_context(SOMEONE_ELSE):
            rec = json.loads(self.c.force_close_stalemate("0"))
        self.assertEqual(rec["status"], "cancelled")
        self.assertCountEqual(
            transfers(),
            [{"to": PARTY_A, "value": 1000}, {"to": PARTY_B, "value": 1000}],
        )

    def test_cannot_close_awaiting_funding_agreement(self):
        self.create(stake=1000)
        set_now(T0 + self.c.STALEMATE_TIMEOUT + timedelta(days=1))
        with self.assertRaises(Exception):
            self.c.force_close_stalemate("0")

    def test_cannot_close_already_resolved_agreement(self):
        self.create(stake=1000)
        self.fund("0", stake=1000)
        set_pipeline("page", GOOD_PROMPT_TRIGGERED)
        self.c.resolve_agreement("0", THREE_URLS)
        set_now(T0 + self.c.STALEMATE_TIMEOUT + timedelta(days=1))
        with self.assertRaises(Exception):
            self.c.force_close_stalemate("0")


class TestResolveDomainPolicy(BaseCase):
    def test_rejects_too_few_sources(self):
        self.create()
        self.fund("0")
        with self.assertRaises(Exception):
            self.c.resolve_agreement("0", THREE_URLS[:2])

    def test_rejects_too_many_sources(self):
        self.create()
        self.fund("0")
        with self.assertRaises(Exception):
            self.c.resolve_agreement("0", THREE_URLS * 3)

    def test_cannot_resolve_before_funded(self):
        self.create()
        with self.assertRaises(Exception):
            self.c.resolve_agreement("0", THREE_URLS)

    def test_committed_domain_missing_rejected(self):
        self.create(required=["flightaware.com", "flightstats.com"])
        self.fund("0")
        set_pipeline("page", GOOD_PROMPT_TRIGGERED)
        bad_urls = [
            "https://flightaware.com/x",
            "https://planefinder.net/y",
            "https://flightradar24.com/z",
        ]
        with self.assertRaises(Exception):
            self.c.resolve_agreement("0", bad_urls)

    def test_committed_domains_present_succeeds(self):
        self.create(required=["flightaware.com", "flightstats.com"])
        self.fund("0")
        set_pipeline("page", GOOD_PROMPT_TRIGGERED)
        rec = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(rec["final_verdict"], "PayoutTriggered")

    def test_insufficient_distinct_reputable_domains_rejected(self):
        self.create()
        self.fund("0")
        with self.assertRaises(Exception):
            self.c.resolve_agreement(
                "0",
                [
                    "https://flightaware.com/a",
                    "https://flightaware.com/b",
                    "https://randomblog.com/c",
                ],
            )


class TestResolveOutcomesAndPayout(BaseCase):
    def test_party_a_wins_when_triggered_and_bet_triggered(self):
        self.create(side_a="PayoutTriggered", stake=1000)
        self.fund("0", stake=1000)
        set_pipeline("page", GOOD_PROMPT_TRIGGERED)
        rec = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(rec["winner"], "party_a")
        self.assertEqual(rec["status"], "resolved")
        self.assertEqual(rec["payout_amount"], "2000")
        self.assertEqual(transfers(), [{"to": PARTY_A, "value": 2000}])

    def test_party_b_wins_when_triggered_but_bet_no_payout(self):
        self.create(side_a="NoPayout", stake=1000)
        self.fund("0", stake=1000)
        set_pipeline("page", GOOD_PROMPT_TRIGGERED)
        rec = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(rec["winner"], "party_b")
        self.assertEqual(transfers(), [{"to": PARTY_B, "value": 2000}])

    def test_party_a_wins_when_ontime_and_bet_no_payout(self):
        self.create(side_a="NoPayout", stake=1000)
        self.fund("0", stake=1000)
        set_pipeline("page", GOOD_PROMPT_ONTIME)
        rec = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(rec["winner"], "party_a")

    def test_indeterminate_stale_sources_no_payout_and_stays_funded(self):
        self.create()
        self.fund("0")
        stale_prompt = dict(GOOD_PROMPT_TRIGGERED, FRESHNESS="Stale")
        set_pipeline("page", stale_prompt)
        rec = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(rec["final_verdict"], "Indeterminate")
        self.assertEqual(rec["status"], "funded")
        self.assertEqual(transfers(), [])

    def test_flight_mismatch_excluded(self):
        self.create()
        self.fund("0")
        mismatch_prompt = dict(GOOD_PROMPT_TRIGGERED, FLIGHT_MATCH="Mismatch")
        set_pipeline("page", mismatch_prompt)
        rec = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(rec["final_verdict"], "Indeterminate")

    def test_fetch_failure_handled_gracefully(self):
        self.create()
        self.fund("0")

        def raising_render(url, mode="text"):
            raise TimeoutError("no response")

        gl.nondet.web.render = raising_render
        rec = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(rec["final_verdict"], "Indeterminate")
        for r in rec["records"]:
            self.assertEqual(r["fetch_status"], "inaccessible")

    def test_cannot_resolve_after_already_resolved(self):
        self.create()
        self.fund("0")
        set_pipeline("page", GOOD_PROMPT_TRIGGERED)
        self.c.resolve_agreement("0", THREE_URLS)
        with self.assertRaises(Exception):
            self.c.resolve_agreement("0", THREE_URLS)

    def test_resolution_attempts_increments_on_indeterminate_and_evidence_overwritten(self):
        self.create()
        self.fund("0")
        stale_prompt = dict(GOOD_PROMPT_TRIGGERED, FRESHNESS="Stale")
        set_pipeline("page", stale_prompt)
        first = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(first["resolution_attempts"], 1)

        set_pipeline("page", GOOD_PROMPT_TRIGGERED)
        second = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(second["resolution_attempts"], 2)
        self.assertEqual(second["final_verdict"], "PayoutTriggered")
        for r in second["records"]:
            self.assertNotEqual(r.get("quality_flag"), "stale_or_unknown_freshness")

    def test_resolver_identity_does_not_affect_winner(self):
        # resolve_agreement is deliberately caller-open; whoever calls it
        # cannot redirect the payout, since the winner address was fixed
        # at create/fund time, not supplied by the resolver.
        self.create(side_a="PayoutTriggered", stake=1000)
        self.fund("0", stake=1000)
        set_pipeline("page", GOOD_PROMPT_TRIGGERED)
        with tx_context(SOMEONE_ELSE, 0):
            rec = json.loads(self.c.resolve_agreement("0", THREE_URLS))
        self.assertEqual(rec["winner"], "party_a")
        self.assertEqual(transfers(), [{"to": PARTY_A, "value": 2000}])


class TestCancellation(BaseCase):
    def test_single_consent_does_not_cancel(self):
        self.create()
        self.fund("0")
        with tx_context(PARTY_A):
            rec = json.loads(self.c.request_cancel("0"))
        self.assertEqual(rec["status"], "funded")
        self.assertTrue(rec["cancel_consent_a"])
        self.assertFalse(rec["cancel_consent_b"])
        self.assertEqual(transfers(), [])

    def test_mutual_consent_cancels_and_refunds_both(self):
        self.create(stake=1000)
        self.fund("0", stake=1000)
        with tx_context(PARTY_A):
            self.c.request_cancel("0")
        with tx_context(PARTY_B):
            rec = json.loads(self.c.request_cancel("0"))
        self.assertEqual(rec["status"], "cancelled")
        self.assertEqual(rec["cancel_reason"], "mutual_consent")
        self.assertCountEqual(
            transfers(),
            [{"to": PARTY_A, "value": 1000}, {"to": PARTY_B, "value": 1000}],
        )

    def test_cancel_before_funding_only_refunds_party_a(self):
        self.create(stake=1000)  # not funded by B yet
        with tx_context(PARTY_A):
            self.c.request_cancel("0")
        with tx_context(PARTY_B):
            rec = json.loads(self.c.request_cancel("0"))
        self.assertEqual(rec["status"], "cancelled")
        self.assertEqual(transfers(), [{"to": PARTY_A, "value": 1000}])

    def test_non_party_cannot_request_cancel(self):
        self.create()
        self.fund("0")
        with self.assertRaises(Exception):
            with tx_context(INTRUDER):
                self.c.request_cancel("0")

    def test_cannot_cancel_after_resolved(self):
        self.create()
        self.fund("0")
        set_pipeline("page", GOOD_PROMPT_TRIGGERED)
        self.c.resolve_agreement("0", THREE_URLS)
        with self.assertRaises(Exception):
            with tx_context(PARTY_A):
                self.c.request_cancel("0")


class TestViews(BaseCase):
    def test_get_agreement_roundtrips(self):
        created = self.create()
        fetched = json.loads(self.c.get_agreement("0"))
        self.assertEqual(fetched["agreement_id"], created["agreement_id"])

    def test_get_agreement_missing_raises(self):
        with self.assertRaises(Exception):
            self.c.get_agreement("does-not-exist")

    def test_total_agreements_zero_initially(self):
        self.assertEqual(self.c.total_agreements(), 0)


if __name__ == "__main__":
    unittest.main()
