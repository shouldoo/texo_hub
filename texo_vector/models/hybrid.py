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
"""
RRF_K = 10
WEIGHT_LEXICAL_ALL = 2.0
WEIGHT_LEXICAL_SOME = 0.5
WEIGHT_SEMANTIC = 2.0
ORDER = {'both': 0, 'lexical': 1, 'semantic': 2}


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
    the cosine when the vectors found it, words (all, some) what the lexical search said."""
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
    # at equal score: what both found, then the words (a hit of every word against the first
    # vector is a tie), then the vectors; the newer first among equals
    result = sorted(fused.values(), key=lambda e: (-e['score'], ORDER[e['match']], -e['id']))
    for entry in result:
        entry['score'] = round(entry['score'], 4)
    return result[:limit]
