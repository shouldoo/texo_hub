# Texo - Project

Odoo 20.0 · LGPL-3

Project routes for agents, behind the Texo token (API key with scope `texo`,
see the `texo` module). They answer the questions an agent asks most when it works on a
client task, in a compact format meant for an LLM. Installed automatically with `texo`
and `project`.

| Route (`POST`, bearer = hub token) | Parameters | Returns |
|---|---|---|
| `/texo/v1/project/my_work` | `limit` (default 50) | open project tasks assigned to the user: project, customer, stage, priority, deadline |
| `/texo/v1/project/task` | `task_id`, `messages` (default 10, max 30) | the task summary, description as plain text, tags, parent, subtasks, milestone and the latest chatter messages |
| `/texo/v1/project/task_note` | `task_id`, `body` (plain text, max 10,000 characters) | posts an internal note as the user |
| `/texo/v1/project/project` | `project_id` | the project: customer, manager, description as plain text (max 4,000 characters), milestones, its present (`now`, the last update) and the `warnings` on it |
| `/texo/v1/project/update` | `project_id`, `name`, `status` (`on_track`, `at_risk`, `off_track`, `on_hold`, `done`), `description` (plain text, max 10,000 characters), `progress` (0-100; default: the last one) | writes a project update as the user: the new present of the project |

- Everything runs as the user: a task or project the user cannot read answers 404, like one that does
  not exist; an update is written with the access rules of `project` on updates.
- `my_work`, `task` and `project` are read-only routes. `task_note` and `update` write, and their text
  is escaped: an agent cannot inject HTML.
- Names of linked records (project, customer, stage, assignees) are read as Odoo shows them on the
  task form, also when the project itself is restricted.

## A project as the agent reads it

The project lives in Odoo, in three places the people already use:

| What | Where | In the context |
|---|---|---|
| What it is: scope, constraints, stable decisions | the description of the project | `description` |
| The roadmap | the milestones (when the project uses them) | `milestones`: the ones not reached first, by deadline (the overdue ones lead, `overdue`), then the reached ones; with the open and closed tasks the user can see; at most 20 |
| Its present: status, progress, what changed, risks, next steps | the last project update (`last_update_id`); the previous ones are its history | `now`: title, date, author, status, progress, description (max 3,000 characters) |

`warnings` says when the present is not to be trusted as it is: `now_missing` (no update yet),
`now_stale` (the last update is older than 30 days, or a milestone was reached or fell due after
it). The context pack of `texo_memory` carries the project of the task with these warnings.

## The project in Open Knowledge Format

The native fields keep their names; with `format: okf` the routes `project` and `task` answer an
[OKF](https://github.com/GoogleCloudPlatform/open-knowledge-format) concept (`projects/<id>.md`:
the description, the milestones as a checklist, the last update under `# Now`; `tasks/<id>.md`: the
description and the subtasks, the chatter as its log), and the route `log` (`project_id` or `task_id`,
`limit`) the history as a `log.md`, newest first: the updates of a project and the milestones reached,
or the human messages of a task.

## The home project of a company

The internal work of the organisation (its own tasks and updates) needs a project like any customer's
work: every company of the instance has a
**home project** (`project.project.texo_home`), named after the company, with the company
as `company_id`, no customer and visible to every internal user. It is created for every existing
company when the module is installed (`post_init_hook`) and for every new company at its creation (`res.company.create`);
`res.company._texo_home_project()` finds it whatever its state and recreates it when
missing, `_texo_ensure_homes()` does it for every company. One per company, no customer
on it, never deleted (archive it). With several companies, the home of each one follows the
multi-company rules of projects.

The memory of the organisation itself (its rules, facts, procedures and documents) is anchored to the
company, not to the home project (`texo_memory` 20.0.8.0.0). The organisation is never a customer: `project.project._texo_is_own_partner`
tells the partners of our companies from the customers.

## Tests

```bash
odoo -c <conf> -d test_cohub20 -i texo_project --test-tags /texo_project --stop-after-init --http-port 18069
```

## Changelog

### 20.0.1.0.1

- `project/my_work` leaves out the tasks of the project templates and the task templates.

### 20.0.1.0.0

- First release in Texo.

## Author

Daniele Lucarelli
