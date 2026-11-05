# Texo

Odoo 20.0 · LGPL-3

Makes Odoo the identity provider and the configuration of Texo: people, hub roles, personal hub tokens
and what the CLI mounts live in Odoo, and every agent route of the hub modules runs as the person behind the token.

## How it works

| Piece | What it does |
|---|---|
| API key scope `texo` | Added to the standard *New API Key* wizard. A key with this scope opens only routes declared with `bearer_scope='texo'`: `/json/2` and XML-RPC refuse it. |
| Token rules | A hub token always has an expiration date, at most `texo.token_max_days` days (system parameter, default 90), administrators included. Only users with a hub role can create one. |
| Privilege *Texo* | Groups Member, Lead and Administrator (each implies the previous one). The highest one is the hub role. |
| `POST /texo/v1/whoami` | Called by the agent's client with the user's token as bearer. Odoo checks scope, expiry and active user, then returns `uid`, `login`, `name` and `role`. Returns 401 for an invalid token and 403 for a user without a hub role. |
| Last seen | `res.users.texo_last_seen` is updated by `whoami`, with a resolution of one minute. |
| Users > Texo Tokens | Menu for hub administrators: every hub token with owner, creation date, expiry and last use. |

A user creates a token from *My Preferences > Security > New API Key*, scope *Texo*.
Disabling the user or deleting the key revokes it at once: every route checks the token on each
call.

## Generic read-only access for agents

Free questions on the ERP without a generic MCP server and without an `rpc` key: the agent
writes the query, Odoo runs it as the user behind the hub token.

| Route (`POST`, bearer = hub token) | Parameters | Returns |
|---|---|---|
| `/texo/v1/search_read` | `model`, `domain`, `fields`, `limit` (default 20, max 100), `offset`, `order` | `records`, `count`, `has_more` |
| `/texo/v1/read_group` | `model`, `domain`, `groupby`, `aggregates` (default `__count`), `limit`, `order` | `groups`, `has_more` |
| `/texo/v1/fields` | `model`, `query` | readable fields: name, type, label, relation |
| `/texo/v1/models` | `query` (3+ characters) | readable models matching the query |

Guarantees:
- the routes are declared `readonly`: Odoo serves them on a read-only cursor, nothing can be written;
- they run as the user: ACLs, record rules and multi-company rules apply;
- technical and security models are refused (`ir.*`, `res.users.apikeys`, `res.config*`, ...);
- binary fields and credential-like fields (`password`, `*_token`, `*_key`, `secret`, ...) are never
  returned and cannot be used in a domain;
- HTML is returned as plain text, long texts are truncated, x2many lists are capped at 20 ids;
- without `fields`, only `id` and `display_name` are returned: ask for the fields you need.

Task, ticket and chatter routes live in companion modules (`texo_project`).

## The configuration of the organisation

What the `texo` CLI mounts on the machine of every person of the organisation lives here, never in a repository:

| Model | What |
|---|---|
| `texo.pack` | the skill packs of the marketplace the organisation installs, each at a version (`odoo_partner`, `v1.0.0`) |
| `texo.thread` | the threads it mounts next to the memory: id, type (`source`, `tool`, `connector`), driver, `data_class`, `writes`, guide, and the settings of the driver as a JSON object |
| `res.company.texo_slug` | the name of the organisation for the CLI: its credentials file is `~/.config/texo/<slug>.env` (empty: derived from the name of the company) |

A credential is never stored: a thread names it as `env:NAME` and the person keeps its value on the machine; a
value in its place is refused. Administrators edit both lists in *Settings > Users* (*Texo Skill Packs*, *Texo
Threads*) or through the route `admin/config`.

| Route (`POST /texo/v1/...`) | Who | Parameters | Returns |
|---|---|---|---|
| `config` | every role | `company_id` (optional) | `organisation` (the slug), `company`, `packs` (`name`, `version`), `threads` (each as a `[[thread]]` of `texo.toml`) |
| `admin/config` | administrators | `packs`, `threads` (the full lists; one left out is not touched), `slug`, `company_id`, `apply` (default false) | every pack and thread `created`, `updated` (with `changes`), `unchanged` or `archived` (left out of the list: never deleted), and the counts; written only with `apply` |

## Client configuration

A client needs three values, kept in a file of the person outside any repository (mode 600):

| Variable | Value |
|---|---|
| `ODOO_URL` | URL of this Odoo |
| `ODOO_DB` | the database, when the server serves more than one |
| `TEXO_TOKEN` | the personal hub token |

## Endpoint example

```bash
curl -X POST https://<odoo>/texo/v1/whoami \
  -H "Authorization: Bearer <hub token>" -H "Content-Type: application/json" -d '{}'
# {"uid": 7, "login": "jdoe", "name": "John Doe", "role": "member"}
```

## Tests

```bash
odoo -c <conf> -d test_cohub20 -i texo --test-tags /texo --stop-after-init --http-port 18069
```

## Changelog

### 20.0.1.1.0

- The configuration of the organisation for the texo CLI: skill packs and threads, the slug of the organisation,
  the routes `config` and `admin/config`, the menus for administrators.

### 20.0.1.0.0

- First release in Texo.

## Author

Daniele Lucarelli
