# Copilot Agent Instructions

## Overview

RELATE is a Django-based learning management system (LMS). Its main unit of
interactivity is a *flow*: a sequence of pages described via YAML containing a
Markdown flavor. Database support centers on Postgres for production and SQLite
for testing and development. It uses [uv](https://docs.astral.sh/uv/) for
Python package management and rollup/npm for JS/frontend package management.

## Repository Structure

- `accounts/`: Custom user model app
- `course/`: Core LMS business logic
- `relate/`: Supporting functionality
- `docker-image-run-py/`: Code for building the Python autograder Docker images
- `frontend/`: JS frontend code (uses an ESLint configuration)
- `prairietest/`: Interoperability with PrairieTest test center management
- `tests/`: pytest-driven test suite

## Linting

Always ensure `uv run ruff check` passes before finishing a change.

## Type Checking

Run `uv run basedpyright` and aim to keep it passing.  Use judgment:

- If making it pass requires large amounts of type annotation unrelated to the
  change at hand, or if the diagnostics relate to external packages, it is
  acceptable to sweep the associated diagnostics into the baseline instead:

  ```
  uv run basedpyright --writebaseline
  ```

## Testing

Run tests with:

```
uv run pytest          # standard test suite
uv run pytest --slow   # includes slow tests
```

Both commands can take multiple minutes. Focus test runs on newly-created or
modified tests rather than the full suite, and rely on CI for full coverage.
