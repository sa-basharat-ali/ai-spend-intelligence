"""Card descriptor -> canonical vendor.

Two stages, and the second one is the whole point.

  Stage 1  clean the descriptor and match it against a registry of known vendors.
           This is what every internal build does and it works for exactly as long as
           the registry is current.

  Stage 2  cluster whatever did not match, by character trigram similarity, into
           groups that are one vendor each.

Stage 2 exists because a registry is a snapshot and the AI vendor list is not. Half the
line items a finance team is trying to understand this quarter are from companies that
did not have a product last year. A categorisation system that needs a human to add a
row before it can see a vendor will always be reporting on last quarter's spend, and the
whole question being asked is about this quarter's.

To make that concrete rather than rhetorical, the registry here deliberately omits the
newest vendors in the feed. They have to be recovered by clustering alone.
"""
import re
from collections import defaultdict

# Deliberately stale: no Anthropic, Cursor/Anyphere, Perplexity, Replit, ElevenLabs.
REGISTRY = {
    "OpenAI": ["OPENAI"],
    "GitHub": ["GITHUB"],
    "Amazon Web Services": ["AWS", "AMAZON WEB SERVICES"],
    "Google Cloud": ["GOOGLE CLOUD", "GOOGLE"],
    "Datadog": ["DATADOG"],
    "Slack": ["SLACK"],
    "Notion": ["NOTION", "NOTION LABS"],
    "Figma": ["FIGMA"],
    "Linear": ["LINEAR", "LINEAR ORBIT"],
    "Zoom": ["ZOOM", "ZOOM COMMUNICATIONS"],
}

_PHONE   = re.compile(r"\+?\d[\d\-\(\) ]{7,}\d")
_URLJUNK = re.compile(r"HTTPS?\S*|WWW\.\S*")
# Keep the domain STEM. "ZOOM.COM" is not noise, it is the vendor's name with a TLD
# stapled to it, and stripping the whole token deletes the only identifying text in
# the descriptor. That alone accounted for a bucket of unattributable spend.
_DOMAIN  = re.compile(r"\b([A-Z][A-Z0-9\-]{2,})\.(?:COM|CO|AI|IO|NET|ORG|SO|APP|DEV)\b")
_EMAIL   = re.compile(r"\S+@\S+")
_STATE   = re.compile(r"\b(?:[A-Z]{2})\s*$")
_REF     = re.compile(r"\b(?=[A-Z0-9]{5,8}\b)(?=[A-Z0-9]*\d)[A-Z0-9]+\b")
_NOISE   = {"INC", "INC.", "LLC", "LTD", "PBC", "CORP", "CO", "THE", "SUBSCRIPTION",
            "SUBSCR", "SUB", "PLAN", "PRO", "TEAM", "ENTERPRISE", "CREDIT", "CREDITS",
            "API", "SAN", "FRANCISCO", "NEW", "YORK", "JOSE", "DUBLIN", "EMEA"}


def clean(descriptor):
    """Strip everything the card network added and keep what the vendor is called."""
    s = descriptor.upper()
    s = _EMAIL.sub(" ", s)
    s = _URLJUNK.sub(" ", s)
    s = _DOMAIN.sub(r"\1", s)
    s = _PHONE.sub(" ", s)
    s = _STATE.sub(" ", s)
    s = s.split("*")[0] if "*" in s and len(s.split("*")[0].strip()) >= 3 else s
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = _REF.sub(" ", s)
    toks = [t for t in s.split() if t not in _NOISE and len(t) > 1]
    out = " ".join(toks).strip()
    if out:
        return out
    # Cleaning removed everything. Better to keep a noisy token than to drop the row
    # into an unattributable bucket, which is where money goes to hide.
    raw = re.sub(r"[^A-Z ]", " ", descriptor.upper())
    for t in raw.split():
        if len(t) > 2 and t not in _NOISE:
            return t
    return ""


def _trigrams(s):
    s = f"  {s} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def match_registry(cleaned):
    """Longest-alias-first prefix match. Longest first so 'GOOGLE CLOUD' is not
    swallowed by 'GOOGLE'."""
    best = None
    for canon, aliases in REGISTRY.items():
        for a in aliases:
            if cleaned.startswith(a) or a in cleaned:
                if best is None or len(a) > best[1]:
                    best = (canon, len(a))
    return best[0] if best else None


def cluster(cleaned_values, threshold=0.42):
    """Single-link agglomerative clustering on trigram Jaccard.

    Single-link rather than complete-link on purpose. Truncation means the same vendor
    appears as both 'ANTHROPIC CLAUDE' and 'ANTHROP', which share very little with each
    other directly but are each close to 'ANTHROPIC CLAUDE CODE'. Single-link chains
    them; complete-link splits them into three vendors.

    The cost is that single-link over-merges when two vendors share a stem, which is the
    trade being made and is worth stating rather than hiding."""
    vals = sorted(set(v for v in cleaned_values if v))
    tg = {v: _trigrams(v) for v in vals}
    parent = {v: v for v in vals}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def toks(v):
        return {t for t in v.split() if len(t) >= 5 and t not in _NOISE}
    tok = {v: toks(v) for v in vals}

    for i, a in enumerate(vals):
        for b in vals[i + 1:]:
            # Trigram similarity, or a shared distinctive token. "ANYSPHERE CURSOR" and
            # "CURSOR AI" share almost no trigrams and are obviously one vendor.
            if _jaccard(tg[a], tg[b]) >= threshold or (tok[a] & tok[b]):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

    groups = defaultdict(list)
    for v in vals:
        groups[find(v)].append(v)
    # label each cluster with its longest member, which is the least-truncated form
    return {v: max(members, key=len) for root, members in groups.items() for v in members}


def resolve(rows):
    """Full pipeline. Returns rows with `vendor` and `resolved_by` added."""
    cleaned = {r["descriptor"]: clean(r["descriptor"]) for r in rows}
    unmatched = set()
    reg = {}
    for desc, cl in cleaned.items():
        hit = match_registry(cl)
        if hit:
            reg[desc] = hit
        else:
            unmatched.add(cl)

    clusters = cluster(unmatched)
    out = []
    for r in rows:
        cl = cleaned[r["descriptor"]]
        if r["descriptor"] in reg:
            v, how = reg[r["descriptor"]], "registry"
        else:
            v, how = clusters.get(cl, cl), "cluster"
        out.append({**r, "cleaned": cl, "vendor": v, "resolved_by": how})
    return out
