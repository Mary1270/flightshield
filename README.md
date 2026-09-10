# FlightShield

A two-party, multi-source-verified **flight delay / cancellation
settlement contract with real on-chain GEN escrow**, built for the
GenLayer Builder program.

This is a new Intelligent Contract - not an update to an existing
submission - but it deliberately reuses the multi-source corroboration
architecture already proven (offline-tested and live-tested on GenLayer
Studio) by the OilPriceOracle / GoldPriceOracle contracts, and exists
specifically to close three gaps those contracts *disclosed but left
open*. See the full rationale in `contract.py`'s class docstring.

## The three gaps this closes

| Gap disclosed in OilPriceOracle's README | How FlightShield closes it |
|---|---|
| "Actually moving funds based on the winner is intentionally NOT implemented" | `create_agreement` / `fund_agreement` are `@gl.public.write.payable` and lock real GEN; `resolve_agreement` pays the winner automatically via `emit_transfer` |
| `party_a` / `party_b` are free-text strings, not bound to a caller identity | `party_a` / `party_b` **are** `gl.message.sender_address` values, checked on every fund-moving call |
| A committed source policy can strand an agreement forever, with no on-chain recovery | `request_cancel`: mutual-consent cancellation refunds both parties their own stake, no oracle result required |

## v2: steward feedback addressed

A steward review of the v1 submission requested four concrete fixes.
All four are implemented, tested, and documented in `contract.py`'s
class docstring (see "STEWARD FEEDBACK ADDRESSED"):

| Steward request | Fix |
|---|---|
| Validate party_b as an Address and store one canonical address form | `_canonical_address()` enforces a strict `0x` + 40-hex-char shape and lowercases the result for **both** party_a and party_b before storage or comparison |
| Let party_a recover an unfunded stake after a clear timeout | `reclaim_unfunded_stake()` - party_a only, after `UNFUNDED_TIMEOUT` (48h) of no funding |
| A deterministic terminal refund path after prolonged indeterminate/unavailable evidence, without both parties' consent | `force_close_stalemate()` - callable by anyone, after `STALEMATE_TIMEOUT` (14 days) past funding **and** at least one real resolve attempt |
| Parse decimal, compound, or ranged delay text without threshold-changing ambiguity | `_parse_delay_minutes()` rewritten around anchored regexes; explicit ranges are never resolved to a single number |

**Important correction from v1:** the v1 README claimed GenVM has no
on-chain clock and built every time-sensitive check on LLM content
classification alone. That claim was wrong. GenVM injects a
deterministic, consensus-agreed `datetime.datetime.now()` into every
transaction (confirmed by `genlayer-test`'s `genvm_datetime` fixture,
built specifically to pin that value for reproducible testing) - every
validator computes the exact same value for a given transaction, so
ordinary Python `datetime` arithmetic is safe in deterministic contract
code. The two new timeout methods use the real clock; the existing
`FRESHNESS` check still uses LLM content classification, since it's
answering a different question (does this *evidence* reflect the
current situation, not how much wall-clock time has passed).

## v3: range-detection gap closed

The v2 fix for delay-text ranges only caught the shape where a unit
appears right after the *second* number ("30-45 minutes"). A steward
found that phrasings like **"between 30 and 45 minutes"** (connector
"and", unit only after the second number) and **"30 minutes to 1
hour"** (each number carries its own unit) slipped past that check
entirely and were silently resolved to one bound by the hours/minutes
patterns - the same threshold-flipping risk v2 was meant to eliminate,
just via a different phrasing.

`_RANGE_CONNECTOR_PATTERN` now matches ANY two numbers joined by a
dash/en-dash/em-dash/"to"/"and", with units optional on either side,
and treats it as unparseable - *unless* it's specifically the
legitimate "N hour(s) and M minute(s)" compound-duration shape
(connector "and", first unit category hour, second category minute),
which is a single duration, not a range, and still parses correctly
(e.g. "1 hour and 30 minutes" -> 90).

While fixing this, the same latent bug was found and fixed
**proactively** in WeatherVault's `_parse_metric_value` (it silently
returned the first bound of "30-45mm" instead of flagging it as
ambiguous) - see that project's own README for details.

## How it works

