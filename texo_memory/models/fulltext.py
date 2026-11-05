# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The full-text search shared by the lessons and the documents.

The ranking needs the tsvector operators, which the ORM cannot express: the ids come
from SQL and the records go through the ORM afterwards, so the access rules apply. The
words are reduced to letters, digits and underscores before they reach to_tsquery, so a
query can never carry its operators.
"""
import re

CONFIGS = ('simple', 'italian', 'english')
# Below this rank a hit matched only some of the words, in a long text: noise.
MIN_SCORE = 0.01
# A word this long or longer also matches as a prefix: «migraz» finds «migrazione».
PREFIX_LEN = 4
MAX_WORDS = 12


def words(query, related_terms=None):
    """The distinct words of the query and of the related terms, at most MAX_WORDS."""
    text = " ".join([query or ''] + list(related_terms or []))
    return list(dict.fromkeys(w.lower() for w in re.findall(r'\w+', text) if len(w) > 1))[:MAX_WORDS]


def _group(word):
    """One word in every configuration, as a prefix when it is long enough."""
    term = f"{word}:*" if len(word) >= PREFIX_LEN else word
    return "(" + " || ".join(f"to_tsquery('{config}', %s)" for config in CONFIGS) + ")", [term] * len(CONFIGS)


def rank(cr, table, vector, word_list, limit, where="TRUE"):
    """{id: (holds every word, rank)} of the rows of table whose vector matches: first the
    rows that hold every word; only to fill the limit, those that hold some, above
    MIN_SCORE; at most limit rows per pass. table, vector and where are SQL written by the
    caller, never user input."""
    if not word_list:
        return {}
    groups = [_group(w) for w in word_list]
    params = [p for _, group_params in groups for p in group_params]
    ranked = {}
    for operator in (" && ", " || "):
        tsquery = operator.join(sql for sql, _ in groups)
        cr.execute(
            f"SELECT id, ts_rank({vector}, ({tsquery})) FROM {table} "
            f"WHERE {where} AND {vector} @@ ({tsquery}) ORDER BY 2 DESC, id DESC LIMIT %s",
            params + params + [limit])
        for row_id, score in cr.fetchall():
            if row_id not in ranked and (operator == " && " or score >= MIN_SCORE):
                ranked[row_id] = (operator == " && ", score)
        if len(ranked) >= limit or len(word_list) == 1:
            break
    return ranked


def order(ranked, record):
    """Sort key: the rows with every word first, then by rank, the newer first."""
    every, score = ranked[record.id]
    return (not every, -score, -record.id)


def fields(ranked, record_id):
    """What a search entry says of its rank: score (the ts_rank, rounded) and words, all or
    some. A ranking of another search (every is None) gives its score as it is, and no words."""
    every, score = ranked[record_id]
    if every is None:
        return {'score': score}
    return {'score': round(score, 3), 'words': 'all' if every else 'some'}


def search(model, table, vector, word_list, limit, domain=(), where="TRUE", cap=400):
    """The records of model the user may read that match, in order, at most limit.

    SQL ranks the candidates without the access rules, the ORM keeps those the user may
    read: when the best candidates are not readable (the facts of other customers), the
    window grows until limit readable records are found or nothing more matches."""
    return search_ranked(model, lambda window: rank(model.env.cr, table, vector, word_list, window, where), limit,
                         domain, cap)


def search_ranked(model, ranker, limit, domain=(), cap=400):
    """search, with the ranking given by ranker(window) -> {id: (holds every word, rank)}."""
    # the vectors are read by SQL: the pending writes of the ORM go first
    model.flush_model()
    window = limit * 3
    while True:
        ranked = ranker(window)
        records = model.search([('id', 'in', list(ranked))] + list(domain)) if ranked else model.browse()
        records = records.sorted(key=lambda r: order(ranked, r))
        if len(records) >= limit or len(ranked) < window or window >= cap:
            return records[:limit], ranked
        window *= 4
