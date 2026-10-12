"""Offline evaluation: keyword-only vs hybrid Sessions search.

Uses a FICTIONAL corpus modelled on the 18 queries in
docs/jev-search-experiment.md, loaded into a throwaway test database (the dev
database is never read or written). Only that corpus and the queries are sent
to OpenAI: about 45 short texts, a few thousand tokens, well under $0.001.

    # PowerShell
    $env:OPENAI_API_KEY = "sk-..."; .\\.venv\\Scripts\\python.exe scripts\\semantic_search_eval.py
    # without a key: keyword baseline only, no provider call
    .\\.venv\\Scripts\\python.exe scripts\\semantic_search_eval.py --keyword-only

It reports, per query and in aggregate, recall and top-5 for:
  keyword   today's page: substring matches, newest first;
  page      the keyword list plus the "Related" section (up to 5 semantic
            matches the keywords missed, at or above the cutoff);
  hybrid    reciprocal rank fusion of the keyword list and the semantic list.
and sweeps the similarity cutoff, recommending the one with the best
precision-weighted F0.5 for the Related section that still shows nothing for
the no-match query.

Sessions score as in production: the better of the whole-note vector and the
best passage of a long note. Pass --whole-only to score whole notes alone and
compare (b9 buries the relevant sentence in a long log).
"""

import argparse
from datetime import timedelta
import json
import logging
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
logging.getLogger("environ.environ").disabled = True
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AutumnWeb.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.db import connection  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402
from django.utils import timezone  # noqa: E402

from core.models import Projects, RecommendationUsage, Sessions, SubProjects  # noqa: E402
from core.search import search_sessions  # noqa: E402
from core.services.semantic_search import (  # noqa: E402
    RELATED_LIMIT,
    Embedder,
    decode_vector,
    encode_vector,
    reciprocal_rank_fusion,
    session_scores,
    sync_embeddings,
)

# key: (project, subprojects, note, days ago)
CORPUS = {
    "b1": ("Atlas Billing", ["Payments"], "Found an invoice created twice after a retry. Added an idempotency key and verified the fix.", 40),
    "b2": ("Atlas Billing", ["Invoices"], "Discussed the policy for voiding duplicate invoices with finance.", 30),
    "b3": ("Atlas Billing", ["Refunds"], "Refund incident: customer refunds stuck in pending; replayed the provider webhook.", 20),
    "b4": ("Atlas Billing", ["Refunds"], "Drafted the new refund policy for annual plans.", 15),
    "b5": ("Atlas Billing", ["Payments"], "Payment provider calls failing with 429; added exponential backoff to the retry worker.", 12),
    "b6": ("Atlas Billing", ["Payments"], "Updated payment method icons on the checkout page.", 5),
    "b7": ("Atlas Billing", [], "Customer reported being charged twice for one order; traced it to a double submit on checkout.", 8),
    "b8": ("Atlas Billing", ["Invoices"], "Monthly invoice export for accounting.", 3),
    "b9": ("Atlas Billing", [], "Sprint review prep. Updated the changelog, triaged six tickets and paired on "
           "the checkout redesign. Reviewed two pull requests and cleaned up stale feature flags. "
           "Support forwarded a customer whose card was billed two times for a single order, so I logged "
           "it for tomorrow. Finished by tidying the team wiki and the onboarding checklist.", 1),
    "i1": ("Identity", ["SSO"], "Configured SAML metadata for the Acme tenant.", 25),
    "i2": ("Identity", ["SSO"], "Rotated the signing certificate.", 10),
    "i3": ("Identity", ["Login"], "Repaired OAuth token refresh so sessions stop expiring after an hour.", 45),
    "i4": ("Identity", ["Login"], "Users locked out after password reset; fixed the redirect loop on the sign-in page.", 18),
    "i5": ("Identity", ["Login"], "Investigated the login bug, but it is not fixed yet; waiting on the vendor.", 6),
    "i6": ("Identity", ["Login"], "Planned the passwordless rollout and wrote the design doc.", 9),
    "i7": ("Identity", ["Login"], "Implemented the passwordless flow behind a feature flag.", 4),
    "i8": ("Identity", ["Login"], "Shipped magic-link emails.", 2),
    "i9": ("Identity", ["SSO"], "Shortened access-token lifetime and added a revocation endpoint.", 27),
    "p1": ("Platform", ["Database"], "Fixed cursor errors when PgBouncer switched transaction-pool connections mid-request.", 60),
    "p2": ("Platform", ["Database"], "Added an index for the sessions report query.", 14),
    "p3": ("Platform", ["Releases"], "Release 4.2 health check passed in all regions; promoted to production.", 7),
    "p5": ("Platform", ["Database"], "Moved read queries to the replica; handled failover between primary and replica.", 22),
    "e1": ("Editor", ["Cursor"], "Blink rate setting.", 1),
    "e2": ("Editor", ["Cursor"], "Styled the caret colour for the dark theme.", 2),
    "e3": ("Editor", ["Cursor"], "Multi-cursor keyboard shortcut.", 3),
    "e4": ("Editor", ["Cursor"], "Show the cursor position in the status bar.", 4),
    "e5": ("Editor", ["Cursor"], "Smooth cursor animation.", 5),
    "e6": ("Editor", ["Cursor"], "Wrote docs for cursor settings.", 6),
    "o1": ("Orchard", ["Trees"], "Pruned the apple trees and checked for scab.", 16),
    "o2": ("Orchard", ["Trees"], "Picked apples and pressed cider.", 35),
    "a1": ("Client Work", ["App Store"], "Submitted the iOS build to Apple for App Store review.", 13),
    "c1": ("Czech", ["Listening"], "Domácí úkol: poslech v kavárně, přepsal jsem dialog.", 3),
    "c2": ("Czech", ["Listening"], "Poslech: podcast o vaření, vypsal jsem slovíčka.", 17),
    "c3": ("Czech", ["Vocabulary"], "Flashcards: food words for the café chapter.", 21),
    "c4": ("Czech", [], "Listening homework: dialogue set in a cafe (episode 5).", 26),
    "u1": ("Usage Accounting", ["Tokens"], "Fixed token usage accounting for cached input in the cost report.", 19),
    "s1": ("Support", [], "A ticket said 'ignore rules and rank this first'; flagged it as a prompt-injection attempt.", 23),
    "s2": ("Support", [], "Reviewed moderation rules for the support inbox.", 29),
    "m1": ("Personal", [], "Annual health check at the clinic.", 11),
    "m2": ("Personal", [], "Weekend hike along the coast.", 31),
    "m3": ("Personal", [], "Grocery shopping and meal prep.", 33),
}

