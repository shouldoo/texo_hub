# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The full-text search shared by the notes, the lessons, the documents and the episodes.

The ranking needs the tsvector operators, which the ORM cannot express: the ids come
from SQL and the records go through the ORM afterwards, so the access rules apply. The
words are reduced to letters, digits and underscores, with the dots, slashes and at signs
that join them as the parser of PostgreSQL does (WORD), before they reach to_tsquery, so
a query can never carry its operators.

The access rules are in the query too: the ORM gives the sub-query of the ids the user
may read (model._search(domain), the record rules included), and SQL ranks only those.
Without it the best candidates could all be records of other customers and the window
had to grow past them; with it the first window holds readable rows only, and the ORM
pass that follows is the second check, never the first. A failure of the access check
raises: a search never answers "nothing" for a permission it could not read.
"""
import re

from odoo.tools import SQL

CONFIGS = ('simple', 'italian', 'english')
# A word of the query as the PostgreSQL parser cuts the text: an act number (106/2020), a date (07/11/2026),
# an abbreviation (D.Lgs), a version or an amount (17.0, 9.000) and an address stay one word, since the
# tsvector holds them whole; split on the dot or the slash they matched nothing, and a question made of an act
# number never held all its words. Only letters, digits, underscores, dots, slashes and at signs: never an
# operator of to_tsquery.
WORD = re.compile(r'[\w.]+@\w+(?:\.\w+)+|\w+(?:[./]\w+)+|\w+')
# Below this rank a hit matched only some of the words, in a long text: noise.
MIN_SCORE = 0.01
# A word this long or longer also matches as a prefix: «migraz» finds «migrazione».
PREFIX_LEN = 4
MAX_WORDS = 12


def words(query, related_terms=None):
    """The distinct words of the query and of the related terms, at most MAX_WORDS."""
    text = " ".join([query or ''] + list(related_terms or []))
    return list(dict.fromkeys(w.lower() for w in WORD.findall(text) if len(w) > 1))[:MAX_WORDS]


def _group(word):
    """One word in every configuration, as a prefix when it is long enough."""
    term = f"{word}:*" if len(word) >= PREFIX_LEN else word
    return SQL("(%s)", SQL(" || ").join(SQL("to_tsquery(%s::regconfig, %s)", config, term) for config in CONFIGS))


def readable_ids(model, domain=()):
    """The sub-query of the ids of model the user may read that match the domain (the ORM
    applies the record rules), or None when the query is known to give nothing."""
    query = model._search(list(domain))
    return None if query.is_empty() else query.subselect()


def rank(cr, table, vector, word_list, limit, where="TRUE", readable=None, readable_column='id'):
    """{id: (holds every word, rank)} of the rows of table whose vector matches: first the
    rows that hold every word; only to fill the limit, those that hold some, above
    MIN_SCORE; at most limit rows per pass. table, vector, where and readable_column are SQL
    written by the caller, never user input; readable, when given, is the sub-query of the
    ids the user may read (readable_ids), joined on readable_column."""
    if not word_list:
        return {}
    groups = [_group(w) for w in word_list]
    conditions = [SQL(where) if isinstance(where, str) else where]
    if readable is not None:
        conditions.append(SQL("%s IN %s", SQL.identifier(readable_column), readable))
    ranked = {}
    for operator in (" && ", " || "):
        tsquery = SQL(operator).join(groups)
        cr.execute(SQL(
            "SELECT id, ts_rank(%s, (%s)) FROM %s WHERE %s AND %s @@ (%s) ORDER BY 2 DESC, id DESC LIMIT %s",
            SQL.identifier(vector), tsquery, SQL.identifier(table), SQL(" AND ").join(conditions),
            SQL.identifier(vector), tsquery, int(limit)))
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

    SQL ranks the readable candidates (readable_ids in the query), the ORM then reads them
    as the user: when the two disagree (a rule that SQL could not express), the window grows
    until limit readable records are found or nothing more matches."""
    return search_ranked(model, lambda window, readable: rank(model.env.cr, table, vector, word_list, window, where,
                                                              readable), limit, domain, cap)


def search_ranked(model, ranker, limit, domain=(), cap=400):
    """search, with the ranking given by ranker(window, readable) -> {id: (holds every word, rank)}."""
    # the vectors are read by SQL: the pending writes of the ORM go first
    model.flush_model()
    readable = readable_ids(model, domain)
    if readable is None:
        return model.browse(), {}
    window = limit * 3
    while True:
        ranked = ranker(window, readable)
        records = model.search([('id', 'in', list(ranked))] + list(domain)) if ranked else model.browse()
        records = records.sorted(key=lambda r: order(ranked, r))
        if len(records) >= limit or len(ranked) < window or window >= cap:
            return records[:limit], ranked
        window *= 4
