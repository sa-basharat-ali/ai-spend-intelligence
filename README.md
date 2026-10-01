# AI spend intelligence from a raw card feed

```
python3 run.py      # stdlib only, no install, under a second
```

1,900 transactions, 600 employees, 6 months, 231 distinct descriptors, 15 vendors.
Generated feed, deterministic seed, no real company's data.

---

## What it does

Three questions a finance team cannot currently answer from a card feed, and the reason
each one is hard.

### 1. Which vendor is this actually

Card network descriptors arrive truncated to 22 or 25 characters, carrying phone numbers,
city and country codes, per-transaction reference hashes, and an entity name that might
be the legal entity, the product, the reseller, or an acronym nobody outside the vendor
recognises.

```
ANTHROPIC*CLAUDE.AI HTTPSWWW.ANTH CA  ->  ANTHROPIC     (cluster)
ANTHROPIC*8TZQSP API CREDIT           ->  ANTHROPIC     (cluster)
ANTHROPIC PBC       SAN FRANCISC      ->  ANTHROPIC     (cluster)
OPENAI *CHATGPT SUBSCR SAN FRANCIS    ->  OpenAI        (registry)
ANYSPHERE INC (CURSOR) SAN FRANCIS    ->  ANYSPHERE CURSOR  (cluster)
```

231 descriptors to 15 vendors, 100% pure, one-to-one against ground truth.

Two stages: a registry match, then trigram clustering for whatever did not match. **The
registry deliberately omits Anthropic, Cursor, Perplexity, Replit and ElevenLabs.** They
are recovered by clustering alone, which is the design point rather than a demo trick. A
registry is a snapshot and the AI vendor list is not. Half the line items a finance team
is trying to understand this quarter are from companies that did not have a product last
year, and a system that needs a human to add a row before it can see a vendor is always
reporting on last quarter while being asked about this one.

### 2. Which vendors can existing controls actually govern

Seat, usage or hybrid, classified from the time series alone. No vendor list, no lookup,
no manual tagging. Three features: charge days per month, coefficient of variation of the
daily total, and the share of charges with a distinct amount. 14 of 15 correct.

Seat pricing lands on a small set of values because it is a rate card times a headcount.
Usage pricing lands on a continuum because it is a meter.

This matters because every spend control ever shipped assumes the seat shape. Limits,
approvals and budgets all key off a predictable recurring amount. Pointed at a metered
vendor they do not fail loudly. They quietly stop being controls.

### 3. When can you call month-end

| as of day | run-rate error | empirical error | 80% coverage | interval half-width |
|---|---|---|---|---|
| 3 | 54.5% | 57.5% | 80% | ±139% |
| 5 | 40.5% | 41.4% | 79% | ±100% |
| 8 | 25.6% | 28.6% | 76% | ±72% |
| 12 | 17.2% | 16.9% | 71% | ±34% |
| 20 | 10.7% | 11.5% | 81% | ±23% |
| 25 | 6.5% | 7.3% | 76% | ±18% |

**Nothing beats plain run-rate as a point estimate.** I tried weekday pacing plus a growth
trend, which was worse at three of five cutoffs, then an empirical ratio model, which
ties. That negative result is the useful part, and it says what to build instead.

Early-month error on a metered vendor is not a calendar effect. It is lumpiness: a few
large charges dominate the month, and whether two of them have landed by day 5 is close
to a coin flip. A cleverer point estimate cannot fix variance.

So the deliverable is a calibrated interval instead. Coverage runs 71% to 81% against a
nominal 80%, so the intervals mean what they say, and they answer the question finance
actually has: **metered spend is not callable before roughly day 12.** Any dashboard
showing a run-rate projection on day 5 is displaying a point estimate that is really a
±100% range, and that gap is the entire mechanism by which this category becomes an
invisible cost.

## What falls out

$549,270 a year across six AI vendors that did not exist as a budget line eighteen months
ago. Four of them are paid by five or more separate cardholders, so there is no
subscription to renegotiate and nobody owns the number.

| vendor | this month | MoM | in 6 months | added |
|---|---|---|---|---|
| Anthropic | $17,258 | 28% | $75,464 | $58,206 |
| OpenAI | $20,347 | 16% | $49,207 | $28,860 |
| ElevenLabs | $1,324 | 33% | $7,311 | $5,988 |

$100,747 a month of new spend within two quarters if the current rates hold. They will
not hold, which is the point: nobody knows whether they halve or double, and nothing in
the feed flags either, because every individual charge is small and unremarkable.

## What I got wrong, both in the run output

**The pacing forecast.** Weekday weighting plus a growth multiplier was the obvious
improvement and it lost to a straight line. Worth keeping in the write-up because the
reason it lost is what determined the right design.

**The hybrid vendor.** Replit is a seat floor with usage on top and gets classified as
pure usage, because the usage half dominates its signature. Three features cannot see a
floor underneath a meter. Separating the recurring component would need charge-level
structure, which is a bigger model than this deserves.

## Files

| | |
|---|---|
| `transactions.py` | the card feed and the descriptor mangling |
| `normalize.py` | descriptor cleaning, registry match, trigram clustering |
| `analyze.py` | shape classification, interval forecasting, control-gap ranking |
| `run.py` | the report |

## Where this comes from

At Geidea, Saudi Arabia's largest payments processor, I built merchant intelligence segmentation
across 40,000+ merchants and 400,000+ POS terminals against a million transactions a day,
plus churn models and real-time anomaly detection. Merchant descriptor resolution at that
scale is the same problem in the other direction: a messy string, a real entity behind
it, and every downstream number wrong if you get it wrong.

Syed Ahmed Basharat Ali. sabasharat.ali@gmail.com | basharat.net
