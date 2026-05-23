---
name: add-new-dev-tool-module
description: Workflow command scaffold for add-new-dev-tool-module in AutoAFK.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /add-new-dev-tool-module

Use this workflow when working on **add-new-dev-tool-module** in `AutoAFK`.

## Goal

Adds a new dev tool module/package with initial code and test skeletons.

## Common Files

- `src/dev_tools/<module_name>/__init__.py`
- `tests/dev_tools/<module_name>/__init__.py`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Create new package/module directory under src/dev_tools/<module_name>/ with __init__.py.
- Create corresponding test directory under tests/dev_tools/<module_name>/ with __init__.py.
- Add initial implementation files (e.g., models.py, code_generator.py, etc.).
- Add initial test files for new module.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.