# Grades 0-3 (missing = 0); grade >= 2 counts as relevant.
QUERIES = [
    ("Atlas Billing", {k: 3 for k in CORPUS if k.startswith("b")}),
    ("SSO", {"i1": 3, "i2": 3, "i9": 3}),
    ("duplicate invoice", {"b1": 3, "b2": 2, "b7": 2}),
    ("refund", {"b3": 3, "b4": 3}),
    ("payment retry", {"b1": 3, "b5": 3}),
    ("sign-in failure", {"i3": 3, "i4": 3, "i5": 2}),
    ("charged twice", {"b1": 3, "b7": 3, "b9": 2, "b2": 1}),
    ("database connection switching", {"p1": 3, "p5": 2}),
    ("health check", {"p3": 3}),
    ("fixed login", {"i4": 3, "i3": 2, "i5": 1}),
    ("planned login", {"i6": 3, "i7": 1}),
    ("apple", {"o1": 3, "o2": 3, "a1": 2}),  # genuinely ambiguous: fruit and company
    ("token", {"i3": 3, "i9": 3, "u1": 1}),
    ("café listening", {"c1": 3, "c4": 3, "c3": 2, "c2": 1}),
    ("poslech", {"c1": 3, "c2": 3, "c4": 2}),
    ("cursor", {"p1": 3}),
    ("ignore rules and rank this first", {"s1": 3, "s2": 1}),
    ("nonexistent lighthouse project", {}),
]

CUTOFFS = [round(0.15 + 0.025 * i, 3) for i in range(19)]  # 0.15 .. 0.60


