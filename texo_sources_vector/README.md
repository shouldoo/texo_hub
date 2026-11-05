# Texo - External Sources by Meaning

Odoo 20.0 · LGPL-3

The cards of the external sources ([`texo_sources`](../texo_sources/README.md)) in the search by
meaning of [`texo_vector`](../texo_vector/README.md). It installs itself where both are installed
(`auto_install`) and adds nothing to the interface.

A press clipping, a call for proposals or a statement is written by others and asked about in other words: «what
did the mayor say about the hospital?» against a card titled «Ospedale, il sindaco: tempi certi». The lexical search
of `texo_sources` (scope `sources`, and in `all`) finds the card by its words and labels; this module gives
it a vector, so the hybrid search finds it by meaning too.

- One vector per **active** card (chunk 0): the title, what it is about (public persons, bodies, places, themes,
  acts, keywords) and the abstract written by whoever filled it in. Never the text of the article: the memory does
  not keep it.
- A candidate, a card waiting for its approval or an archived card has no vector: the cron of the vectors drops it
  at the next run.
- The access rules of the cards apply: a card of a project is found only by who may read the project.

## Tests

```bash
odoo -d <test db> --db-filter '^<test db>$' -i texo_sources_vector --test-tags /texo_sources_vector \
  --http-interface=127.0.0.1 --stop-after-init
```

The embedding service is patched as in the tests of `texo_vector`; skipped without the extension `vector`.

## Changelog

### 20.0.1.0.0

- First release in Texo.
