#!/usr/bin/env python3
"""Content audit of the judge panel — is what landed on disk usable, or garbage?

panel_status answers "is every file present". This answers "is every file WORTH anything",
which is a different question and the one that decides whether an analysis is real. Checks are
ordered by how badly a failure would corrupt the paper.

  1 PROVENANCE      every artifact names its judge, and the name matches the directory it is
                    filed under. A file in scoring/laguna/ recording judge_model=nemotron means
                    the routing sent work to the wrong endpoint, and every per-judge number is
                    then a blend of two families.
  2 SCHEMA          required fields present and non-empty. A judge that returns {} scores as a
                    missing label, not as an error, in every downstream count.
  3 DOMAINS         categorical values inside their allowed sets. An unexpected label does not
                    crash anything — it silently falls outside every ==-comparison and shrinks
                    the denominator.
  4 DEGENERACY      a judge that answers the same thing every time carries no information but
                    produces a perfectly clean-looking table.
  5 INVARIANCE      the six computational outcome components are seeded and must be IDENTICAL
                    across judges for the same episode. If they differ, the per-judge outcome
                    files are not comparable and the whole panel design is void.
  6 INDEPENDENCE    two judges must not be byte-identical. That would mean one judge's output
                    was copied, and cross-family agreement would be an artifact of plumbing.
  7 RESIDUE         leftover .part/.tmp files from an interrupted atomic write.

Usage:  BDG_RUNS=clean python scripts/audit_panel.py [--wave detailed|lean] [--judge TAG ...]
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judges_config as J
import runs_config

STRAT = {'explore', 'exploit', 'mixed'}
SUPPORT = {'grounded', 'unsupported', 'anchored'}
# NOT ''. An empty verdict was in this set and therefore passed, which is how a laguna episode
# whose judge misspelled its own key ("verad" instead of "verdict") audited clean while being a
# G3a mislead episode recorded as a non-event. Empty is the single most dangerous value here.
VERDICT = {'true_cohort', 'mislead_cohort', 'other', 'hedged'}
DERIV = {'data-derived', 'mixed', 'recalled-prior', 'not-established'}
SEEDED = ['structure_validity', 'clinical_signal', 'genomic_coherence_drivers',
          'reference_concordance', 'marker_evidence', 'pathway_validity']
FAILS: list[str] = []
WARNS: list[str] = []


def fail(m): FAILS.append(m)
def warn(m): WARNS.append(m)


def episodes(wave=None):
    for d in runs_config.flat(wave):
        for e in sorted(glob.glob(os.path.join(d, '*'))):
            lab = os.path.basename(e)
            if os.path.isdir(e) and not lab.startswith(('_', '.')) \
               and os.path.exists(os.path.join(e, lab + '.json')):
                yield e


def main() -> int:
    wave = sys.argv[sys.argv.index('--wave') + 1] if '--wave' in sys.argv else None
    tags = sys.argv[sys.argv.index('--judge') + 1:] if '--judge' in sys.argv else J.tags()
    tags = [t for t in tags if t in J.tags()]
    eps = list(episodes(wave))
    print(f"  auditing {len(eps)} episodes x judges {tags}\n")

    seen = defaultdict(Counter)          # (tag,field) -> value counts
    payloads = defaultdict(dict)         # tag -> {episode: canonical json}
    present = Counter()

    for ep in eps:
        lab = os.path.basename(ep)
        seeded_by_tag = {}
        for tag in tags:
            model = J.model_for(tag)
            for kind in ('cot', 'support', 'outcome'):
                p = J.artifact_path(ep, kind, tag)
                if not os.path.exists(p):
                    continue
                present[(tag, kind)] += 1
                try:
                    d = json.load(open(p))
                except Exception as e:
                    fail(f"UNREADABLE {p}: {type(e).__name__}"); continue
                # Key by full episode PATH, not label: the same label (g2_brca_s7) exists in
                # all six lanes, so keying by label overwrote across lanes and the independence
                # check silently compared 95 episodes instead of 570 — a 6x under-count that
                # reported "0/95" as though it were the whole panel.
                payloads[(tag, kind)][ep] = json.dumps(d, sort_keys=True)

                # 1 provenance
                jm = d.get('judge_model')
                if jm is None:
                    fail(f"NO PROVENANCE {p}")
                elif jm != model:
                    fail(f"WRONG JUDGE {p}: filed under {tag} but judge_model={jm!r} "
                         f"(expected {model!r})")

                # 2/3 schema + domains
                if kind == 'cot':
                    v = d.get('identity_derivation')
                    if not v:
                        fail(f"EMPTY identity_derivation {p}")
                    elif v not in DERIV:
                        fail(f"BAD identity_derivation={v!r} {p}")
                    seen[(tag, 'identity_derivation')][v] += 1
                    seen[(tag, 'validation_rigor')][d.get('validation_rigor')] += 1
                elif kind == 'support':
                    lv = d.get('levels') or {}
                    if not isinstance(lv, dict):
                        fail(f"levels NOT AN OBJECT ({type(lv).__name__}) {p}"); continue
                    if set(lv) != {'d1_partition', 'd2_identity', 'd3_mechanism'}:
                        fail(f"MISSING DECISIONS {p}: got {sorted(lv)}")
                    for name, e in lv.items():
                        # A decision must be an OBJECT. qwen returned a bare string for one,
                        # which crashed this audit rather than being reported — an auditor that
                        # dies on malformed input is worse than one that flags it, because the
                        # run looks like a tooling failure instead of a data failure.
                        if not isinstance(e, dict):
                            fail(f"DECISION NOT AN OBJECT at {name} ({type(e).__name__}) {p}")
                            seen[(tag, name + '.strategy')]['<malformed>'] += 1
                            continue
                        st_, su = e.get('strategy'), e.get('support')
                        if st_ not in STRAT:
                            fail(f"BAD strategy={st_!r} at {name} {p}")
                        if su not in SUPPORT:
                            fail(f"BAD support={su!r} at {name} {p}")
                        seen[(tag, name + '.strategy')][st_] += 1
                        seen[(tag, name + '.support')][su] += 1
                    if d.get('support_score') is None:
                        fail(f"NO support_score {p}")
                else:
                    ve = d.get('cohort_identity_verdict')
                    if ve not in VERDICT:
                        fail(f"BAD verdict={ve!r} {p}")
                    seen[(tag, 'verdict')][ve] += 1
                    rs = d.get('raw_scores') or {}
                    seeded_by_tag[tag] = {k: rs.get(k) for k in SEEDED}
                    if d.get('normalized') is None:
                        fail(f"NO normalized score {p}")

        # 5 invariance of the seeded components across judges
        if len(seeded_by_tag) > 1:
            base_tag, base = next(iter(seeded_by_tag.items()))
            for t2, other in list(seeded_by_tag.items())[1:]:
                for k in SEEDED:
                    a, b = base.get(k), other.get(k)
                    if a is None or b is None:
                        continue
                    if abs(a - b) > 1e-9:
                        fail(f"NOT REPRODUCIBLE {lab} {k}: {base_tag}={a} vs {t2}={b} "
                             f"(seeded components must be identical across judges)")

    # coverage
    print("  COVERAGE")
    for tag in tags:
        row = "  ".join(f"{k}={present[(tag, k)]}" for k in ('cot', 'support', 'outcome'))
        mark = "" if all(present[(tag, k)] == len(eps) for k in ('cot', 'support', 'outcome')) \
               else "   <-- INCOMPLETE"
        print(f"    {tag:10} {row}{mark}")

    # 4 degeneracy + distributions
    print("\n  LABEL DISTRIBUTIONS (a single-value column carries no information)")
    for (tag, field), c in sorted(seen.items()):
        if not c:
            continue
        tot = sum(c.values())
        top, n = c.most_common(1)[0]
        if n == tot and tot > 20:
            fail(f"DEGENERATE {tag}.{field}: {top!r} for all {tot}")
        elif n / tot > 0.97 and tot > 20:
            warn(f"near-constant {tag}.{field}: {top!r} in {n}/{tot} ({100*n/tot:.0f}%)")
        dist = " ".join(f"{k}={v}" for k, v in c.most_common())
        print(f"    {tag:10} {field:26} {dist}")

    # 6 independence
    print("\n  INDEPENDENCE (identical payloads across judges would mean copied output)")
    for kind in ('cot', 'support', 'outcome'):
        for i, a in enumerate(tags):
            for b in tags[i + 1:]:
                A, B = payloads[(a, kind)], payloads[(b, kind)]
                both = set(A) & set(B)
                if not both:
                    continue
                # judge_model differs by construction; compare with it stripped
                same = sum(1 for k in both
                           if A[k].replace(J.model_for(a), '') == B[k].replace(J.model_for(b), ''))
                pct = 100 * same / len(both)
                if pct > 95:
                    fail(f"SUSPECT COPY {kind} {a} vs {b}: {same}/{len(both)} byte-identical")
                print(f"    {kind:8} {a:9} vs {b:9} identical {same}/{len(both)} ({pct:.1f}%)")

    # 7 residue
    residue = [p for d in runs_config.flat(wave)
               for p in glob.glob(os.path.join(d, '*', 'scoring', '**', '*.part'), recursive=True)
               + glob.glob(os.path.join(d, '*', 'scoring', '**', '*.tmp'), recursive=True)]
    print(f"\n  RESIDUE  interrupted-write leftovers: {len(residue)}")
    for r in residue[:5]:
        fail(f"RESIDUE {r}")

    print("\n" + "=" * 70)
    for w in WARNS:
        print(f"  WARN  {w}")
    for f_ in FAILS[:40]:
        print(f"  FAIL  {f_}")
    if len(FAILS) > 40:
        print(f"  ... and {len(FAILS) - 40} more failures")
    print(f"\n  {len(FAILS)} failures, {len(WARNS)} warnings -> "
          f"{'AUDIT PASSED' if not FAILS else 'AUDIT FAILED'}")
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
