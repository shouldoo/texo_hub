# Texo - Timesheet

Odoo 20.0 · LGPL-3

Hours on a task from an agent, behind the Texo token. Installed automatically with
`texo_project` and `hr_timesheet`, so an instance without timesheets never needs it.

| Route (`POST`, bearer = hub token) | Parameters | Returns |
|---|---|---|
| `/texo/v1/project/log_time` | `task_id`, `hours` (0 to 24), `description` (the worklog line, max 500 characters), `date` (optional, `YYYY-MM-DD`, default today) | the timesheet line id, the hours and the task's total |

- The line is created as the calling user, on their employee record: a user without an
  employee gets a refusal, a task the user cannot read answers 404.
- The hours are the person's, never the agent's estimate; the description says what was done
  and why, so the next session reads it in the worklog.
- The task context of `texo_project` gains `worklog` (the last 10 lines: date, hours,
  who, what) and `hours` (spent and allocated).

## Tests

```bash
odoo -c <conf> -d test_cohub20 -i texo_timesheet --test-tags /texo_timesheet --http-interface=127.0.0.1 --stop-after-init
```

## Changelog

### 20.0.1.0.0

- First release in Texo.

## Author

Daniele Lucarelli
