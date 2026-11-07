# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The fusion of the lexical and the semantic results: reciprocal rank fusion.

Each list contributes weight / (K + rank) to every entry it holds; an entry in both lists adds
the two. RRF needs no comparable scores (a ts_rank and a cosine are not), and the measure
showed it loses none of the lexical hits: what the lexical search found stays in the top of
the fused list, what only the vectors found fills the rest.

The weights come from the measure on the evaluation sets of the demo customers. With the usual K = 60 and
equal weights the hybrid closed fewer paraphrases than the vectors alone (facts 9 of 14
against 11, episodes 19 of 20 against 20): the lexical hits of some words, the fill of the
lexical search, took the places of the vectors. K = 10 with the vectors weighing twice the
words gives the hybrid the hits of the vectors on the paraphrases (11, 14 of 17 lessons, 20),
but a lexical hit of every word (a code, a name, an acronym: far from every vector) was then
pushed out of the top five by five weak vectors (the tenth vector, 2/20, beats the first
lexical hit, 1/11). So a lexical hit of every word weighs as a vector, and a hit of some
words half as much: the first two fill the top together, the third stays the fill. Measured
on two evaluation sets: 173 of 192 (lessons 16 of 17 paraphrases, episodes 20 of 20
with mrr 0.94), the seed set whole, no lexical hit lost.

A hit of some words then weighed half a hit of every word (0.5). The measure on the four demo sets of the
packs (689 questions, November 2026) showed that this fill still pushed down the paraphrases the vectors
put first, documents and facts above all: the hybrid had a lower mrr than the vectors alone on every set
(0.881 against 0.911 on average). At 0.25 a hit of some words lifts a vector hit by one place, no longer
by two: the mrr rises on every set (0.881 to 0.891 on average; the facts of odoo_partner asked with other
words from 0.64 to 0.77), one hit more in all, and the hit of every word keeps its place. Heavier vectors
gave more on these sets (0.91) but would push a code or an acronym, which only the words find, out of the
first five: the sets have no such question, and the rule above stays.
"""
import datetime

RRF_K = 10
WEIGHT_LEXICAL_ALL = 2.0
WEIGHT_LEXICAL_SOME = 0.25
WEIGHT_SEMANTIC = 2.0
ORDER = {'both': 0, 'lexical': 1, 'semantic': 2}
# the recency boost, off unless texo_vector.recency_boost says how much: a fused score is multiplied by
# 1 + boost * 0.5 ** (age in days / half-life), so a hit of today gains the whole boost, one of three
# months ago half of it; an entry without a date (updated) gains nothing. A tie-breaker between hits of
# neighbouring ranks: at a few percent a rank of the fusion is worth more than the boost, at the maximum
# (0.2) a hit of today may pass the one above it (Sim does the same, by rank)
HALF_LIFE_DAYS = 90
MAX_BOOST = 0.2


def weight(entry, match):
    if match == 'semantic':
        return WEIGHT_SEMANTIC
    return WEIGHT_LEXICAL_ALL if entry.get('words') == 'all' else WEIGHT_LEXICAL_SOME


def key(entry):
    """What identifies an entry across the two lists: its OKF concept id (facts/3, tasks/7)."""
    return entry.get('concept') or (entry.get('kind'), entry['id'])


def fuse(lexical, semantic, limit, k=RRF_K):
    """The entries of the two lists, fused and in order, at most limit: score is the fused
    score, match says which search found the entry (lexical, semantic, both), similarity is
    the cosine when the vectors found it, words (all, some) what the lexical search said,
    ranks the place of the entry in each list (the score is the sum of weight / (K + rank))."""
    fused = {}
    for entries, match in ((lexical, 'lexical'), (semantic, 'semantic')):
        for rank, entry in enumerate(entries, 1):
            found = fused.get(key(entry))
            if found is None:
                found = fused[key(entry)] = dict(entry, score=0.0, match=match)
            else:
                found['match'] = 'both'
                if match == 'semantic':
                    found['similarity'] = entry.get('similarity')
            found['score'] += weight(entry, match) / (k + rank)
            # the explanation of the fused score: the rank of the entry in each list that holds it
            found.setdefault('ranks', {})[match] = rank
    # at equal score: what both found, then the words (a hit of every word against the first
    # vector is a tie), then the vectors; the newer first among equals
    result = sorted(fused.values(), key=lambda e: (-e['score'], ORDER[e['match']], -e['id']))
    for entry in result:
        entry['score'] = round(entry['score'], 4)
    return result[:limit]


def recency_factor(entry, boost, today, half_life=HALF_LIFE_DAYS):
    """1 + boost * 0.5 ** (age / half_life) for an entry with a date (updated, YYYY-MM-DD or a datetime
    string); 1 without."""
    updated = (entry.get('updated') or '')[:10]
    try:
        age = (today - datetime.date.fromisoformat(updated)).days
    except ValueError:
        return 1.0
    return 1.0 + boost * 0.5 ** (max(age, 0) / half_life)


def with_recency(entries, boost, today):
    """The entries with their fused score multiplied by the recency factor, in the new order; the factor
    applied is written on the entry (recency). Nothing happens with a boost of zero."""
    boost = min(max(float(boost or 0), 0.0), MAX_BOOST)
    if not boost:
        return entries
    for entry in entries:
        factor = recency_factor(entry, boost, today)
        if factor != 1.0:
            entry['recency'] = round(factor, 4)
            entry['score'] = round(entry['score'] * factor, 4)
    return sorted(entries, key=lambda e: (-e['score'], ORDER.get(e.get('match'), 1), -e['id']))
