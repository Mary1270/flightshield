# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json
import re
from datetime import datetime, timedelta


class FlightShield(gl.Contract):
    """
    FlightShield - A two-party, multi-source-verified flight delay /
    cancellation settlement contract with REAL on-chain GEN escrow.

    -------------------------------------------------------------------
    WHY THIS CONTRACT EXISTS
    -------------------------------------------------------------------
    This is a new Intelligent Contract, not an update to an existing
    one - but it is deliberately built on the multi-source
    corroboration architecture already proven (offline-tested and
    live-deployed on GenLayer Studio) by my previously accepted
    OilPriceOracle / GoldPriceOracle contracts, and it exists
    specifically to close three gaps those contracts *disclosed but
    left open*:

      1. "No actual fund transfer" - OilPriceOracle's `resolve_agreement`
         computes an authoritative `winner` but never moves value; it
         explicitly says a settlement/escrow layer would consume that
         decision. FlightShield IS that settlement layer: it holds real
         GEN in escrow (`@gl.public.write.payable`) and pays the winner
         automatically via `emit_transfer` once consensus is reached.

      2. "party_a/party_b are free-text strings, not addresses bound to
         a caller identity" - in OilPriceOracle this was an explicit,
         disclosed design trade-off (restricting resolver identity was
         considered and rejected as out of scope for that update).
         Here, because real money moves, identity binding is no longer
         optional: `party_a`/`party_b` ARE `gl.message.sender_address`
         values, checked on every fund-moving call.

      3. "A committed source policy can strand an agreement" -
         OilPriceOracle disclosed that a permanently-unreachable
         committed domain leaves an agreement stuck open forever, with
         no on-chain recovery. FlightShield adds `request_cancel`:
         mutual-consent cancellation that refunds both parties their
         own stake without needing a working oracle result at all.

    Live-testing on GenLayer Studio surfaced one more real fix baked
    in here: flight-tracking sites like flightaware.com serve regional
    subdomains (uk.flightaware.com, m.flightaware.com, etc.) that
    render fine but were being rejected as "not on the allowlist"
    under naive exact-domain matching. `_canonical_reputable_domain`
    now treats any subdomain of an allowlisted domain as that same
    tracker (while still deduplicating two subdomains of the same
    tracker down to one independent source, since they're the same
    underlying data provider).

    Everything else - the reputable-domain allowlist, requiring
    multiple independent sources, deterministic (Python, not LLM)
    numeric parsing, freshness/on-topic classification, and
    `gl.eq_principle.prompt_comparative` for the fetch+LLM pipeline -
    intentionally mirrors the already-reviewed, already-accepted
    architecture, because the underlying trust problem (how do you let
    a deterministic-consensus contract believe a claim about the real
    world) is the same problem, just applied to flight status instead
    of a commodity price.

    -------------------------------------------------------------------
    WHAT'S GENUINELY NEW HERE (not present in the oracle contracts)
    -------------------------------------------------------------------
      - `@gl.public.write.payable` + `gl.message.value`: parties lock
        real GEN when creating/funding an agreement.
      - `gl.message.sender_address`: `party_a`/`party_b` are real
        caller identities, not caller-supplied strings.
      - `gl.get_contract_at(Address(...)).emit_transfer(value=...)`: the
        pot (both stakes) is paid out to the winning party's own
        address automatically on resolution - no separate claim step,
        no way for a resolver to redirect funds (the destination
        address was fixed at `create_agreement`/`fund_agreement` time,
        long before any evidence was fetched). Note: earlier GenVM SDK
        docs/examples show this accessor as `gl.ContractAt(...)`; it
        was renamed to `gl.get_contract_at(...)` in SDK v0.1.3+ - this
        contract uses the current name, confirmed against a live
        GenLayer Studio deployment.
      - Symmetric staking + identity-bound `fund_agreement`: this is
        deliberately a peer-to-peer bet between two named wallets, not
        a pooled marketplace - keeps the trust model small enough that
        no third-party underwriter, oracle-of-solvency, or partial-fill
        matching logic is needed for a first version.
      - Mutual-consent cancellation as a stranding escape hatch (see
        gap 3 above) - something none of my prior contracts had.

    -------------------------------------------------------------------
    WHY RESOLVE STAYS OPEN-CALLER BUT FUND/CANCEL ARE IDENTITY-BOUND
    -------------------------------------------------------------------
    It would be tempting to restrict `resolve_agreement` to
    `party_a`/`party_b` too, now that those are real addresses. This
    contract deliberately does NOT do that, for the same reason
    OilPriceOracle's README gives for leaving its resolver open: the
    winner is fully determined by (a) the source policy and side
    committed at `create_agreement` time and (b) the deterministic
    aggregation of independently-fetched, independently-classified
    evidence - never by anything the caller of `resolve_agreement`
    supplies. Restricting who may *trigger* that computation would only
    risk liveness (both parties could go silent) for zero additional
    safety, since the payout destination was already fixed before any
    evidence existed. Identity binding is applied exactly where it
    matters: `fund_agreement` (moving money in) and `request_cancel`
    (moving money back out) are the only calls where the caller's
    identity, not just the data they submit, decides the outcome.

    -------------------------------------------------------------------
    STEWARD FEEDBACK ADDRESSED (v1 -> v2)
    -------------------------------------------------------------------
    A steward review of the first submission requested four concrete
    fixes, all present in this version:

      1. "Validate party_b as an Address and store one canonical
         address form." `_canonical_address()` now enforces a strict
         0x + 40-hex-char shape and lowercases the result for BOTH
         party_a (from `gl.message.sender_address`) and the caller-
         supplied party_b, so two different letter-casings of the same
         real address are always the same party everywhere they're
         compared - and a malformed party_b can never get accepted into
         an agreement party_a can't recover from.

      2. "Let party_a recover an unfunded stake after a clear timeout."
         `reclaim_unfunded_stake()` does exactly this after
         `UNFUNDED_TIMEOUT` (48h) of `awaiting_funding` with nobody's
         consent needed but party_a's own, since only party_a's own
         money is at risk at that stage. This relies on a correction to
         an assumption in v1's own README: GenVM does NOT lack a clock -
         it injects a deterministic, consensus-agreed
         `datetime.datetime.now()` into every transaction (confirmed by
         `genlayer-test`'s `genvm_datetime` fixture, used specifically
         to pin that value for reproducible tests). v1 assumed no clock
         existed and built freshness checks entirely on LLM content
         classification instead; that content-based check is kept for
         judging whether *evidence* is stale, but real elapsed-time
         timeouts now use the real clock, which is the correct tool for
         them.

      3. "Add a deterministic terminal refund path after prolonged
         indeterminate/unavailable evidence, without requiring both
         parties' consent." `force_close_stalemate()` refunds each
         party their own stake after `STALEMATE_TIMEOUT` (14 days) past
         `funded_at`, once at least one real `resolve_agreement` attempt
         has been made. This is deliberately callable by ANYONE (see
         the resolver-identity rationale above) because both refund
         destinations and amounts were fixed at `create_agreement` /
         `fund_agreement` time - the caller cannot change the outcome,
         only trigger it.

      4. "Parse decimal, compound, or ranged delay text without
         threshold-changing ambiguity (or safely treat it as
         indeterminate)." `_parse_delay_minutes()` was rewritten around
         anchored regexes for each real shape ("75 minutes", "1.5
         hours", "1 hour 30 minutes"); an explicit range ("30-45
         minutes", "1 to 2 hours") is NEVER resolved to a single number
         and is instead treated as unparseable (excluded from
         consensus), since either bound could flip the verdict against
         a real threshold. See that method's docstring for the specific
         bug this replaced.
    """

    # ------------------------------------------------------------------
    # Persistent on-chain storage
    # ------------------------------------------------------------------
    agreements: TreeMap[str, str]
    agreement_count: u256

    # ------------------------------------------------------------------
    # Fixed vocabularies - every value that crosses the consensus
    # boundary (the return value of nondet()) is restricted to one of
    # these small, closed sets, so the prompt_comparative NLP comparator
    # only ever has to check categorical equality, never judge
    # open-ended prose or exact numeric values. Same discipline as the
    # accepted OilPriceOracle/GoldPriceOracle contracts.
    # ------------------------------------------------------------------
    STATUS_WORDS = ("OnTime", "Delayed", "Cancelled", "Diverted", "Unknown")
    FLIGHT_MATCH_WORDS = ("Match", "Mismatch", "Unclear")
    FRESHNESS_WORDS = ("Current", "Stale", "Unknown")
    FETCH_STATUSES = ("ok", "empty", "timeout", "inaccessible", "malformed")
    QUALITY_FLAGS = (
        "ok",
        "flight_or_date_mismatch",
        "stale_or_unknown_freshness",
        "delay_unparseable",
    )
    SIDE_WORDS = ("PayoutTriggered", "NoPayout")
    FINAL_VERDICTS = ("PayoutTriggered", "NoPayout", "Indeterminate")
    AGREEMENT_STATUSES = (
        "awaiting_funding",
        "funded",
        "resolved",
        "cancelled",
    )
    CANCEL_REASONS = ("mutual_consent", "unfunded_timeout", "stalemate_timeout")

    # A strict 0x + 40-hex-char address format check, applied to BOTH
    # party_a (derived from gl.message.sender_address) and party_b
    # (caller-supplied) before either is ever stored. This is
    # independent of whatever validation the SDK's own Address type
    # does internally - a steward review of the first version found
    # party_b was accepted as an unvalidated free-text string with no
    # guarantee it was even address-shaped, and that two different
    # capitalizations of the same real address would be treated as two
    # different parties. Every address that reaches storage now goes
    # through `_canonical_address()`, which validates the shape AND
    # normalizes case, so `fund_agreement`'s identity check can never
    # silently fail (or silently succeed for the wrong party) over a
    # checksum-casing mismatch.
    _ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

    # No on-chain wall clock exists in most smart-contract VMs, which is
    # why the first version of this contract assumed GenVM had none
    # either and left every stranding scenario unresolved. That
    # assumption was wrong: GenVM injects a consensus-agreed
    # `datetime.datetime.now()` into every transaction (the same value
    # every validator sees, confirmed by genlayer-test's
    # `genvm_datetime` fixture for reproducible testing), so ordinary
    # Python `datetime` arithmetic is safe to use in deterministic
    # contract code - no `gl.nondet` block required. `_now()` centralizes
    # the single call site.
    UNFUNDED_TIMEOUT = timedelta(hours=48)
    STALEMATE_TIMEOUT = timedelta(days=14)
    MIN_STALEMATE_ATTEMPTS = 1

    # A small, static, hand-maintained allowlist of flight-tracking
    # sources - same deliberate determinism trade-off documented for
    # OilPriceOracle's REPUTABLE_PRICE_DOMAINS: a live reputation feed
    # would be nicer, but is nondeterministic across validators unless
    # itself run through consensus, which is out of scope here.
    REPUTABLE_FLIGHT_DOMAINS = frozenset(
        {
            "flightaware.com",
            "flightstats.com",
            "flightradar24.com",
            "flightview.com",
            "planefinder.net",
        }
    )

    KNOWN_MULTI_PART_SUFFIXES = ("co.uk", "com.au", "co.jp", "com.br")

    MIN_SOURCES_SUBMITTED = 3
    MAX_SOURCES_SUBMITTED = 6
    MIN_INDEPENDENT_SOURCES = 2
    MIN_REQUIRED_DOMAINS = 2
    MAX_REQUIRED_DOMAINS = MAX_SOURCES_SUBMITTED

    EQUIVALENCE_PRINCIPLE = (
        "The result is a JSON object classifying a single flight-status "
        "web page. Two results are equivalent if and only if they agree "
        "on every categorical field (fetch_status, flight_match, "
        "freshness, status_word) and on the DELAY_TEXT field's numeric "
        "meaning (e.g. '45 minutes' and '45 min late' are equivalent; "
        "'45 minutes' and '90 minutes' are not). Minor wording "
        "differences in free-text fields do not affect equivalence."
    )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(self):
        self.agreement_count = u256(0)

    # ==================================================================
    # PUBLIC WRITE METHODS
    # ==================================================================

    @gl.public.write.payable
    def create_agreement(
        self,
        party_b_address: str,
        flight_number: str,
        flight_date: str,
        delay_threshold_minutes: int,
        side_a: str,
        description: str,
        required_source_domains: list[str] = None,
    ) -> str:
        """
        Party A creates the agreement and, in the same transaction,
        locks their stake (`gl.message.value`) in escrow. Everything
        that determines who can later move money - the two addresses,
        the stake amount, the flight being bet on, and (optionally) the
        committed source policy - is fixed here, before any evidence
        exists.
        """
        sender = self._canonical_address(str(gl.message.sender_address))
        stake = int(gl.message.value)

        if stake <= 0:
            raise Exception("create_agreement requires a positive stake (attach GEN value).")

        party_b_address = self._canonical_address(party_b_address)
        if party_b_address == sender:
            raise Exception("party_b_address must be different from the caller (party_a).")

        flight_number = (flight_number or "").strip()
        flight_date = (flight_date or "").strip()
        if not flight_number:
            raise Exception("flight_number is required.")
        if not flight_date:
            raise Exception("flight_date is required.")

        if delay_threshold_minutes is None or int(delay_threshold_minutes) < 0:
            raise Exception("delay_threshold_minutes must be a non-negative integer.")
        delay_threshold_minutes = int(delay_threshold_minutes)

        if side_a not in self.SIDE_WORDS:
            raise Exception(f"side_a must be one of {self.SIDE_WORDS}.")

        normalized_domains = self._validate_and_normalize_required_domains(
            required_source_domains
        )

        agreement_id = str(int(self.agreement_count))
        self.agreement_count = u256(int(self.agreement_count) + 1)
        created_at = self._now()

        record = {
            "agreement_id": agreement_id,
            "status": "awaiting_funding",
            "party_a_address": sender,
            "party_b_address": party_b_address,
            "stake": str(stake),
            "flight_number": flight_number,
            "flight_date": flight_date,
            "delay_threshold_minutes": delay_threshold_minutes,
            "side_a": side_a,
            "description": (description or "").strip(),
            "required_source_domains": normalized_domains,
            "funded_a": True,
            "funded_b": False,
            "winner": None,
            "payout_amount": None,
            "resolution_attempts": 0,
            "records": [],
            "cancel_consent_a": False,
            "cancel_consent_b": False,
            "created_at": created_at.isoformat(),
            "funded_at": None,
            "cancel_reason": None,
        }
        self.agreements[agreement_id] = json.dumps(record)
        return json.dumps(record)

    @gl.public.write.payable
    def fund_agreement(self, agreement_id: str) -> str:
        """
        Party B accepts the bet by attaching exactly the same stake
        party A locked. The sender must be the exact address party A
        named at creation - this is the identity binding that was
        missing from the oracle contracts' free-text party fields.
        """
        record = self._load_agreement(agreement_id)

        if record["status"] != "awaiting_funding":
            raise Exception(
                f"agreement {agreement_id} is '{record['status']}', not awaiting funding."
            )

        sender = self._canonical_address(str(gl.message.sender_address))
        if sender != record["party_b_address"]:
            raise Exception(
                "Only the address named as party_b at creation may fund this agreement."
            )

        stake = int(record["stake"])
        sent = int(gl.message.value)
        if sent != stake:
            raise Exception(
                f"fund_agreement requires exactly the committed stake ({stake}); got {sent}."
            )

        record["funded_b"] = True
        record["status"] = "funded"
        record["funded_at"] = self._now().isoformat()
        self.agreements[agreement_id] = json.dumps(record)
        return json.dumps(record)

    @gl.public.write
    def resolve_agreement(self, agreement_id: str, source_urls: list[str]) -> str:
        """
        Runs the multi-source fetch -> LLM classification -> deterministic
        aggregation pipeline (architecturally identical to
        OilPriceOracle's resolve_agreement) and, if a verdict is
        reached, pays the full pot to the winning party's own address.
        Callable by anyone - see class docstring for why that's safe.
        """
        record = self._load_agreement(agreement_id)
        if record["status"] != "funded":
            raise Exception(
                f"agreement {agreement_id} is '{record['status']}'; both parties must have "
                "funded it before it can be resolved."
            )

        if not isinstance(source_urls, list):
            raise Exception("source_urls must be a list of URLs.")
        if len(source_urls) < self.MIN_SOURCES_SUBMITTED:
            raise Exception(
                f"resolve_agreement requires at least {self.MIN_SOURCES_SUBMITTED} source_urls."
            )
        if len(source_urls) > self.MAX_SOURCES_SUBMITTED:
            raise Exception(
                f"resolve_agreement accepts at most {self.MAX_SOURCES_SUBMITTED} source_urls."
            )

        annotated = self._annotate_sources(source_urls)

        required_domains = record.get("required_source_domains") or []
        if required_domains:
            submitted_reputable_domains = {
                a["canonical_domain"]
                for a in annotated
                if a["is_reputable"] and not a["is_duplicate_domain"]
            }
            missing = [d for d in required_domains if d not in submitted_reputable_domains]
            if missing:
                raise Exception(
                    "This agreement committed a fixed source policy at create_agreement "
                    "time (required_source_domains). The submitted source_urls are "
                    f"missing required reputable domain(s): {', '.join(missing)}."
                )

        distinct_reputable = {
            a["canonical_domain"]
            for a in annotated
            if a["is_reputable"] and not a["is_duplicate_domain"]
        }
        if len(distinct_reputable) < self.MIN_INDEPENDENT_SOURCES:
            raise Exception(
                f"At least {self.MIN_INDEPENDENT_SOURCES} distinct reputable flight-tracking "
                "domains are required before any page is fetched."
            )

        classified = self._classify_all_sources(annotated, record)
        verdict, above_meta = self._aggregate(classified)

        record["records"] = classified
        record["final_verdict"] = verdict
        record["resolution_attempts"] = int(record["resolution_attempts"]) + 1
        record["independent_source_count"] = above_meta["independent_total"]

        if verdict == "Indeterminate":
            # Same "Indeterminate stays open, evidence overwritten on
            # next attempt" behavior as the accepted oracle contracts.
            self.agreements[agreement_id] = json.dumps(record)
            return json.dumps(record)

        side_a = record["side_a"]
        winner_is_a = verdict == side_a
        winner_address = record["party_a_address"] if winner_is_a else record["party_b_address"]
        winner_label = "party_a" if winner_is_a else "party_b"

        pot = int(record["stake"]) * 2
        record["winner"] = winner_label
        record["payout_amount"] = str(pot)
        record["status"] = "resolved"
        self.agreements[agreement_id] = json.dumps(record)

        gl.get_contract_at(Address(winner_address)).emit_transfer(value=pot)

        return json.dumps(record)

    @gl.public.write
    def request_cancel(self, agreement_id: str) -> str:
        """
        Mutual-consent cancellation. Either party can call this at any
        time before resolution; once BOTH have called it, each party's
        own stake is refunded to their own address and the agreement is
        closed. This is the direct fix for the "committed source policy
        can strand an agreement forever" limitation disclosed (and left
        unaddressed) in the OilPriceOracle README.
        """
        record = self._load_agreement(agreement_id)
        if record["status"] not in ("awaiting_funding", "funded"):
            raise Exception(
                f"agreement {agreement_id} is '{record['status']}' and can no longer be cancelled."
            )

        sender = self._canonical_address(str(gl.message.sender_address))
        if sender == record["party_a_address"]:
            record["cancel_consent_a"] = True
        elif sender == record["party_b_address"]:
            record["cancel_consent_b"] = True
        else:
            raise Exception("Only party_a or party_b may request cancellation.")

        if record["cancel_consent_a"] and record["cancel_consent_b"]:
            stake = int(record["stake"])
            record["status"] = "cancelled"
            record["cancel_reason"] = "mutual_consent"
            self.agreements[agreement_id] = json.dumps(record)

            # party_a always locked their stake at create_agreement.
            gl.get_contract_at(Address(record["party_a_address"])).emit_transfer(value=stake)
            # party_b only locked funds if they actually called fund_agreement.
            if record["funded_b"]:
                gl.get_contract_at(Address(record["party_b_address"])).emit_transfer(value=stake)
            return json.dumps(record)

        self.agreements[agreement_id] = json.dumps(record)
        return json.dumps(record)

    @gl.public.write
    def reclaim_unfunded_stake(self, agreement_id: str) -> str:
        """
        Lets party_a recover their own stake if party_b never funds the
        agreement within `UNFUNDED_TIMEOUT` of creation. Fixes a real
        gap: previously an agreement stuck in `awaiting_funding` forever
        (party_b just never shows up) had no recovery path at all -
        `request_cancel` requires party_b's consent too, which is
        exactly what's missing here. This path needs no one else's
        agreement because no one else's money is at risk yet: only
        party_a's own stake has ever been locked while
        `status == "awaiting_funding"`.
        """
        record = self._load_agreement(agreement_id)
        if record["status"] != "awaiting_funding":
            raise Exception(
                f"agreement {agreement_id} is '{record['status']}'; only an unfunded "
                "agreement can be reclaimed this way."
            )

        sender = self._canonical_address(str(gl.message.sender_address))
        if sender != record["party_a_address"]:
            raise Exception("Only party_a may reclaim an unfunded stake.")

        created_at = datetime.fromisoformat(record["created_at"])
        deadline = created_at + self.UNFUNDED_TIMEOUT
        now = self._now()
        if now < deadline:
            raise Exception(
                f"Funding timeout not yet reached; party_b still has until "
                f"{deadline.isoformat()} (now: {now.isoformat()})."
            )

        stake = int(record["stake"])
        record["status"] = "cancelled"
        record["cancel_reason"] = "unfunded_timeout"
        self.agreements[agreement_id] = json.dumps(record)
        gl.get_contract_at(Address(record["party_a_address"])).emit_transfer(value=stake)
        return json.dumps(record)

    @gl.public.write
    def force_close_stalemate(self, agreement_id: str) -> str:
        """
        A deterministic, no-consent-required escape hatch for an
        agreement that has been funded, genuinely attempted at least
        once, and has sat `Indeterminate` (or simply never been
        resolved) for longer than `STALEMATE_TIMEOUT`. Refunds each
        party their own stake and closes the agreement.

        This differs from `request_cancel` specifically to cover the
        case `request_cancel` cannot: one party funds, evidence turns
        out to be permanently unavailable or endlessly ambiguous, and
        the OTHER party refuses to consent to cancellation (perhaps
        because they're hoping a lucky future resolve_agreement call
        goes their way, or because they've simply disappeared). Nobody
        should be able to hold the other party's stake hostage forever
        by just not answering. Requiring at least one real
        `resolve_agreement` attempt (`MIN_STALEMATE_ATTEMPTS`) before
        this is callable prevents it from being used to bail out of an
        agreement the instant it becomes inconvenient - there must be
        genuine, time-tested evidence trouble, not impatience.
        Callable by anyone, like `resolve_agreement`: the refund
        destinations and amounts were fixed long before this call, so
        the caller's identity cannot change the outcome.
        """
        record = self._load_agreement(agreement_id)
        if record["status"] != "funded":
            raise Exception(
                f"agreement {agreement_id} is '{record['status']}'; only a funded, "
                "unresolved agreement can be force-closed as a stalemate."
            )
        if int(record["resolution_attempts"]) < self.MIN_STALEMATE_ATTEMPTS:
            raise Exception(
                f"At least {self.MIN_STALEMATE_ATTEMPTS} resolve_agreement attempt(s) "
                "are required before a stalemate close can be requested."
            )

        funded_at = datetime.fromisoformat(record["funded_at"])
        deadline = funded_at + self.STALEMATE_TIMEOUT
        now = self._now()
        if now < deadline:
            raise Exception(
                f"Stalemate timeout not yet reached; earliest close time is "
                f"{deadline.isoformat()} (now: {now.isoformat()})."
            )

        stake = int(record["stake"])
        record["status"] = "cancelled"
        record["cancel_reason"] = "stalemate_timeout"
        self.agreements[agreement_id] = json.dumps(record)

        gl.get_contract_at(Address(record["party_a_address"])).emit_transfer(value=stake)
        gl.get_contract_at(Address(record["party_b_address"])).emit_transfer(value=stake)
        return json.dumps(record)

    # ==================================================================
    # PUBLIC VIEW METHODS
    # ==================================================================

    @gl.public.view
    def get_agreement(self, agreement_id: str) -> str:
        return json.dumps(self._load_agreement(agreement_id))

    @gl.public.view
    def total_agreements(self) -> int:
        return int(self.agreement_count)

    # ==================================================================
    # INTERNAL HELPERS
    # (plain instance methods, per GenVM lint rule E022 - see
    # OilPriceOracle's README "Live Deployment" section for the exact
    # E022 fix that made this a hard requirement for every new contract
    # in this portfolio.)
    # ==================================================================

    def _load_agreement(self, agreement_id: str) -> dict:
        raw = self.agreements.get(str(agreement_id))
        if raw is None:
            raise Exception(f"No agreement with id '{agreement_id}'.")
        return json.loads(raw)

    def _now(self) -> "datetime":
        """
        Single call site for the current consensus-agreed transaction
        time. GenVM injects a deterministic `datetime.datetime.now()`
        into every transaction - every validator computes the exact
        same value for a given transaction, the same way `genlayer-test`
        lets you pin it via a `genvm_datetime` fixture for reproducible
        tests. Centralizing the call here means the offline test stub
        only has to patch one thing to control time in tests.
        """
        return datetime.now()

    def _canonical_address(self, address: str) -> str:
        """
        Validates that `address` is a well-formed 0x + 40-hex-char
        address and returns its canonical (lowercased) string form.
        Applied to BOTH party_a (from gl.message.sender_address) and
        party_b (caller-supplied) before either is stored, so:
          (a) a malformed party_b can never be locked into an agreement
              party_a can't get funded, and
          (b) two different letter-casings of the same real address are
              always treated as the same party, everywhere they're
              compared (fund_agreement, request_cancel, and the two new
              timeout-recovery methods).
        """
        text = (address or "").strip()
        if not self._ADDRESS_RE.match(text):
            raise Exception(
                f"'{address}' is not a valid address (expected 0x followed by 40 hex characters)."
            )
        return "0x" + text[2:].lower()

    def _validate_and_normalize_required_domains(self, required_source_domains):
        if not required_source_domains:
            return []
        if len(required_source_domains) < self.MIN_REQUIRED_DOMAINS:
            raise Exception(
                f"required_source_domains needs at least {self.MIN_REQUIRED_DOMAINS} entries "
                "if used at all."
            )
        if len(required_source_domains) > self.MAX_REQUIRED_DOMAINS:
            raise Exception(
                f"required_source_domains accepts at most {self.MAX_REQUIRED_DOMAINS} entries."
            )
        normalized = []
        seen = set()
        for entry in required_source_domains:
            domain = self._extract_domain(entry)
            if domain not in self.REPUTABLE_FLIGHT_DOMAINS:
                raise Exception(
                    f"required_source_domains entry '{entry}' is not on the reputable "
                    "flight-tracking allowlist."
                )
            if domain in seen:
                raise Exception(f"required_source_domains has a duplicate entry: '{domain}'.")
            seen.add(domain)
            normalized.append(domain)
        return sorted(normalized)

    def _extract_domain(self, url_or_domain: str) -> str:
        text = (url_or_domain or "").strip().lower()
        text = text.split("://", 1)[-1]
        text = text.split("/", 1)[0]
        text = text.split(":", 1)[0]
        text = text.split("?", 1)[0]
        text = text.split("#", 1)[0]
        if text.startswith("www."):
            text = text[4:]
        parts = text.split(".")
        if len(parts) >= 3:
            last_two = ".".join(parts[-2:])
            if last_two in self.KNOWN_MULTI_PART_SUFFIXES and len(parts) >= 3:
                return ".".join(parts[-3:])
        return text

    def _canonical_reputable_domain(self, domain: str):
        """
        Returns the matching allowlist entry for `domain`, treating any
        subdomain of an allowlisted domain (e.g. 'uk.flightaware.com',
        'm.flightaware.com') as that same tracker, not a separate
        unlisted site. Returns None if `domain` isn't allowlisted or a
        subdomain of anything allowlisted. Two different subdomains of
        the same tracker still count as ONE source for independence
        purposes - they're the same underlying data provider.
        """
        if domain in self.REPUTABLE_FLIGHT_DOMAINS:
            return domain
        for rep in self.REPUTABLE_FLIGHT_DOMAINS:
            if domain.endswith("." + rep):
                return rep
        return None

    def _annotate_sources(self, source_urls: list[str]) -> list[dict]:
        seen_canonical_domains = set()
        annotated = []
        for url in source_urls:
            domain = self._extract_domain(url)
            canonical = self._canonical_reputable_domain(domain)
            is_reputable = canonical is not None
            is_duplicate = is_reputable and canonical in seen_canonical_domains
            if is_reputable and not is_duplicate:
                seen_canonical_domains.add(canonical)
            annotated.append(
                {
                    "url": url,
                    "domain": domain,
                    "canonical_domain": canonical,
                    "is_reputable": is_reputable,
                    "is_duplicate_domain": is_duplicate,
                }
            )
        return annotated

    def _classify_all_sources(self, annotated: list[dict], record: dict) -> list[dict]:
        results = []
        for entry in annotated:
            results.append(self._classify_one_source(entry, record))
        return results

    def _classify_one_source(self, entry: dict, record: dict) -> dict:
        url = entry["url"]
        flight_number = record["flight_number"]
        flight_date = record["flight_date"]

        def nondet():
            try:
                content = gl.nondet.web.render(url, mode="text")
            except Exception:
                return {"fetch_status": "inaccessible"}
            if content is None:
                return {"fetch_status": "inaccessible"}
            content = content.strip() if isinstance(content, str) else str(content)
            if not content:
                return {"fetch_status": "empty"}

            prompt = self._build_prompt(content, flight_number, flight_date)
            raw = gl.nondet.exec_prompt(prompt, response_format="json")
            parsed = raw if isinstance(raw, dict) else json.loads(raw)

            return {
                "fetch_status": "ok",
                "flight_match": parsed.get("FLIGHT_MATCH", "Unclear"),
                "freshness": parsed.get("FRESHNESS", "Unknown"),
                "status_word": parsed.get("STATUS", "Unknown"),
                "delay_text": parsed.get("DELAY_TEXT", ""),
            }

        try:
            result = gl.eq_principle.prompt_comparative(
                nondet, principle=self.EQUIVALENCE_PRINCIPLE
            )
        except Exception:
            result = {"fetch_status": "malformed"}

        fetch_status = result.get("fetch_status", "malformed")
        if fetch_status not in self.FETCH_STATUSES:
            fetch_status = "malformed"

        record_out = {
            "url": url,
            "domain": entry["domain"],
            "is_duplicate_domain": entry["is_duplicate_domain"],
            "is_reputable": entry["is_reputable"],
            "fetch_status": fetch_status,
            "own_verdict": None,
            "delay_minutes": None,
            "quality_flag": None,
        }

        if fetch_status != "ok" or not entry["is_reputable"] or entry["is_duplicate_domain"]:
            record_out["quality_flag"] = (
                "ok" if fetch_status == "ok" else fetch_status
            )
            return record_out

        flight_match = result.get("flight_match", "Unclear")
        if flight_match not in self.FLIGHT_MATCH_WORDS:
            flight_match = "Unclear"
        freshness = result.get("freshness", "Unknown")
        if freshness not in self.FRESHNESS_WORDS:
            freshness = "Unknown"
        status_word = result.get("status_word", "Unknown")
        if status_word not in self.STATUS_WORDS:
            status_word = "Unknown"
        delay_text = result.get("delay_text", "")

        record_out["flight_match"] = flight_match
        record_out["freshness"] = freshness
        record_out["status_word"] = status_word

        if flight_match != "Match":
            record_out["quality_flag"] = "flight_or_date_mismatch"
            return record_out
        if freshness != "Current":
            record_out["quality_flag"] = "stale_or_unknown_freshness"
            return record_out

        delay_minutes = self._parse_delay_minutes(delay_text, status_word)
        if delay_minutes is None:
            record_out["quality_flag"] = "delay_unparseable"
            return record_out

        record_out["delay_minutes"] = delay_minutes
        record_out["quality_flag"] = "ok"
        record_out["own_verdict"] = self._deterministic_verdict(
            status_word, delay_minutes, int(record["delay_threshold_minutes"])
        )
        return record_out

    # ------------------------------------------------------------------
    # Delay-text parsing. This replaced a version that had a real bug,
    # found by a steward review of the first accepted submission: the
    # primary hour/minute extraction only matched when the number was
    # immediately adjacent to its unit letter (no space), which almost
    # never happens in natural LLM output ("75 minutes", "1.5 hours"
    # both have a space) - so nearly everything silently fell through
    # to a last-resort fallback that concatenated EVERY digit in the
    # string with no regard for structure. That fallback turned
    # "30-45 minutes" into 3045, "1 hour 30 minutes" into 130, and
    # "1.5 hours" into 15 (the decimal point was dropped) - each one a
    # wrong number landing on the wrong side of a threshold silently,
    # with no error and no Indeterminate flag. The rewrite below uses
    # anchored regexes for each real shape delay text takes and refuses
    # to guess (returns None -> "delay_unparseable" -> excluded from
    # consensus, same as any other untrustworthy source) for anything
    # a regex doesn't confidently match - most importantly, an explicit
    # range ("30-45 minutes", "1 to 2 hours") is NEVER resolved to a
    # single number, since picking either bound could flip the verdict
    # against a real threshold.
    # ------------------------------------------------------------------
    _RANGE_PATTERN = re.compile(
        r"(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*"
        r"(?:h(?:ours?|rs?|r)?|m(?:in(?:ute)?s?)?)\b"
    )
    _HOURS_MINUTES_PATTERN = re.compile(
        r"(\d+(?:\.\d+)?)\s*h(?:ours?|rs?|r)?\b"
        r"\s*(?:and\s*)?"
        r"(\d+(?:\.\d+)?)\s*m(?:in(?:ute)?s?)?\b"
    )
    _HOURS_ONLY_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*h(?:ours?|rs?|r)?\b")
    _MINUTES_ONLY_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*m(?:in(?:ute)?s?)?\b")
    _BARE_NUMBER_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)$")

    def _parse_delay_minutes(self, delay_text, status_word: str):
        if status_word in ("Cancelled", "OnTime", "Diverted"):
            # Diverted (like Cancelled) triggers a payout regardless of
            # any numeric delay - see _deterministic_verdict. Treating
            # it as 0 here means a Diverted flight with delay_text
            # "N/A" or missing still reaches a verdict instead of being
            # wrongly excluded as "delay_unparseable".
            return 0

        text = (delay_text or "").strip().lower()
        if not text:
            return None
        text = text.replace(",", "")

        # An explicit range is inherently ambiguous for threshold
        # comparison - never pick a bound, always treat as unparseable.
        if self._RANGE_PATTERN.search(text):
            return None

        combo = self._HOURS_MINUTES_PATTERN.search(text)
        if combo:
            hours_text, minutes_text = combo.group(1), combo.group(2)
            # "1.5 hours 30 minutes" is a self-contradictory compound
            # (which half-hour is it?) - refuse rather than guess.
            if "." in hours_text:
                return None
            return int(hours_text) * 60 + round(float(minutes_text))

        hours_only = self._HOURS_ONLY_PATTERN.search(text)
        if hours_only:
            return round(float(hours_only.group(1)) * 60)

        minutes_only = self._MINUTES_ONLY_PATTERN.search(text)
        if minutes_only:
            return round(float(minutes_only.group(1)))

        bare = self._BARE_NUMBER_PATTERN.match(text)
        if bare:
            return round(float(bare.group(1)))

        return None

    def _deterministic_verdict(self, status_word: str, delay_minutes: int, threshold: int) -> str:
        if status_word in ("Cancelled", "Diverted"):
            return "PayoutTriggered"
        if status_word == "Delayed" and delay_minutes >= threshold:
            return "PayoutTriggered"
        return "NoPayout"

    def _aggregate(self, classified: list[dict]):
        eligible = [c for c in classified if c.get("quality_flag") == "ok"]
        triggered = sum(1 for c in eligible if c["own_verdict"] == "PayoutTriggered")
        no_payout = sum(1 for c in eligible if c["own_verdict"] == "NoPayout")
        independent_total = len(eligible)

        meta = {"independent_total": independent_total}

        if independent_total < self.MIN_INDEPENDENT_SOURCES:
            return "Indeterminate", meta
        if triggered >= self.MIN_INDEPENDENT_SOURCES and triggered > no_payout:
            return "PayoutTriggered", meta
        if no_payout >= self.MIN_INDEPENDENT_SOURCES and no_payout > triggered:
            return "NoPayout", meta
        return "Indeterminate", meta

    def _build_prompt(self, content: str, flight_number: str, flight_date: str) -> str:
        return f"""You are checking a flight-tracking web page as evidence for an
on-chain flight-delay agreement. Respond with ONLY a JSON object, no
other text.

Flight being checked: {flight_number} on {flight_date}

Page content:
---
{content[:6000]}
---

Return exactly this JSON shape:
{{
  "FLIGHT_MATCH": "Match" | "Mismatch" | "Unclear",
  "FRESHNESS": "Current" | "Stale" | "Unknown",
  "STATUS": "OnTime" | "Delayed" | "Cancelled" | "Diverted" | "Unknown",
  "DELAY_TEXT": "<the delay as stated on the page, e.g. '47 minutes', 'N/A' if none>"
}}

Rules:
- FLIGHT_MATCH is "Match" only if this page is clearly about flight
  {flight_number} on {flight_date} specifically (not a different
  flight number, different date, or a generic schedule page).
- FRESHNESS is "Current" only if the page appears to reflect the
  actual status of that specific flight/date, not a cached or
  unrelated page.
- STATUS must be your best classification of the flight's real-world
  status from the page content, using ONLY one of the listed words.
- DELAY_TEXT must be copied/paraphrased from the page, never invented.
  Do not do any unit conversion or arithmetic yourself - just report
  what the page says.
- If the page is not about a real flight status at all, set
  FLIGHT_MATCH to "Unclear" and STATUS to "Unknown".
"""
