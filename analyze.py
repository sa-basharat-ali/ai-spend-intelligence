"""Spend shape, month-end forecasting, and where the control gap is.

The premise: a card feed already knows which vendors are billed in a way that existing
spend controls cannot govern. Nobody asks it, because the feed is usually aggregated to
monthly totals per category before anyone looks, and that aggregation is exactly the
step that destroys the signal.
"""
import statistics as st
from collections import defaultdict
from datetime import date

DAYS_IN = {}


def _month(d):
    return d[:7]


# ------------------------------------------------------- shape classification
def classify(rows):
    """Seat, usage or hybrid, from the time series alone. No vendor list, no lookup.

    Three features, and the third is the one that carries it:

      charge_days   days per month the vendor charges at all. Seats bill once
      cv            coefficient of variation of the daily total
      distinct      share of charges with a distinct amount. Seat pricing lands on a
                    small set of values because it is a rate card times a headcount.
                    Usage pricing lands on a continuum because it is a meter

    Why it matters: every spend control ever shipped assumes the seat shape. Limits,
    approvals and budgets all key off a predictable recurring amount. Pointed at a
    metered vendor they do not fail loudly, they just stop being controls."""
    by_v = defaultdict(list)
    for r in rows:
        by_v[r["vendor"]].append(r)

    out = {}
    for v, rs in by_v.items():
        months = defaultdict(list)
        for r in rs:
            months[_month(r["date"])].append(r)
        charge_days = st.mean(len({x["date"] for x in m}) for m in months.values())
        monthly = [sum(x["amount_usd"] for x in m) for m in months.values()]
        daily = defaultdict(float)
        for r in rs:
            daily[r["date"]] += r["amount_usd"]
        vals = list(daily.values())
        cv = (st.pstdev(vals) / st.mean(vals)) if len(vals) > 1 and st.mean(vals) else 0.0
        distinct = len({round(r["amount_usd"], 2) for r in rs}) / len(rs)

        if charge_days <= 3.5:
            arch = "seat"
        elif distinct > 0.75 and charge_days > 8:
            arch = "usage"
        else:
            arch = "hybrid"

        growth = None
        if len(monthly) >= 3:
            head = st.mean(monthly[:len(monthly) // 2])
            tail = st.mean(monthly[-(len(monthly) // 2):])
            n = len(monthly) - len(monthly) // 2
            if head > 0 and n > 0:
                growth = (tail / head) ** (1 / max(n, 1)) - 1

        out[v] = {"vendor": v, "archetype": arch, "charge_days": charge_days,
                  "cv": cv, "distinct_ratio": distinct, "n_txn": len(rs),
                  "total": sum(r["amount_usd"] for r in rs),
                  "monthly": monthly, "mom_growth": growth,
                  "cardholders": len({r["employee_id"] for r in rs}),
                  "teams": len({r["team"] for r in rs})}
    return out


# ----------------------------------------------------------------- forecasting
def _weekday_weights(rows):
    """Learned share of spend by weekday. Metered vendors follow the working week,
    so a flat run-rate on day 3 of a month that started on a Saturday is wrong by
    a predictable amount rather than a random one."""
    tot = defaultdict(float)
    n = defaultdict(int)
    for r in rows:
        wd = date.fromisoformat(r["date"]).weekday()
        tot[wd] += r["amount_usd"]
        n[wd] += 1
    days = {wd: tot[wd] / max(len({r["date"] for r in rows
                                   if date.fromisoformat(r["date"]).weekday() == wd}), 1)
            for wd in range(7)}
    s = sum(days.values()) or 1.0
    return {wd: days[wd] / s * 7 for wd in range(7)}


def _month_days(ym):
    y, m = int(ym[:4]), int(ym[5:])
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return (nxt - date(y, m, 1)).days


def forecast(rows, shapes, as_of_days=(3, 5, 8, 12, 20, 25)):
    """Month-end spend from partial data.

    The first version of this was a point estimate: run-rate, then run-rate corrected
    for weekday pacing and the vendor's own growth trend. The pacing correction did not
    beat plain run-rate at any cutoff, and at days 5 through 12 it was slightly worse.
    That result is in the run output because it is the useful part.

    The reason it failed says what to build instead. Early-month forecast error on a
    metered vendor is not a calendar effect, it is lumpiness: a handful of large charges
    dominate the month and whether two of them have landed by day 5 is close to a coin
    flip. Weekday weighting is a small correction against a large variance, and adding a
    growth multiplier on top just adds bias to a noisy number.

    What finance can actually act on is not a sharper point estimate. It is a calibrated
    interval, plus the day of the month it gets narrow enough to be worth acting on.

    So: learn the empirical distribution of (month total / spend so far by day D) from
    history, pooled across vendors of the same archetype because five months per vendor
    is not a distribution. Leave-one-month-out, so a month is never in its own training
    set. The interval is the 10th and 90th percentiles of that ratio."""
    by_vm = defaultdict(lambda: defaultdict(float))
    for r in rows:
        by_vm[r["vendor"]][r["date"]] += r["amount_usd"]

    # observations: (archetype, cutoff, month) -> ratio
    obs = defaultdict(list)
    cases = []
    for v, daily in by_vm.items():
        arch = shapes[v]["archetype"]
        if arch == "seat":
            continue                                   # a seat forecast is a lookup
        for ym in sorted({d[:7] for d in daily}):
            nd = _month_days(ym)
            actual = sum(a for d, a in daily.items() if d.startswith(ym))
            if actual <= 0:
                continue
            for cutoff in as_of_days:
                if cutoff >= nd:
                    continue
                so_far = sum(a for d, a in daily.items()
                             if d.startswith(ym) and int(d[8:]) <= cutoff)
                if so_far <= 0:
                    continue
                obs[(arch, cutoff)].append((ym, v, actual / so_far))
                cases.append({"vendor": v, "arch": arch, "month": ym, "cutoff": cutoff,
                              "so_far": so_far, "actual": actual, "days": nd})

    def q(xs, p):
        xs = sorted(xs)
        if not xs:
            return None
        k = (len(xs) - 1) * p
        lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
        return xs[lo] + (k - lo) * (xs[hi] - xs[lo])

    rows_out, per_case = [], []
    for cutoff in as_of_days:
        rr_err, pt_err, covered, widths, n = [], [], 0, [], 0
        for c in cases:
            if c["cutoff"] != cutoff:
                continue
            pool = [r for m, vv, r in obs[(c["arch"], cutoff)] if m != c["month"]]
            if len(pool) < 6:
                continue
            lo = c["so_far"] * q(pool, 0.10)
            hi = c["so_far"] * q(pool, 0.90)
            pt = c["so_far"] * q(pool, 0.50)
            rr = c["so_far"] * c["days"] / cutoff
            n += 1
            rr_err.append(abs(rr - c["actual"]) / c["actual"])
            pt_err.append(abs(pt - c["actual"]) / c["actual"])
            covered += lo <= c["actual"] <= hi
            widths.append((hi - lo) / 2 / max(pt, 1e-9))
            per_case.append({**c, "lo": lo, "hi": hi, "point": pt, "runrate": rr})
        if n:
            rows_out.append({"as_of_day": cutoff, "n": n,
                             "runrate_mape": st.median(rr_err),
                             "empirical_mape": st.median(pt_err),
                             "coverage_80": covered / n,
                             "half_width": st.median(widths)})
    return rows_out, per_case


# ------------------------------------------------------------- the control gap
def control_gap(shapes, rows, months):
    """Rank vendors by spend that no existing control can govern.

    Two independent problems, and a vendor with both is the one to fix first:

      metered   the amount is not knowable in advance, so a limit is either so high it
                governs nothing or so low it takes production down
      diffuse   many individual cardholders rather than one central account, so there
                is no single subscription to renegotiate and no one who owns the number
    """
    out = []
    for v, s in shapes.items():
        monthly = s["monthly"]
        run_rate = monthly[-1] if monthly else 0.0
        annual = run_rate * 12
        risk = 0.0
        reasons = []
        if s["archetype"] in ("usage", "hybrid"):
            risk += annual * 0.6
            reasons.append("metered")
        if s["cardholders"] >= 5:
            risk += annual * 0.3
            reasons.append(f"{s['cardholders']} cardholders")
        if (s["mom_growth"] or 0) > 0.15:
            risk += annual * 0.4
            reasons.append(f"+{s['mom_growth']:.0%}/mo")
        out.append({**s, "annual_run_rate": annual, "exposure": risk,
                    "reasons": reasons})
    return sorted(out, key=lambda r: -r["exposure"])
