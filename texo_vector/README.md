# Texo - Vector

Vectors for the memory of [`texo_memory`](../texo_memory/README.md): a search by meaning
over the episodes, the facts, the procedures, the lessons and the documents, fused with the lexical search, and the near-duplicate lessons
of the housekeeping found by meaning. The vectors live in one table of the database (pgvector), the
embeddings come from a local service: no text of the memory leaves the machine unless the administrator
opts in.

Optional: without it the hub is lexical, as before. With it installed but without the extension `vector`
on the database, or without an endpoint, the hub is still lexical and says so in the log.

## What gets a vector, and what does not

| Memory | Vector | Why |
|---|---|---|
| Episodes (`project.task` of a project: the title and the description, then each human message of the chatter, one vector each) | yes | «has something like this happened before?» is asked with other words than those of the chatter; the measure on the test set went from 17 to 19 hits in 20 paraphrased questions (phase D of the plan) |
| Facts (`memory.note`, kind `fact`, active) | yes | the paraphrased questions went from 4 to 9 hits in 14 |
| Lessons (`memory.lesson`, draft or active) | yes, for the near-duplicates and available to the search | the search gained little (11 to 13 in 17, under the threshold set beforehand); the three near-duplicate pairs written on purpose in the test set are the closest pairs by cosine where `difflib` sees two different texts |
| Rules | never | a rule reaches the agent by chain, in the context pack; it is not something to find by meaning |
| Procedures (`memory.note`, kind `procedure`, active) | yes, since 20.0.1.1.0 | like the facts: title, keywords, text; on the seed of a demo customer the lexical search closed them, the scenarios of the workspace (associations, design studios, political lists) test them where the writing is less disciplined |
| Documents (`ir.attachment` of the memory) | yes, since 20.0.1.1.0: the title, summary and keywords (chunk 0), then, since 20.0.1.3.0, each passage of the converted text cut by its structure (`texo_memory`, `memory.document.passage`: chunk = its sequence, up to 400), with the title of the document and the path of the passage before it, when the document keeps its text | a press clipping, a call for proposals or a regulation is written by others, not for the search; a sensitive document (no text kept) gets the vector of its summary only |

A rule, a to-do without a project, an archived task, a superseded fact: no vector, or the vector is dropped at
the next run of the cron.

## The search

`memory/search` (and the `search` tool of the MCP server) takes `mode`:

| `mode` | What it does |
|---|---|
| `lexical` | the words, as `texo_memory` does: every word first, then some, prefixes, Italian and English stems |
| `semantic` | the records nearest to the question by cosine among those the person may read; `score` is the similarity |
| `hybrid` | both, fused by reciprocal rank (`models/hybrid.py`, K = 10): a vector and a lexical hit of every word of the question (a code, a name, an acronym) weigh 2, a lexical hit of some words, the fill of the lexical search, weighs 0.5. The values that, on the two sets of the workspace, give the hybrid the paraphrases the vectors find (facts 11 of 14, lessons 16 of 17, episodes 20 of 20) without losing one hit of the words; `score` is the fused rank |

Without `mode` the configured one applies (`texo_vector.mode`, `hybrid` by default). Every hit of a
semantic or hybrid search says which search found it (`match`: `lexical`, `semantic`, `both`) and its
`similarity` when the vectors did; a hit of the words says, as in the lexical search, whether it holds every
word of the question or some (`words`); a fused hit says its rank in each list (`ranks`: the score is the sum
of weight / (K + rank)). The scopes without vectors (`rules`, `notes`)
stay lexical whatever the mode; in `all` the facts and the lessons go by meaning too, the rules by their words.
The answer of the route says the `mode` used (`lexical` when the vectors were asked and the service did not
answer) and what the reranker did (`rerank`: `off`, `skipped`, `applied`, `unavailable`).

The access rules apply as in the lexical search, in the query: the nearest chunks come from SQL among the
records the person may read (the sub-query of their ids, given by the ORM with its record rules and the
domains of the lexical search: state, expiry, `applies_to`, a project for the episodes), at most 60 chunks
(200 for the documents), with the iterative scan of pgvector 0.8 (`hnsw.iterative_scan = relaxed_order`) so
the filter does not leave the query with fewer candidates than asked; the records then go through the ORM
as the person, the second check. The question is embedded by the same service; when the service does not
answer (within 10 s) the search is lexical and the log says so once per call.

## The reranker (optional)

A cross-encoder reads the question and each of the first results of the hybrid search together and puts them
in a new order (`models/memory_rerank.py`). It finds nothing new: it reorders what the search found. **Off**
until `texo_vector.rerank_endpoint` names a service:

