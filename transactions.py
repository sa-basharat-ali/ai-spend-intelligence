"""A corporate card transaction feed for a ~600 person company, 6 months.

The descriptors are the point. Card network descriptors arrive mangled: truncated to 22
or 25 characters, carrying phone numbers, city and country codes, per-transaction
reference hashes, and an entity name that may be the legal entity, the product, the
reseller, or an acronym nobody outside the vendor recognises. Anyone who has tried to
answer "how much are we spending on AI" from a card feed has met this.

Three vendor archetypes, because they need completely different controls:

  seat      monthly, stable, amounts land on a small set of values, steps when seats
            are added. Every spend control ever built assumes this shape
  usage     charges land continuously, amounts are unbounded and trending, and you find
            out what you spent after you have spent it
  hybrid    a seat floor with usage on top

Deterministic seed. No real company's data.
"""
import random, math, zlib
from datetime import date, timedelta

SEED = 8811
START = date(2026, 3, 1)
DAYS = 183
N_EMPLOYEES = 600

# canonical -> (billing archetype, descriptor templates, base monthly $, monthly growth)
VENDORS = {
    "Anthropic": ("usage", [
        "ANTHROPIC*CLAUDE.AI HTTPSWWW.ANTH CA", "ANTHROPIC PBC       SAN FRANCISCO CA",
        "ANTHROPIC*API CREDIT  +14155551212 CA", "ANTHROPIC*CLAUDE CODE   SF CA",
    ], 5200, 0.34),
    "OpenAI": ("usage", [
        "OPENAI *CHATGPT SUBSCR SAN FRANCISCOCA", "OPENAI                +14155551212 CA",
        "OPENAI *API           HTTPSOPENAI.C CA", "OPENAI, LLC   SAN FRANCISCO      CA",
    ], 6100, 0.21),
    "Cursor": ("seat", [
        "ANYSPHERE INC (CURSOR) SAN FRANCISCOCA", "CURSOR AI           HTTPSCURSOR.S CA",
        "ANYSPHERE*CURSOR PRO    SF          CA",
    ], 1900, 0.11),
    "GitHub": ("seat", [
        "GITHUB *COPILOT      HTTPSGITHUB.C CA", "GITHUB, INC.        +18774484820 CA",
        "GITHUB *ENTERPRISE     SAN FRANCISCOCA",
    ], 2400, 0.04),
    "Perplexity": ("seat", [
        "PERPLEXITY *PRO      HTTPSPERPLEXI CA", "PERPLEXITY AI INC   SAN FRANCISCO CA",
    ], 640, 0.16),
    "Replit": ("hybrid", [
        "REPLIT SUBSCRIPTION  HTTPSREPLIT.C CA", "REPLIT, INC.        +14155551212 CA",
    ], 780, 0.19),
    "ElevenLabs": ("usage", [
        "ELEVENLABS*CREDITS   HTTPSELEVENLA NY", "ELEVEN LABS INC       NEW YORK    NY",
    ], 430, 0.28),
    "Amazon Web Services": ("usage", [
        "AWS EMEA            aws.amazon.co LU", "AMAZON WEB SERVICES  AWS.AMAZON.CO WA",
        "AWS*BEDROCK          AWS.AMAZON.CO WA",
    ], 41000, 0.06),
    "Google Cloud": ("usage", [
        "GOOGLE *CLOUD 8Y7X2Q  cc@google.com CA", "GOOGLE*CLOUD VERTEX   CC@GOOGLE.COM CA",
        "GOOGLE CLOUD EMEA     DUBLIN         IE",
    ], 12800, 0.09),
    "Datadog": ("usage", [
        "DATADOG INC         +18664586837 NY", "DATADOG, INC.        HTTPSWWW.DATA NY",
    ], 8900, 0.05),
    "Slack": ("seat", ["SLACK T04HN8L*      HTTPSSLACK.CO CA",
                       "SLACK TECHNOLOGIES   SAN FRANCISCO CA"], 4200, 0.01),
    "Notion": ("seat", ["NOTION LABS INC     HTTPSNOTION.S CA",
                        "NOTION *TEAM PLAN    SAN FRANCISCO CA"], 1800, 0.02),
    "Figma": ("seat", ["FIGMA *SUBSCRIPTION  HTTPSFIGMA.CO CA",
                       "FIGMA INC           +14155551212 CA"], 2600, 0.02),
    "Linear": ("seat", ["LINEAR ORBIT INC    HTTPSLINEAR.A CA"], 1400, 0.03),
    "Zoom": ("seat", ["ZOOM.COM 888-799-9666 CA", "ZOOM COMMUNICATIONS  SAN JOSE     CA"], 2100, 0.0),
}

