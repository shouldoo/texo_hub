# Texo - External Sources

What others publish, in the memory of the organisation: the channels it follows, read on request, a triage of the
new links, and structured cards with the public persons, bodies, places, themes and dates they are about. For an
organisation that works on material written by others: a press review for a civic list, calls for proposals and
regulatory news for an association, legislation and tenders for a design studio.

## The models

| Model | What | Who writes it |
|---|---|---|
| `memory.source.channel` | who publishes: a newspaper, a broadcaster, a video channel, a public body, a portal of calls, a source of legislation; what to look for in it, how often to read it, the project it serves | leads (members read) |
| `memory.source.feed` | how a channel is read: an RSS or Atom feed, the feed of a video channel, a search feed, or a page to check by hand; the outcome of the last reading | leads |
| `memory.source.item` | a thing published: a candidate from a feed or a pasted link, then a card (abstract, short quotes, public persons, bodies, places, themes, acts, event date, stance, relevance, related cards, review date) | members triage and write; leads approve |
| `memory.source.segment` | a passage of a video card: start, end, speaker, summary, short quote | whoever watched the video |
| `memory.source.tag` | the labels of the cards: public persons, bodies, places, themes | members add; leads curate |

- **Read on request, never on a schedule.** «Read Now» on a channel (or the agent, when asked) reads its feeds and
  creates a candidate for every new link; the pages to check by hand are listed for the person. A reading never
  changes a card that exists: links are unique per organisation.
- **No text of others is kept.** A candidate holds title, link, date and channel; the summary of the feed is read
  only to match the words to look for. A card holds an abstract written by whoever fills it in and at most 600
  characters of quotes.
- **A public person is a label, not a contact.** Nobody becomes a partner of the organisation for being named.
- **Approval.** A card that names public persons waits for a lead («To Approve»); the others are active when
  written. An approved card is changed only by a lead, or sent back.
- **Review.** Every card has a review date (a year by default): at the weekly review it is confirmed or archived.
- **Access.** Channels and cards of the organisation are for every member of its companies; those of a project only
  for who may read the project.

## Using it in Odoo

Menu *Memory > External Sources*:

1. **Channels**: add the channels, their feeds and the words to look for; overdue channels are highlighted.
2. **Triage**: the candidates, by channel, those holding the watched words first; keep them with a theme and a line,
   or discard them.
3. **Cards**: list, kanban by state, calendar by event date (the chronology of a theme or a person), pivot and graph
   by theme, week and stance; the form has the content, the labels, the video segments and the related cards.
4. **To Approve**: the cards waiting for a lead.
5. **Source Labels** (leads, under *Configuration*): persons, bodies, places and themes of the organisation.

The queues of the sources are in *Memory > To Review*; a project shows the cards of its channels with a button.

Reading a feed is an HTTP request from the server to the address of the feed (http or https only, at most 5 MB,
20 s); external XML entities are never resolved.

## The cards in the search of the memory

The **active** cards are part of the search of the memory (`memory/search`, the tool `search`, *Search the Memory*):
scope `sources`, and in `all` with the rules, facts, procedures, documents and lessons. By their words: the title
weighs most, then what the card is about (public persons, bodies, places, themes, acts, keywords), then what it says
(abstract, quotes, note of the triage); a renamed label finds its cards by the new name. By their meaning where
`texo_vector` is installed, through `texo_sources_vector`. A candidate, a card waiting for its
approval or an archived card is not found there; `sources_find` searches all of them, by words and by filters
(period: the date of the event, or the day of publication when it is not known; person, theme, channel).

## The triage in the session of the agent

The same candidates, states and cards as in Odoo: the triage is one process with two interfaces. The
routes `/texo/v1/sources/*`, the tools `sources_*` of the MCP server (`texo_mcp`, shown only when this
module is installed) and the `sources-*` commands of the `texo` CLI:

| Tool | What |
|---|---|
| `sources_due` | the channels overdue; the context pack carries them too, with the candidates to sort and the cards to approve |
| `sources_find` | the cards and candidates already collected: words, public persons, themes, channel, period (event date, else publication day) |
| `sources_inbox` | the candidates to sort, the watched first, with the proposals |
| `sources_collect` | read the channels now, on request |
| `sources_search` | «search news about X»: what the memory has, then the channels asked now through their **search feeds with placeholder** (an address with `{q}` where the subject goes, e.g. `https://site/?s={q}&feed=rss2`) |
| `sources_link` | a pasted link becomes a candidate on the channel of its site |
| `sources_propose` | the agent's proposal kept on a candidate: action (keep, discard, check), themes, the card in short, **doubts** from a fixed list (event date uncertain, private person, who is it, opinion or unconfirmed, quote not verifiable, article not readable, duplicate, partisan source, unknown channel, video to watch), questions |
| `sources_triage` | the person's decision: keep, keep as proposed, discard |
| `sources_card` | the card, after the person's yes; **every quote is checked on the page, word for word** (read for the check, not kept) or the card is refused |
| `sources_channel` | a new channel (leads) |

In Odoo the triage shows the agent's proposal and its doubts, and **Keep as Proposed** applies it.

A member reads the channels without deciding them: the date and the outcome of a reading are written as the system.
The scheduled reading exists but is **off**: *Memory: read the overdue external source channels* in Scheduled
Actions, for an organisation that wants the candidates to arrive by themselves.

## Tests

```bash
odoo -d <test db> --db-filter '^<test db>$' -i texo_sources --test-tags /texo_sources \
  --http-interface=127.0.0.1 --stop-after-init
```

The feeds are patched: no network in the tests.

## Changelog

### 20.0.1.0.0

- First release in Texo.