| Parameter | Default | What |
|---|---|---|
| `rerank_endpoint` | empty (off) | the service; a host outside the local network only with `allow_remote_endpoint` |
| `rerank_api` | `tei` | `tei`: Text Embeddings Inference, `POST /rerank` (the `tei-rerank` service of the stack, profile `rerank`); `llamacpp`: llama.cpp server with `--reranking`, `POST /v1/rerank`, for AMD and Intel GPUs through Vulkan (`rerank_model` names its model if it serves several) |
| `rerank_pool` | 10 | how many of the first results it reorders (2 to 20) |
| `rerank_chars` | 800 | characters of each result it reads: the title and the text; for a document the passage chosen for the hit |
| `rerank_timeout` | 5 | seconds; past them the hybrid order stays and the log says why |

Only the hybrid mode is reranked; each reordered hit carries its score (`rerank`), and the answer of the search
says what happened: `applied`; `skipped` (a lexical or semantic search, or fewer than two results); `unavailable`
(named but refused outside the local network, or no answer in time: the hybrid order stays). Measured with
`BAAI/bge-reranker-v2-m3` on 40 questions whose answer is one passage of a long act (an evaluation set of a demo customer):
on a design studio the right document goes first more often (mrr 0.86 to 0.97 with 10 results of 800
characters, to 1.00 with 20 of 2000), on an association whose hybrid was right already nothing changes (0.96 to
0.94); the passage named first is the same. On a CPU it costs **7 s per search** (30 s with 20 long results):
turn it on where an accelerator serves it.

## The vectors

- `memory.embedding`: one row per chunk (`res_model`, `res_id`, `chunk`: 0 for the record, the message id
  for a message of the chatter), with the model that computed it and the SHA-256 of the text. The column
  `embedding vector(n)` and its HNSW index (cosine) are created by `init()`, as the `tsvector` columns of
  the memory are; `n` is `texo_vector.dimensions`. A change of dimensions drops the column and every
  vector: the cron computes them again. Administrators read the table; everything else is done by the module.
- **What changed, not the whole memory.** A write on a record of the scope (a task; a message of its chatter;
  a fact or a procedure; a lesson; a document, its passages cut again) marks the record pending
  (`memory.embedding.pending`: the hooks of `models/scope_hooks.py`, on the fields the texts are made of and
  the scope is decided by; a deletion too). The cron reads the texts of the pending records only, computes the
  vectors missing or whose text changed and drops those of the chunks gone, and a record whose chunks are all
  stored is no longer pending: a run costs what changed. A weekly cron, **reconciliation of the vectors with
  the memory** (`_cron_reconcile()`), walks the whole scope and marks pending what the writes may have missed
  (a text changed by SQL, a row of a record gone); it computes nothing. The install, a change of model and a
  change of dimensions mark every record of the scope.
- **queue_job, optional.** Where the OCA module `queue_job` is installed, a write also asks for one job that
  works off the pending records at once (`_schedule_now()`: identity key `texo_vector.embed_pending`, so one
  such job waits at a time, however many writes ask); a queue that refuses is logged and the cron does it within
  fifteen minutes. Without `queue_job` nothing changes: the cron alone.
- The cron **Memory: vectors of the episodes, the facts and the lessons** (`_cron_embed()`, every 15 minutes,
  at most 2,000 chunks per run) computes the vectors missing, those whose text or model changed, and drops
  those of the chunks that left the scope. A new fact is found by its words at once and by meaning after the
  next run. Nothing is written when the service does not answer: the chunks wait.
- The texts: a task is `title`, `description` (plain text); a message its body; a fact `title`, `keywords`,
  `body`; a lesson `title`, `keywords`, `finding`, `solution`. At most 6,000 characters each; whitespace folded.

## The embedding service