TEAMS = ["Engineering", "Data", "Product", "Design", "GTM", "Support", "Finance"]


def _ref(rnd):
    """Takes the seeded generator explicitly. Using the module-level `random` here made
    the descriptor count drift between runs while every other number stayed put, which
    is the most annoying possible way for a "deterministic" claim to be false."""
    return "".join(rnd.choice("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6))


def build(seed=SEED):
    rnd = random.Random(seed)
    employees = [{"employee_id": f"E{i:04d}", "team": rnd.choices(
        TEAMS, weights=[38, 9, 11, 7, 18, 11, 6])[0]} for i in range(N_EMPLOYEES)]

    # who holds a card for which vendor. Shadow AI is the default state, not the
    # exception: individual engineers expense their own tools long before procurement
    # notices there is a category.
    holders = {}
    for v, (arch, _, base, _) in VENDORS.items():
        n = 1 if base > 8000 else rnd.randint(3, 22)     # infra is centralised, tools are not
        pool = [e for e in employees if e["team"] in
                (["Engineering", "Data", "Product"] if v in
                 ("Anthropic", "OpenAI", "Cursor", "GitHub", "Replit", "Amazon Web Services",
                  "Google Cloud", "Datadog") else TEAMS)]
        holders[v] = rnd.sample(pool, k=min(n, len(pool)))

    txns = []
    for v, (arch, templates, base, growth) in VENDORS.items():
        for day in range(DAYS):
            d = START + timedelta(days=day)
            month = day // 30
            scale = (1 + growth) ** month

            if arch == "seat":
                # zlib.crc32, not hash(). Python randomises string hashing per process
                # unless PYTHONHASHSEED is pinned, so hash() here made the billing day
                # move between runs and quietly broke the deterministic-seed claim.
                if d.day != 1 + (zlib.crc32(v.encode()) % 5):
                    continue
                per = base * scale / max(len(holders[v]), 1)
                for e in holders[v]:
                    amt = round(per * rnd.choice([1.0, 1.0, 1.0, 1.0, 0.5, 2.0]), 2)
                    txns.append((d, v, templates, amt, e, arch))
            else:
                # usage lands continuously and is lumpy. weekday-heavy for dev tools.
                lam = 2.2 if base > 8000 else 0.9
                wd = 1.0 if d.weekday() < 5 else 0.35
                n = sum(1 for _ in range(6) if rnd.random() < lam * wd / 6)
                if arch == "hybrid" and d.day == 3:
                    e = rnd.choice(holders[v])
                    txns.append((d, v, templates, round(base * scale * 0.45, 2), e, arch))
                daily = base * scale / 30 * (0.55 if arch == "hybrid" else 1.0)
                for _ in range(n):
                    amt = round(daily / max(lam * wd, 0.2) * math.exp(rnd.gauss(0, 0.75)), 2)
                    if amt < 0.5:
                        continue
                    txns.append((d, v, templates, amt, rnd.choice(holders[v]), arch))

    rows = []
    for i, (d, v, templates, amt, e, arch) in enumerate(sorted(txns, key=lambda t: t[0])):
        desc = rnd.choice(templates)
        if rnd.random() < 0.30:                      # network truncation
            desc = desc[:rnd.choice([22, 25])]
        if rnd.random() < 0.18:                      # per-transaction reference
            desc = desc.replace("*", f"*{_ref(rnd)} ", 1)
        rows.append({
            "txn_id": f"T{i:06d}", "date": d.isoformat(), "day_index": (d - START).days,
            "descriptor": desc, "amount_usd": amt,
            "employee_id": e["employee_id"], "team": e["team"],
            "_vendor": v, "_archetype": arch,        # ground truth, evaluation only
        })
    return rows, employees


if __name__ == "__main__":
    rows, emp = build()
    total = sum(r["amount_usd"] for r in rows)
    print(f"{len(rows):,} transactions, {DAYS} days, ${total:,.0f} total")
    print(f"{len({r['descriptor'] for r in rows})} distinct descriptors for "
          f"{len(VENDORS)} vendors")
    for r in rows[:6]:
        print(f"  {r['date']}  {r['descriptor']:<40} ${r['amount_usd']:>9,.2f}")
