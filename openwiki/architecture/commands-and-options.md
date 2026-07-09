# Commands and Options

Users interact with Bert-E almost entirely through PR comments addressed to
`@<robot>` (the robot's git host username). This page explains the generic
mechanism (`bert_e/reactor.py`) and how it's wired to GitWaterFlow-specific
behavior (`bert_e/workflow/gitwaterflow/commands.py`). For the end-user list
of every option/command and their meaning, see the tables in
[`bert_e/docs/USER_DOC.md`](../../bert_e/docs/USER_DOC.md) — this page
covers the mechanism, not the full catalog.

## Options vs. commands

- **Options** are persistent: they stay active for as long as the comment
  that set them remains on the PR (deleting the comment deactivates the
  option). They're stored in `job.settings` and re-evaluated on every
  Bert-E run. Example: `unanimity`, `bypass_build_status`.
- **Commands** are one-shot: found once, executed once, not "remembered".
  Example: `help`, `reset`, `force_reset`.

Both are registered on a shared `Reactor` class (`bert_e/reactor.py`), which
is a generic, dependency-light dispatcher (its only coupling to the rest of
the app is that a "job" must expose a dict-like `.settings`). It is
deliberately reusable/testable in isolation (see its module docstring for a
runnable doctest-style example).

## Registration API (`bert_e/reactor.py`)

- `Reactor.command` — decorator (usable bare or with
  `key=`, `help_=`, `privileged=True`) that registers a one-shot command.
- `Reactor.option` / `Reactor.add_option` — decorator/function to register a
  persistent option with a `default` value, optionally `privileged=True`
  (admins only) or `authored=True` (PR author only).
- `Reactor.init_settings(job)` — populates `job.settings` with every
  registered option's default (deep-copied, so mutable defaults like `set()`
  are safe to share across registrations).
- `Reactor.handle_options` / `Reactor.handle_commands` — scan a comment's
  text for `@robot <keyword>[=value]` tokens and invoke the matching
  handler, raising `NotFound` / `NotPrivileged` / `NotAuthored` for the
  caller to translate into a user-facing message.

## Wiring in GitWaterFlow (`bert_e/workflow/gitwaterflow/commands.py` and `.../utils.py`)

`commands.py::setup(defaults={})` is called once at startup (from
`gitwaterflow/__init__.py`, imported as `from .commands import setup  #
noqa`) and registers every GitWaterFlow-specific option (all the
`bypass_*` options, `unanimity`, `wait`, `after_pull_request`,
`create_pull_requests`, `create_integration_branches`, `approve`,
`no_octopus`, ...) and command (`help`, `status`, `reset`, `force_reset`,
plus stubs `build`/`retry`/`clear` that raise `CommandNotImplemented`).
`defaults` lets a repository's `settings.yml` override an option's default
(see `settings.sample.yml`).

`bert_e/workflow/gitwaterflow/utils.py` holds small predicates like
`bypass_incompatible_branch(job)` that just read the corresponding
`job.settings.bypass_*` flag — these are what the pipeline checks in
`__init__.py` call to decide whether to skip a validation.

`handle_comments()` in `gitwaterflow/__init__.py` is where the reactor is
actually driven for a given PR:

1. It walks **all** comments (in original order) through
   `reactor.handle_options`, computing `privileged` (comment author is in
   `settings.admins`) and `authored` (comment author is the PR author) per
   comment, and turns `NotFound`/`NotPrivileged`/`NotAuthored` into the
   corresponding `bert_e.exceptions` messages (`UnknownCommand`,
   `NotEnoughCredentials`, `NotAuthor`).
2. It then walks comments **in reverse** through `reactor.handle_commands`,
   stopping as soon as it reaches a comment authored by the robot itself
   (so commands are only executed from comments posted *after* Bert-E's
   last reply).

## How to add a new command or option

1. Pick a unique keyword. Decide: persistent behavior (`Reactor.option`,
   needs a default) or one-shot action (`Reactor.command`).
2. Register it in `commands.py::setup()` (or add a new
   `@Reactor.command`/`@Reactor.option`-decorated function near the existing
   ones) — set `privileged=True` if only admins should use it.
3. If it should have a specific side effect beyond "set a settings flag",
   write a dedicated handler function (see `after_pull_request` for an
   option, `force_reset`/`reset` for commands) instead of relying on the
   generic `add_option` setter.
4. If the option gates a check in the pipeline, read it via
   `job.settings.<key>` inside `bert_e/workflow/gitwaterflow/__init__.py`
   (see the existing `bypass_*` usages).
5. Add/adjust the entry in the option/command tables in
   `bert_e/docs/USER_DOC.md`.
6. Add unit tests (`bert_e/tests/unit/`) and, for behavior affecting the
   merge pipeline, functional coverage in `bert_e/tests/test_bert_e.py`.

## What to watch out for

- Command/option keywords are matched against **all** comment text with the
  `@<robot>` prefix — pick keywords that won't collide with normal English
  words users might type after mentioning the robot.
- `privileged`/`authored` checks happen at the `Reactor` level based on
  `job.settings.admins` and the PR author — don't re-implement privilege
  checks ad hoc inside a handler.
- Options are evaluated fresh on every run from the current comment list;
  there is no persisted state beyond "is the setting comment still present".