[Text Embeddings Inference](https://github.com/huggingface/text-embeddings-inference) in CPU, or any
service with its `POST /embed` (`{"inputs": [...], "truncate": true}` in, a list of vectors out); or
[llama.cpp server](https://github.com/ggml-org/llama.cpp) started with `--embedding` and the pooling of the model
(`--pooling cls` for bge-m3), `POST /v1/embeddings`, which runs on the AMD and Intel GPUs that TEI does not support,
through Vulkan. Named in `ir.config_parameter`:

| Parameter | Default | Meaning |
|---|---|---|
| `texo_vector.endpoint` | none | the URL of the service; `http://tei:80` in the coordination stack of `texo_core`. Without it nothing is computed and the search is lexical |
| `texo_vector.api` | `tei` | `tei`: `POST /embed`; `llamacpp`: `POST /v1/embeddings` (`{"input": [...]}` in, `data[].embedding` out). The texts are cut at 6000 characters: start llama.cpp with a context of at least 8192 tokens (`-c 8192 -b 8192 -ub 8192`), since it refuses an input longer than its batch |
| `texo_vector.model` | `BAAI/bge-m3` | the model the service runs; `intfloat/multilingual-e5-small` is the light alternative (one tenth of the memory, a little weaker); the e5 family gets its `query:` and `passage:` prefixes |
| `texo_vector.dimensions` | `1024` | the size of its vectors (`384` for e5-small) |
| `texo_vector.mode` | `hybrid` | the mode of a search that gives none |
| `texo_vector.duplicate_similarity` | `0.80` | two lessons at least this close are near-duplicates for the housekeeping (`0.93` with e5-small, whose unrelated pairs sit above 0.8) |
| `texo_vector.allow_remote_endpoint` | `False` | an endpoint outside the local network (a public name or address) is refused, with a warning, unless this is `True` |

The texts of clients and projects are what gets embedded: the endpoint is an outgoing call, declared here and
limited to the local network (loopback, private or link-local addresses, a name without a domain such as a
compose service, `.localhost`, `.local`, `.internal`, `.lan`) unless the administrator opts in per database.
Changing the model: set `model` and `dimensions`, then update the module or wait for the cron; the vectors
are computed again (the first run after a change is the long one: a few seconds per hundred chunks in CPU
with bge-m3).

## Housekeeping

`memory.lesson._duplicate_pairs()` (the weekly housekeeping and the review queue) gives the pairs of live
lessons about the same thing (a tag in common, or both without tags) whose vectors are at least
`duplicate_similarity` close, the ratio in percent; a lesson without a vector yet is compared by `difflib`
with the others, as before. The activities to the leads and the rest of the housekeeping do not change:
nothing is merged on its own.

## State of the search

Menu *Memory > Configuration > State of the Search* (administrators): whether the vectors are available, the
mode, the model and the service, how many texts of each kind have their vector and how many wait for it, when
the cron last ran and runs next. **Compute Now** asks the cron to run as soon as a worker is free. A count of
waiting texts that does not go down is a service that does not answer or a cron that does not run. With this
module the page *Search the Memory* also offers the search by meaning.

## Tests

```bash
odoo -c <conf> -d test_cohub20 -i texo_vector --test-tags /texo_vector --http-interface=127.0.0.1 --stop-after-init
```

The tests run with a fake embedding service (seven dimensions, one per concept the texts of the tests talk about,
so that «restituzioni» lands next to «resi» without any word in common): the cron that computes, recomputes
and drops the vectors (a message is a chunk of its own, a rule never gets one, a to-do is not an episode,
another model recomputes everything); the hybrid search that finds a paraphrase and keeps the lexical hits,
the semantic mode, the configured mode, the scopes that stay lexical, a wrong mode refused; only what the
person may read; the service down (lexical, the chunks wait) and a service answering with vectors of another
size; the API of llama.cpp (the vectors in the order of their index, an error answer); a remote endpoint refused without the opt-in, the local hosts; the dimensions that follow the model;
the near-duplicates by meaning, by tag, and by `difflib` for a lesson without a vector; the route with
`mode`; and, with the extension made unavailable on purpose, the search, the cron and the housekeeping as
they were. Where the extension `vector` is missing the tests with vectors are skipped; the CI runs on
`pgvector/pgvector:pg17`.

## Changelog

### 20.0.1.3.0

- The vectors follow the writes: a record of the scope that changes is marked pending and the cron reads the
  pending records only (before, every run read the texts of the whole memory); a weekly reconciliation marks
  what the writes missed; where `queue_job` is installed a write asks for one job at once.
- The state of the search and the metrics count the chunks with a vector and the records waiting.

### 20.0.1.2.0

- The answer of the search says the mode used and what the reranker did (`applied`, `skipped`,
  `unavailable`); a fused hit says its rank in each list (`ranks`).
- The gauges of the vectors in `GET /texo/metrics`: available, services named, texts with and without their
  vector by kind, the cron.
- The access rules are in the query of the nearest chunks (the sub-query of the readable ids), with the
  iterative scan of pgvector 0.8: the candidates are readable records, not the nearest of everyone's.

### 20.0.1.1.0

- The embedding service may be llama.cpp server (`texo_vector.api` = `llamacpp`, `POST /v1/embeddings`): the
  vectors on an AMD or Intel GPU through Vulkan.

### 20.0.1.0.1

- Without an embedding service the cron reports no work: no warning of `ir.cron` at every run.

### 20.0.1.0.0

- First release in Texo.

## Author

Daniele Lucarelli, 2026. LGPL-3.