1. **`create_agreement`** (payable) - Party A locks their stake, names
   Party B's address, commits the flight number/date, the delay
   threshold, which side they're betting on (`PayoutTriggered` /
   `NoPayout`), and optionally a fixed `required_source_domains`
   policy (same "commit the policy before anyone knows the outcome"
   pattern as OilPriceOracle v3's endpoint commitment).
2. **`fund_agreement`** (payable) - Only the named Party B address can
   call this, and only with the exact matching stake. Symmetric bet,
   identity-bound on both sides.
3. **`resolve_agreement`** - Anyone can trigger this (see "Why resolve
   stays open-caller" in the contract docstring for why that's safe).
   It fetches 3-6 candidate flight-tracking pages, keeps only
   independent (`is_reputable`, non-duplicate-domain) sources, has each
   one classified by an LLM under `gl.eq_principle.prompt_comparative`
   into a small fixed vocabulary (`FLIGHT_MATCH`, `FRESHNESS`,
   `STATUS`, `DELAY_TEXT`), deterministically parses `DELAY_TEXT` in
   Python (never trusts the LLM's own arithmetic), and requires
   **2+ independent reputable sources to agree** before reaching
   `PayoutTriggered` or `NoPayout`. On a real verdict, the full pot
   (`2 x stake`) is transferred to the winning party's own address in
   the same transaction.
4. **`request_cancel`** - Either party can call this before
   resolution; once both have, each gets their own stake back.
5. **`reclaim_unfunded_stake`** - If party_b never funds, party_a
   recovers their own stake alone once `UNFUNDED_TIMEOUT` (48h) has
   passed since `create_agreement` - no one else's money is at risk at
   that stage, so no one else's consent is needed.
6. **`force_close_stalemate`** - If the agreement is funded but stuck
   (evidence is permanently unavailable or endlessly `Indeterminate`)
   for longer than `STALEMATE_TIMEOUT` (14 days) past funding, and at
   least one real `resolve_agreement` attempt has been made, anyone can
   trigger a refund of each party's own stake. This covers the case
   `request_cancel` can't: one party wants out but the other won't
   consent.

## Reputable source allowlist

A small, static, hand-maintained set (same determinism trade-off
documented for OilPriceOracle's price-domain allowlist - a live
reputation feed would be nicer but is nondeterministic across
validators unless itself run through consensus):

```
flightaware.com
flightstats.com
flightradar24.com
flightview.com
planefinder.net
```

## Core GenLayer building blocks used

1. `gl.nondet.web.render()` - trustless web access per source
2. `gl.nondet.exec_prompt()` - LLM classification inside the contract
3. `gl.eq_principle.prompt_comparative()` - Optimistic Democracy
   consensus on LLM-derived output (never `strict_eq` for LLM output)
4. `@gl.public.write.payable` + `gl.message.value` - real GEN escrow
5. `gl.message.sender_address` - identity binding on fund-moving calls
6. `gl.ContractAt(Address(...)).emit_transfer(value=...)` - paying out
   the winner's own wallet address automatically

## Testing

116 offline unit tests across two files, run with plain `unittest`
(no network access needed, no live GenLayer node needed):

```bash
cd tests
python3 -m unittest test_aggregation test_end_to_end -v
```

- `test_aggregation.py` - pure deterministic logic: domain extraction,
  delay-text parsing (`"1h 20m"`, `"47 min late"`, cancelled/on-time
  overrides), the deterministic per-source verdict rule, required-domain
  policy validation, and the 2-of-N aggregation rule.
- `test_end_to_end.py` - full contract flow through the offline SDK
  stub (`tests/genlayer_stub/`), including:
  - stake validation on `create_agreement` (positive stake required,
    party_b != sender, required flight fields, valid side/threshold)
  - identity + amount enforcement on `fund_agreement` (wrong sender
    rejected, wrong amount rejected either direction, double-funding
    rejected)
  - committed source-policy enforcement on `resolve_agreement`
  - all four resolution outcomes (party_a wins / party_b wins /
    stays open on Indeterminate / repeated-attempt evidence overwrite)
    with exact payout-amount and payout-address assertions on the
    recorded `emit_transfer` calls
  - a dedicated test proving the caller of `resolve_agreement` cannot
    redirect the payout, since the destination address was fixed
    before any evidence existed
  - mutual-consent cancellation (single consent doesn't cancel, both
    consents refunds correctly depending on whether B had funded yet,
    non-parties can't request it, can't cancel after resolution)

The offline stub (`tests/genlayer_stub/genlayer/__init__.py`) extends
the pattern from prior contracts in this portfolio with a
`tx_context(sender, value)` test helper that simulates a specific
caller sending a specific amount of GEN, plus a transfer recorder so
tests can assert exactly who got paid, how much, and how many times.

## Live testing on GenLayer Studio

Deployed and exercised end-to-end on Studio with two real funded
addresses and a real scheduled flight (British Airways BA286,
SFO -> LHR), across several agreements:

- **`create_agreement`**: confirmed rejected with zero value, with
  `party_b == sender`, with a missing flight number, with a negative
  threshold, and with an invalid `side_a`; confirmed it locks the
  caller's exact attached stake and returns `status: "awaiting_funding"`.
- **`fund_agreement`**: confirmed rejected when called from any address
  other than the declared `party_b`, and when the attached value didn't
  exactly match the committed stake; confirmed it flips the agreement to
  `status: "funded"` once both hold.
- **`request_cancel`**: confirmed a single party's consent alone does
  NOT cancel; confirmed that once both parties call it, the agreement
  moves to `status: "cancelled"` and each party's own stake is
  refunded to their own address via `emit_transfer`, both when only
  Party A had funded and when both had.
- **`resolve_agreement`**: confirmed the `Indeterminate` safety path -
  when fewer than 2 independent reputable sources return usable
  evidence (stale page, wrong flight matched, fetch failure), the
  agreement stays `funded` and no funds move, `resolution_attempts`
  increments, and old evidence is overwritten on the next attempt.
  A real bug was found and fixed during this testing (see below).
- One real design constraint was confirmed empirically: flight-tracking
  sites only populate live status once a flight actually departs, and
  swap over to the *next* scheduled flight once the current one is no
  longer "live" - a real, narrow window rather than a bug. See
  "Known limitations" below.

### Bug found and fixed during live testing: regional subdomains

flightaware.com serves regional subdomains (`uk.flightaware.com`,
`m.flightaware.com`, etc.) that render fine but were being rejected
under naive exact-domain matching against `REPUTABLE_FLIGHT_DOMAINS`.
`_canonical_reputable_domain()` now treats any subdomain of an
allowlisted domain as that same tracker (verified with a dedicated
test in `test_aggregation.py`), while still deduplicating two
subdomains of the same tracker down to one independent source.

## Known limitations

- **Peer-to-peer only, no pooled underwriting.** This is deliberately
  a bet between two named wallets, not a marketplace with a shared
  liquidity pool, partial fills, or premium pricing. A pooled version
  would need its own solvency/collateralization model - out of scope
  for a first version. (Addressed in a separate contract, WeatherVault,
  which is exactly that pooled version applied to a different domain.)
- **~~No trusted on-chain clock~~ - corrected in v2.** v1 claimed GenVM
  has no validator-agreed timestamp and built every time check on LLM
  content classification alone. That was wrong: GenVM injects a
  deterministic `datetime.datetime.now()` into every transaction (see
  "v2: steward feedback addressed" above), and `reclaim_unfunded_stake`
  / `force_close_stalemate` now use it for real elapsed-time timeouts.
  The `FRESHNESS` LLM classification is kept for what it's actually
  suited to: judging whether a fetched page's *content* reflects the
  current situation, not how much wall-clock time has passed.
  **Confirmed empirically during live testing**: for a given flight
  number, tracking sites only populate live status *after departure*
  ("FlightAware couldn't find flight tracking data ... just yet" was
  the actual response pre-departure), and swap to the *next* day's
  scheduled instance of that flight number once the current one is no
  longer the "live" one - so there is a real, narrow window (roughly:
  after departure, before the site rolls over to tomorrow's flight)
  in which `resolve_agreement` can reach a real verdict for a given
  `flight_date` rather than `Indeterminate`. This is an accurate
  reflection of the underlying data source, not a workaround - the
  contract correctly refuses to guess outside that window.
- **Static allowlist.** Same trade-off as the accepted oracle
  contracts - a hand-maintained list of 5 domains, not a live
  reputation system.
- **No partial/split payouts.** The full pot goes to one side; there
  is no proportional payout for, e.g., a delay just over threshold
  vs. a multi-hour delay.