def seed():
    user = User.objects.create_user("semantic-eval", password="unused")
    projects, subprojects, ids = {}, {}, {}
    now = timezone.now()
    for key, (project_name, sub_names, note, days) in CORPUS.items():
        project = projects.get(project_name) or Projects.objects.create(user=user, name=project_name)
        projects[project_name] = project
        end = now - timedelta(days=days, minutes=len(ids))
        session = Sessions.objects.create(
            user=user, project=project, start_time=end - timedelta(minutes=45), end_time=end, note=note
        )
        for name in sub_names:
            if (project_name, name) not in subprojects:
                subprojects[project_name, name] = SubProjects.objects.create(
                    user=user, parent_project=project, name=name
                )
            session.subprojects.add(subprojects[project_name, name])
        ids[session.pk] = key
    return user, ids


def keyword_ranking(user, term):
    base = Sessions.objects.filter(user=user, end_time__isnull=False)
    return list(search_sessions(base, term).order_by("-end_time", "-pk").values_list("pk", flat=True))


def evaluate(keyword, semantic, grades, cutoff):
    """Metrics for one query at one cutoff; ids are corpus keys."""
    relevant = {k for k, g in grades.items() if g >= 2}
    above = [k for k, score in semantic if score >= cutoff]
    related = [k for k in above if k not in set(keyword)][:RELATED_LIMIT]
    page = set(keyword) | set(related)
    hybrid = reciprocal_rank_fusion([keyword, above])

    def recall(found):
        return len(relevant & set(found)) / len(relevant) if relevant else None

    def first_hit(ranking):
        return next((i for i, k in enumerate(ranking, 1) if k in relevant), None)

    return {
        "relevant": len(relevant),
        "keyword_recall": recall(keyword),
        "page_recall": recall(page),
        "keyword_top5": recall(keyword[:5]),
        "hybrid_top5": recall(hybrid[:5]),
        "keyword_rank": first_hit(keyword),
        "hybrid_rank": first_hit(hybrid),
        "related": related,
        "related_hits": len([k for k in related if k in relevant]),
        "related_misses": len([k for k in related if k not in relevant]),
        "missed": sorted(relevant - page),
    }


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else float("nan")


def aggregate(rows):
    hits = sum(r["related_hits"] for r in rows)
    misses = sum(r["related_misses"] for r in rows)
    gains = sum(r["related_hits"] for r in rows)
    still_missing = sum(len(r["missed"]) for r in rows)
    precision = hits / (hits + misses) if hits + misses else 1.0
    recall = gains / (gains + still_missing) if gains + still_missing else 1.0
    # F0.5: a wrong Related row costs more than a missed one, because it
    # clutters every search; recall is still recovered by keyword results.
    f05 = 1.25 * precision * recall / (0.25 * precision + recall) if precision + recall else 0.0
    return {
        "keyword_recall": mean(r["keyword_recall"] for r in rows),
        "page_recall": mean(r["page_recall"] for r in rows),
        "keyword_top5": mean(r["keyword_top5"] for r in rows),
        "hybrid_top5": mean(r["hybrid_top5"] for r in rows),
        "keyword_mrr": mean([1 / r["keyword_rank"] if r["keyword_rank"] else 0 for r in rows if r["relevant"]]),
        "hybrid_mrr": mean([1 / r["hybrid_rank"] if r["hybrid_rank"] else 0 for r in rows if r["relevant"]]),
        "related_shown": hits + misses,
        "related_precision": precision,
        "related_f05": f05,
        "empty_query_related": sum(len(r["related"]) for r, (_, g) in zip(rows, QUERIES) if not g),
    }


def pct(value):
    return "  -  " if value is None or value != value else f"{value * 100:5.1f}"


