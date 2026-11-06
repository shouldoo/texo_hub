# texo_hub

Texo — workspace and memory for AI agents at work. This repository is the loom: the Odoo Community modules
that make a coordination Odoo the home of the memory of an organisation, whatever its sector: identity and
personal tokens, tasks and hours, rules for the agents with states and roles, client-free lessons, the
documents of the memory as attachments of the records they belong to, with the sources the rules cite. The
AI agents of the organisation reach it through its routes, as the person, with the person's own token. Built
for the `texo` CLI of [`texo_core`](https://github.com/shouldoo/texo_core), usable by any client that speaks
HTTP. What a sector adds (activities, sections, rules, project templates) comes from the seed of a skill pack of
[`texo_marketplace`](https://github.com/shouldoo/texo_marketplace), not from these modules.

| Module | Purpose | Depends on |
|---|---|---|
| [`texo`](texo/README.md) | Identity: personal tokens as API keys with a dedicated scope, hub roles as Odoo groups, `whoami`; generic read-only routes on the ERP (`search_read`, `read_group`, `fields`, `models`) | `base` |
| [`texo_project`](texo_project/README.md) | Agent routes on projects: my open tasks, task context with chatter and milestone, internal note; the project with its description, milestones and last update as its present, and a new update | `texo`, `project` |
| [`texo_memory`](texo_memory/README.md) | Working memory: what it knows of the organisation (the company), a customer, a project or a task, as notes of three kinds in sections: rules an agent follows (those of the organisation open every session), with state and review by role, facts and procedures; the documents of the memory as attachments of their records (files or links), with the converted text; client-free lessons and findings that survive a customer's opt-out; leak filter; context pack, search, review, rules, lesson and state routes; opt-out wizard; weekly housekeeping | `texo_project` |
| [`texo_timesheet`](texo_timesheet/README.md) | Hours on a task from an agent, as the person who gives them; worklog and hours in the task context | `texo_project`, `hr_timesheet` |
| [`texo_mcp`](texo_mcp/README.md) | The memory as a remote MCP server: `POST /texo/mcp` with the person's token or through OAuth 2.1 (discovery, dynamic registration, consent, PKCE), the rules of the session as instructions, the tools of the routes with the same checks, a write after `confirm` | `texo_memory` |
| [`texo_vector`](texo_vector/README.md) | Optional. Vectors for the memory (pgvector, a local embedding service): the search by meaning over the episodes, the facts, the procedures, the lessons and the documents, fused with the lexical one (`mode` lexical, semantic, hybrid); the near-duplicate lessons by meaning; never the rules; no text leaves the machine without an opt-in | `texo_memory` |
| [`texo_sources`](texo_sources/README.md) | Optional. External sources: the channels the organisation follows (newspapers, video channels, public bodies, calls, legislation), read on request, a triage of the new links, structured cards with public persons, bodies, places, themes and event dates, approval of the cards that name persons; no text of others is kept; the active cards in the search of the memory (scope `sources`) | `texo_memory` |
| [`texo_sources_vector`](texo_sources_vector/README.md) | Installs itself with the two modules it joins. The cards of the external sources in the search by meaning: a vector on the title, the labels and the abstract of every active card | `texo_sources`, `texo_vector` |

The memory is read back named as [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
(OKF v0.2): every record a concept (`rules/12`, `facts/3`, `projects/2`) with its type, status, provenance and
trust, the context pack an `index.md`, the updates of a project and the chatter of a task a `log.md`; the
native fields of Odoo keep their names (`texo/okf.py`, [`texo_memory`](texo_memory/README.md#open-knowledge-format)).

Every agent route is `POST /texo/v1/...` with the user's hub token as bearer and runs as that
user: ACLs, record rules and the chatter audit are Odoo's. The routes are the whole interface: a token as
bearer, JSON in, JSON out. Everything runs on Odoo Community.

Branch `20.0`, Odoo 20.0, PostgreSQL 16 or later. License LGPL-3.

## Installation from a release

The modules are installed as a released artifact: a deploy that needs them installs a version of this
branch and never forks it (a need of one context becomes a module of that context that inherits these,
and comes back here as a pull request when it is general). A version is a tag of `20.0` or, in its
absence, the commit recorded by the installing deploy.

What the instance needs:

| Piece | Value |
|---|---|
| Image | `odoo:20.0` with the Python package `markdown2` added (without it the `mail` module logs a warning at every start; the CI of this repository installs it the same way) |
| Database | PostgreSQL 16 or later (`odoo/release.py`, `MIN_PG_VERSION`); for `texo_vector`, with the extension [pgvector](https://github.com/pgvector/pgvector) (the image `pgvector/pgvector:pg17`, as in the CI) |
| Addons path | this repository mounted read-only next to the core addons |
| Modules | `texo`, `texo_project`, `texo_memory`, `texo_timesheet` (the last one pulls `hr_timesheet`), `texo_mcp`; `texo_vector` where the database has pgvector and a local embedding service runs next to Odoo (`texo_vector/README.md`) |
| Network | the HTTP port on loopback or behind TLS: the token travels as a bearer |

Minimal stack, one directory outside git:

```dockerfile
# Dockerfile
FROM odoo:20.0
USER root
RUN pip install --quiet --break-system-packages markdown2
USER odoo
```

```yaml
# docker-compose.yml (excerpt)
services:
  db:
    image: pgvector/pgvector:pg17      # postgres:17 without texo_vector
    environment: {POSTGRES_USER: odoo, POSTGRES_PASSWORD_FILE: /run/secrets/pg_password, POSTGRES_DB: postgres}
    secrets: [pg_password]
  tei:                                 # the embedding service of texo_vector, in the compose network only
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-latest
    command: ["--model-id", "BAAI/bge-m3", "--auto-truncate", "--max-batch-tokens", "2048", "--port", "80"]
    volumes: [tei-data:/data]
  web:
    build: .
    depends_on: [db]
    ports: ["127.0.0.1:8069:8069"]
    volumes:
      - ./odoo.conf:/etc/odoo/odoo.conf:ro
      - /path/to/texo_hub:/mnt/modules/texo_hub:ro
      - filestore:/var/lib/odoo
    secrets: [pg_password]
```

`odoo.conf` carries `addons_path = /mnt/modules/texo_hub` (the core addons are found by the
image) and the database credentials; the file must be readable by the `odoo` user of the image (uid 100,
gid 101). Then, with a throw-away container:

```bash
C="docker compose -f /path/to/stack/docker-compose.yml"
ODOO="$C run --rm -T --no-deps --entrypoint odoo web"
$ODOO db -c /etc/odoo/odoo.conf init coord --country it --language it_IT
$ODOO -c /etc/odoo/odoo.conf -d coord \
  -i texo,texo_project,texo_memory,texo_timesheet,texo_mcp,texo_vector \
  --test-tags /texo,/texo_project,/texo_memory,/texo_timesheet,/texo_mcp,/texo_vector \
  --http-interface=127.0.0.1 --stop-after-init 2>&1 | tee install.log
checklog-odoo --no-echo install.log      # zero warnings, as in the CI
$C up -d
```

With `texo_vector`, name the embedding service once per database (Settings, Technical, System
Parameters, or the shell): `texo_vector.endpoint` = `http://tei:80`; the cron computes the vectors
within fifteen minutes, the search is lexical until then.

Updating to a newer version: pull the branch to the chosen commit, then `-u <changed modules>` with the
same test tags and the same `checklog-odoo` pass, and restart `web`. Migration scripts, when a version
carries them, run from the manifest version bump.

## Roles and tokens

| Step | Where |
|---|---|
| Give a person a hub role | *Settings > Users*, privilege *Texo*: Member, Lead or Administrator (each implies the previous). A user without a role gets 403 from every route |
| Create a personal token | the person, from *My Preferences > Security > New API Key*, scope *Texo*, at most `texo.token_max_days` days (default 90); shown once |
| Review the tokens | *Users > Texo Tokens* (administrators): owner, creation, expiry, last use |
| Revoke | delete the key or disable the user |

What the role decides in the memory: a Member's notes are drafts that a Lead reviews; a Lead's confirmed
notes may be active at once and only a Lead changes states; an Administrator also manages tokens and the
opt-out of a customer (`texo_memory/README.md`, «Roles»).

## The client

Any HTTP client works: a token as bearer, JSON in, JSON out. The reference client is
the `texo` CLI of [`texo_core`](https://github.com/shouldoo/texo_core) (command line and local MCP server
over stdio, standard library only), configured by the `texo.toml` of the customer repository. An MCP client reaches the same tools without
anything on the person's machine through the remote MCP server of `texo_mcp`
(`POST /texo/mcp`, the same token as bearer).

| Route family | Routes | Module |
|---|---|---|
| Identity | `whoami` | `texo` |
| Metrics | `GET /texo/metrics` (administrators, Prometheus text) | `texo` |
| Configuration of the organisation | `config`, `admin/config` (administrators) | `texo` |
| Read-only ERP | `search_read`, `read_group`, `fields`, `models` | `texo` |
| Project | `project/my_work`, `project/task`, `project/task_note` | `texo_project` |
| Memory | `memory/rules`, `memory/context`, `memory/search`, `memory/read`, `memory/note`, `memory/state`, `memory/review`, `memory/confirm` | `texo_memory` |
| Documents | `document/list`, `document/read`, `document/write`, `document/remove`, `document/attachment` | `texo_memory` |
| Seed of a pack | `admin/seed` (administrators) | `texo_memory` |
| Hours | `project/log_time` | `texo_timesheet` |
| MCP | `/texo/mcp` (JSON-RPC: `initialize`, `tools/list`, `tools/call`, `ping`) | `texo_mcp` |

Parameters and answers of each route: the README of its module. The same logic exists as methods on the
models (`_agent_*`), for an adapter that exposes it another way; `texo_mcp` is one, and calls
the controller methods of the routes.

## Extending

Extend by inheritance from a module of your own (`_inherit` on the models, new routes in a controller that
reuses `_texo_check_role`), never by editing these modules. Keep the guarantees: every route
runs as the user, writes to shared data ask for confirmation, a lesson never stores a customer. A change
useful to every context is welcome as a pull request on `20.0`: tests with the change, zero warnings in
the log.

## Checks

The workflow `tests` (`.github/workflows/tests.yml`) installs every module on the official
`odoo:20.0` image with PostgreSQL 17, runs their tests and then `checklog-odoo` on the log: a `WARNING`
fails the build like a failed test. Tests that expect a refusal from a route mute `odoo.http`, which logs
every client error as a warning. Each module keeps its own changelog under its manifest version.
