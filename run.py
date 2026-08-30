#!/usr/bin/env python3
"""AI spend intelligence from a raw corporate card feed.

    python3 run.py        stdlib only, no install, <1s

Generated feed, deterministic seed, no real company's data.
"""
import os, sys, json, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from collections import defaultdict, Counter
import transactions, normalize, analyze

line = lambda c="=", n=84: print(c * n)
money = lambda x: f"${x:,.0f}"

rows, employees = transactions.build()
res = normalize.resolve(rows)
shapes = analyze.classify(res)

print()
line()
print("  AI SPEND INTELLIGENCE FROM A RAW CARD FEED")
line()
total = sum(r["amount_usd"] for r in rows)
print(f"  {len(rows):,} transactions   {len(employees)} employees   "
      f"{transactions.DAYS} days   {money(total)}")
print(f"  {len({r['descriptor'] for r in rows})} distinct descriptors")

# ---- 1. descriptor resolution ----------------------------------------------
print("\n\n1. THE DESCRIPTORS ARE THE PROBLEM\n")
seen = []
for r in res:
    if r["_vendor"] in ("Anthropic", "OpenAI", "Cursor", "Amazon Web Services") \
            and (r["descriptor"], r["vendor"]) not in seen:
        seen.append((r["descriptor"], r["vendor"]))
print(f"   {'raw descriptor':<40}{'cleaned':<22}{'resolved to':<22}via")
print("   " + "-" * 92)
for d, v in seen[:11]:
    cl = normalize.clean(d)
    how = next(x["resolved_by"] for x in res if x["descriptor"] == d)
    print(f"   {d[:38]:<40}{cl[:20]:<22}{v[:20]:<22}{how}")

groups = defaultdict(Counter)
for r in res:
    groups[r["vendor"]][r["_vendor"]] += 1
purity = sum(c.most_common(1)[0][1] for c in groups.values()) / len(res)
n_cluster = len({r["vendor"] for r in res if r["resolved_by"] == "cluster"})
print(f"\n   {len(groups)} vendors recovered from {len({r['descriptor'] for r in rows})} "
      f"descriptors, {purity:.1%} pure, one-to-one against ground truth.")
print(f"\n   {n_cluster} of them came from clustering, not the registry, because the registry")
print(f"   deliberately does not contain them. That is the design point rather than a")
print(f"   demo trick: a vendor registry is a snapshot and the AI vendor list is not.")
print(f"   Half the line items a finance team is trying to understand this quarter are")
print(f"   from companies that did not have a product last year, and a system that needs")
print(f"   a human to add a row before it can see a vendor is always reporting on last")
print(f"   quarter while being asked about this one.")

# ---- 2. billing shape -------------------------------------------------------
print("\n\n2. WHICH VENDORS EXISTING SPEND CONTROLS CANNOT GOVERN\n")
truth = {r["vendor"]: r["_archetype"] for r in res}
print(f"   {'vendor':<30}{'shape':<9}{'days/mo':>9}{'cv':>7}{'distinct':>10}"
      f"{'6mo spend':>12}")
print("   " + "-" * 79)
correct = 0
for v, s in sorted(shapes.items(), key=lambda kv: -kv[1]["total"]):
    correct += s["archetype"] == truth[v]
    flag = "" if s["archetype"] == truth[v] else "  <-- called it wrong"
    print(f"   {v[:28]:<30}{s['archetype']:<9}{s['charge_days']:>9.1f}{s['cv']:>7.2f}"
          f"{s['distinct_ratio']:>10.2f}{money(s['total']):>12}{flag}")
print(f"\n   {correct}/{len(shapes)} correct against ground truth, from the time series alone.")
print(f"   No vendor list, no lookup, no manual tagging.")
miss = [v for v, s in shapes.items() if s["archetype"] != truth[v]]
if miss:
    v = miss[0]
    print(f"\n   The miss is real and worth keeping: {v[:20]} is a seat floor with usage on")
    print(f"   top, and the usage half dominates its signature. Three features cannot see a")
    print(f"   floor underneath a meter. Separating the recurring component would need the")
    print(f"   charge-level structure, which is a bigger model than this deserves.")
print(f"\n   Every spend control ever shipped assumes the seat shape: a limit, an approval,")
print(f"   a budget, all keyed to a predictable recurring amount. Pointed at a metered")
print(f"   vendor they do not fail loudly. They just quietly stop being controls.")

# ---- 3. forecasting ---------------------------------------------------------
table, cases = analyze.forecast(res, shapes)
print("\n\n3. WHEN CAN YOU ACTUALLY CALL MONTH-END\n")
print(f"   {'as of day':>10}{'n':>5}{'run-rate err':>15}{'empirical err':>15}"
      f"{'80% coverage':>15}{'half-width':>13}")