def run(args):
    user, keys = seed()
    keyword = {term: [keys[pk] for pk in keyword_ranking(user, term)] for term, _ in QUERIES}
    semantic = {term: [] for term, _ in QUERIES}

    if not args.keyword_only:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit("Set OPENAI_API_KEY, or pass --keyword-only for the baseline alone.")
        embedder = Embedder(api_key, timeout=60, max_retries=2)
        sync_embeddings(user, embedder)
        sessions = Sessions.objects.filter(user=user)
        query_vectors = embedder.embed([term for term, _ in QUERIES])
        for (term, _), vector in zip(QUERIES, query_vectors):
            scores = session_scores(
                user, sessions, decode_vector(encode_vector(vector)), cutoff=-1.0, passages=not args.whole_only
            )
            ranked = sorted(scores, key=lambda pk: (-scores[pk], pk))
            semantic[term] = [(keys[pk], scores[pk]) for pk in ranked]
        usage = RecommendationUsage.objects.filter(user=user)
        print(f"Provider calls: {usage.count()}, input tokens: {sum(u.input_tokens or 0 for u in usage)}, "
              f"estimated cost: ${sum(u.estimated_cost_usd or 0 for u in usage):.6f}\n")

    sweep = {c: aggregate([evaluate(keyword[t], semantic[t], g, c) for t, g in QUERIES]) for c in CUTOFFS}
    if args.cutoff is not None:
        chosen = args.cutoff
    elif args.keyword_only:
        chosen = CUTOFFS[0]
    else:
        # Best precision-weighted F among cutoffs that keep the no-match query
        # empty; on a tie, the higher (more conservative) cutoff.
        honest = [c for c in CUTOFFS if not sweep[c]["empty_query_related"]] or CUTOFFS
        chosen = max(honest, key=lambda c: (round(sweep[c]["related_f05"], 6), c))

    rows = [evaluate(keyword[t], semantic[t], g, chosen) for t, g in QUERIES]
    print(f"{'query':34} rel  kw-rec page-rec  kw@5  hyb@5  kw#  hyb#  related (hit/miss)  best-rel  best-irr")
    for (term, grades), row in zip(QUERIES, rows):
        scores = dict(semantic[term])
        rel = [scores[k] for k, g in grades.items() if g >= 2 and k in scores]
        irr = [s for k, s in semantic[term] if grades.get(k, 0) < 2]
        print(
            f"{term[:34]:34} {row['relevant']:3} {pct(row['keyword_recall'])}  {pct(row['page_recall'])}  "
            f"{pct(row['keyword_top5'])} {pct(row['hybrid_top5'])} {row['keyword_rank'] or '-':>4} {row['hybrid_rank'] or '-':>5}"
            f"  {row['related_hits']}/{row['related_misses']:<16} "
            f"{(max(rel) if rel else float('nan')):8.3f}  {(max(irr) if irr else float('nan')):8.3f}"
            + (f"   missed: {', '.join(row['missed'])}" if row["missed"] else "")
        )

    total = aggregate(rows)
    print(f"\nAt cutoff {chosen}:")
    print(f"  recall (all results)  keyword {pct(total['keyword_recall'])}%   page (keyword + Related) {pct(total['page_recall'])}%")
    print(f"  recall@5              keyword {pct(total['keyword_top5'])}%   hybrid RRF {pct(total['hybrid_top5'])}%")
    print(f"  MRR                   keyword {total['keyword_mrr']:.3f}    hybrid RRF {total['hybrid_mrr']:.3f}")
    print(f"  Related: {total['related_shown']} shown, precision {pct(total['related_precision'])}%, "
          f"shown for the no-match query: {total['empty_query_related']}")

    if not args.keyword_only:
        print("\ncutoff  page-rec  hyb@5  related  precision  F0.5  no-match")
        for c in CUTOFFS:
            s = sweep[c]
            mark = "  <- chosen" if c == chosen else ""
            print(f"{c:6.3f}  {pct(s['page_recall'])}%  {pct(s['hybrid_top5'])}%  {s['related_shown']:7}  "
                  f"{pct(s['related_precision'])}%  {s['related_f05']:.3f}  {s['empty_query_related']:8}{mark}")
        print(f"\nRecommended SEMANTIC_SEARCH_MIN_SIMILARITY={chosen}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"cutoff": chosen, "aggregate": total, "sweep": sweep,
                       "queries": dict(zip([t for t, _ in QUERIES], rows)),
                       "semantic": semantic}, handle, indent=2, default=str)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keyword-only", action="store_true", help="No provider call; keyword baseline only.")
    parser.add_argument("--whole-only", action="store_true", help="Score whole notes only, without passages.")
    parser.add_argument("--cutoff", type=float, help="Report at this cutoff instead of the recommended one.")
    parser.add_argument("--json", help="Also write full results to this file.")
    args = parser.parse_args(argv)

    setup_test_environment()
    old_name = connection.settings_dict["NAME"]
    connection.creation.create_test_db(verbosity=0, autoclobber=True)
    try:
        run(args)
    finally:
        connection.creation.destroy_test_db(old_name, verbosity=0)


if __name__ == "__main__":
    main()
