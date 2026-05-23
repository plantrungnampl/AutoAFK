---
name: feature-implementation-with-tests
description: Workflow command scaffold for feature-implementation-with-tests in AutoAFK.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /feature-implementation-with-tests

Use this workflow when working on **feature-implementation-with-tests** in `AutoAFK`.

## Goal

Implements a new feature in an existing module and adds corresponding tests.

## Common Files

- `src/dev_tools/<module_name>/*.py`
- `tests/dev_tools/<module_name>/test_*.py`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Add new implementation file(s) to src/dev_tools/<module_name>/ (e.g., models.py, action_schema.py, agent_client.py, agent_loop.py, agent_gui.py, prompt_templates.py).
- Add or update corresponding test file(s) in tests/dev_tools/<module_name>/ (e.g., test_action_schema.py, test_agent_client_errors.py, test_agent_loop.py).

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.