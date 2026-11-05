# Texo - MCP

Odoo 20.0 · LGPL-3

The memory of Texo as a **remote MCP server**: any MCP client that speaks Streamable HTTP
reaches the same tools as the local client of `texo_core` (`texo mcp`, over stdio), with
nothing installed on the person's machine.

## The endpoint

`POST /texo/mcp`, one JSON-RPC 2.0 message per request, a JSON answer (no streams, no
sessions), with a Texo token as bearer: a personal one (Odoo, Preferences, Security, New API
Key, scope Texo), or the access token a client got through OAuth (below). The tools run as the
person, with Odoo's access rights and record rules. Without a valid token the answer is `401` with
`WWW-Authenticate: Bearer resource_metadata="…"`, which tells a client where to start OAuth. A token
whose user has no hub role gets the error `-32001`; a notification gets `202`; batches are refused.

| Method | Answer |
|---|---|
| `initialize` | the server and its **instructions**: the rules of the session (`memory/rules`: the common rules, the active rules of the organisation with their severity, the role, the activities) |
| `tools/list` | the tools below |
| `tools/call` | the answer of the route, as JSON text, or, asked with `format: okf`, the files of the OKF bundle as markdown, each after a `<!-- okf: path -->` line; a refusal of the route (no access, a leak, a wrong argument) comes back as a result with `isError`, and what the call wrote is rolled back |
| `ping` | `{}` |

## Tools

Each tool calls the controller method of its route, so the two give the same answers and make the
same checks: `whoami`, `rules`, `my_work`, `task`, `task_note`, `context`, `search`, `read`, `note` (a rule,
a fact or a procedure), `note_append`, `note_update`, `fact`, `fact_append`, `fact_update` (aliases), `lesson`, `project`, `log`, `update`, `state`, `log_time` (with
`texo_timesheet`), `review`, `confirm`, `documents`, `document`, `document_write`, `document_remove`,
`query` (`search_read`). A write (`task_note`, `note`, `note_append`, `note_update`, `fact`, `fact_append`,
`fact_update`, `lesson`,
`update`, `state`, `log_time`, `confirm`, `document_write`, `document_remove`) needs `confirm: true`, after the person's yes; without it the answer says so and
nothing is written. The `texo` client keeps two tools of its own that need the person's
machine: the download of an attachment for the local conversion and the upload of a local file.
`search` takes `scope` (`tasks` for the episodes) and `mode` (`lexical`, `semantic`, `hybrid`: meaningful
where `texo_vector` is installed, lexical otherwise).

## OAuth

The hub is the OAuth 2.1 authorization server of its own endpoint, as the MCP authorization
specification asks, so a client connects with the URL alone (the connectors of claude.ai, Claude Code
without a header):

| Step | Where |
|---|---|
| Discovery | `/.well-known/oauth-protected-resource` (RFC 9728) and `/.well-known/oauth-authorization-server` (RFC 8414), also with the path of the endpoint appended |
| Registration of the client | `POST /texo/oauth/register` (RFC 7591): a public client, with its redirect addresses (https, or http on localhost) |
| Consent | `/texo/oauth/authorize`: the person logs in to Odoo and allows or denies the client, on a page that is never framed; only a person with a hub role can allow |
| Tokens | `POST /texo/oauth/token`: the code (one use, ten minutes, PKCE S256 required) for an access token and a refresh token; a refresh token works once and brings a new pair |

The access token is an API key of the hub scope that lasts one hour: the endpoint and the routes accept
it as any other token, and the hub checks the role of the person at every issue. The refresh token lasts
thirty days. Codes and refresh tokens are stored as their sha256 only. A hub administrator sees the
connections in *Memory > MCP Connections* and revokes one: its key goes at once, its refresh token no
longer works. The expired codes and grants are removed by the autovacuum.

The hub must be reachable over https at the address the client uses: the issuer and the resource are
built from the host of the request (with `proxy_mode` behind a reverse proxy).

## A client

With OAuth, the URL alone, for example in the connectors of claude.ai or in Claude Code:

```bash
claude mcp add --transport http memoria https://<hub>/texo/mcp
```

Or with a personal token, for a client that sends a header:

```bash
claude mcp add --transport http memoria https://<hub>/texo/mcp --header "Authorization: Bearer <token>"
```

## Tests

```bash
odoo -c <conf> -d test_cohub20 -i texo_mcp --test-tags /texo_mcp --http-interface=127.0.0.1 --stop-after-init
```

7 tests: the instructions with the rules, the versions and the notifications; the tools as the person, a
write that waits for the yes; a refusal as an error result that writes nothing; the token and the role;
OAuth discovery and the 401 that points to it, the refusal of a foreign redirect address; the whole flow
(registration, consent, code with PKCE, a wrong verifier, a code used twice, the refresh that rotates and
revokes the old key, the revocation by an administrator); the person who denies, the person with no role,
an unknown redirect, a request without PKCE.

## Changelog

### 20.0.1.0.0

- First release in Texo.

## Author

Daniele Lucarelli