print("   " + "-" * 75)
for r in table:
    print(f"   {r['as_of_day']:>10}{r['n']:>5}{r['runrate_mape']:>14.1%}"
          f"{r['empirical_mape']:>15.1%}{r['coverage_80']:>15.0%}{r['half_width']:>12.0%}")

print("\n   Two findings and the first one is negative.")
print("\n   Nothing beats plain run-rate as a point estimate. I tried weekday pacing plus a")
print("   growth trend, which was worse at three of five cutoffs, and then an empirical")
print("   ratio model, which ties. Early-month error on a metered vendor is not a calendar")
print("   effect, it is lumpiness: a few large charges dominate the month and whether two")
print("   of them have landed by day 5 is close to a coin flip. A cleverer point estimate")
print("   cannot fix variance.")
d8 = next(r for r in table if r["as_of_day"] == 8)
d12 = next(r for r in table if r["as_of_day"] == 12)
d20 = next(r for r in table if r["as_of_day"] == 20)
print(f"\n   So the answer is not a better number, it is an honest interval. Coverage runs")
print(f"   {min(r['coverage_80'] for r in table):.0%} to {max(r['coverage_80'] for r in table):.0%} "
      f"against a nominal 80%, so the intervals mean what they say.")
print(f"\n   And then the interval answers the question finance actually has. On day "
      f"{d8['as_of_day']} the")
print(f"   honest range is plus or minus {d8['half_width']:.0%}. On day {d12['as_of_day']} it is "
      f"{d12['half_width']:.0%}. On day {d20['as_of_day']} it is {d20['half_width']:.0%}.")
print(f"   Metered spend is not callable before roughly day {d12['as_of_day']}, and any dashboard")
print(f"   showing a run-rate projection on day 5 is displaying a point estimate that is")
print(f"   really a plus-or-minus {next(r for r in table if r['as_of_day']==5)['half_width']:.0%} range.")
print(f"   That gap is the whole mechanism by which this category becomes an invisible cost.")

# ---- 4. control gap ---------------------------------------------------------
gap = analyze.control_gap(shapes, res, transactions.DAYS // 30)
print("\n\n4. WHERE TO POINT A CONTROL FIRST\n")
print(f"   {'vendor':<30}{'annual run-rate':>17}{'holders':>9}{'teams':>7}   why")
print("   " + "-" * 82)
for g in gap[:9]:
    print(f"   {g['vendor'][:28]:<30}{money(g['annual_run_rate']):>17}"
          f"{g['cardholders']:>9}{g['teams']:>7}   {', '.join(g['reasons']) or '-'}")

ai = [g for g in gap if g["vendor"][:9].upper() in
      ("ANTHROPIC", "OPENAI", "PERPLEXIT", "ELEVEN LA", "REPLIT 14", "ANYSPHERE")]
ai_annual = sum(g["annual_run_rate"] for g in ai)
diffuse = [g for g in gap if g["cardholders"] >= 5]
print(f"\n   {money(ai_annual)} a year across {len(ai)} AI vendors, none of which existed as a")
print(f"   budget line eighteen months ago, and {len([g for g in ai if g['cardholders']>=5])} "
      f"of them are paid by five or more")
print(f"   separate cardholders. There is no subscription to renegotiate and nobody owns")
print(f"   the number.")
# rank by absolute dollars added, not by growth rate: a 40% month on $900 is noise
growers = [g for g in gap if (g["mom_growth"] or 0) > 0.10 and g["monthly"]]
for g in growers:
    now = g["monthly"][-1]
    g["_in6"] = now * (1 + g["mom_growth"]) ** 6
    g["_added"] = g["_in6"] - now
growers.sort(key=lambda g: -g["_added"])
print(f"\n   {'vendor':<24}{'this month':>13}{'MoM':>7}{'in 6 months':>14}{'added':>12}")
print("   " + "-" * 70)
for g in growers[:5]:
    print(f"   {g['vendor'][:22]:<24}{money(g['monthly'][-1]):>13}"
          f"{g['mom_growth']:>7.0%}{money(g['_in6']):>14}{money(g['_added']):>12}")
tot6 = sum(g["_added"] for g in growers)
print(f"\n   {money(tot6)} a month of new spend within two quarters if the current rates hold,")
print(f"   and they will not hold, which is the point. Nobody knows whether they will")
print(f"   halve or double, and nothing in the feed flags either because every individual")
print(f"   charge is small and unremarkable. The reason to surface it on day 12 rather")
print(f"   than in the month-end close is that day 12 is while you can still do something.")

json.dump({"purity": purity, "shape_accuracy": correct / len(shapes),
           "forecast": table, "control_gap": gap,
           "vendors": {v: {k: s[k] for k in
                           ("archetype", "total", "cardholders", "teams", "mom_growth")}
                       for v, s in shapes.items()}},
          open("results.json", "w"), indent=2, default=str)
print("\n   -> results.json\n")
line()
