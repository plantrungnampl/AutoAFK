```markdown
# AutoAFK Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns, coding conventions, and workflows used in the AutoAFK Python codebase. AutoAFK is organized around modular dev tools, with a strong emphasis on test-driven development, conventional commits, and clear documentation. This guide will help you contribute new modules, implement features, and maintain documentation in line with project standards.

## Coding Conventions

**File Naming**
- Use `snake_case` for all Python files and directories.
  - Example: `agent_client.py`, `action_schema.py`

**Import Style**
- Use relative imports within modules.
  - Example:
    ```python
    from .models import ActionModel
    ```

**Export Style**
- Use named exports; explicitly define what is available for import.
  - Example:
    ```python
    __all__ = ["ActionModel", "AgentClient"]
    ```

**Commit Messages**
- Use [Conventional Commits](https://www.conventionalcommits.org/) with these prefixes:
  - `feat`: New features
  - `fix`: Bug fixes
  - `docs`: Documentation changes
  - `spec`: Specifications or test plans
  - `plan`: Planning or roadmap updates
- Example:
  ```
  feat(agent_loop): add async support for agent actions
  ```

## Workflows

### Add New Dev Tool Module
**Trigger:** When starting development of a new dev tool (e.g., `llm_recorder`, `llm_agent`)
**Command:** `/new-dev-tool-module`

1. Create a new directory for the module under `src/dev_tools/<module_name>/` with an `__init__.py` file.
2. Create a corresponding test directory under `tests/dev_tools/<module_name>/` with an `__init__.py` file.
3. Add initial implementation files, such as `models.py`, `code_generator.py`, etc.
4. Add initial test files for the new module.

**Example:**
```bash
mkdir -p src/dev_tools/llm_agent
touch src/dev_tools/llm_agent/__init__.py
mkdir -p tests/dev_tools/llm_agent
touch tests/dev_tools/llm_agent/__init__.py
touch src/dev_tools/llm_agent/models.py
touch tests/dev_tools/llm_agent/test_models.py
```

---

### Feature Implementation with Tests
**Trigger:** When adding a new feature or component to an existing dev tool module
**Command:** `/add-feature-with-tests`

1. Add new implementation file(s) to `src/dev_tools/<module_name>/` (e.g., `models.py`, `agent_client.py`).
2. Add or update corresponding test file(s) in `tests/dev_tools/<module_name>/` (e.g., `test_agent_client_errors.py`).

**Example:**
```python
# src/dev_tools/llm_agent/agent_client.py
class AgentClient:
    pass

# tests/dev_tools/llm_agent/test_agent_client.py
from src.dev_tools.llm_agent.agent_client import AgentClient

def test_agent_client_init():
    client = AgentClient()
    assert client is not None
```

---

### Update Documentation and Guides
**Trigger:** When documenting new features, updating setup instructions, or adding developer guides
**Command:** `/update-docs`

1. Add or update markdown files in `docs/` or the project root (e.g., `DEVELOPER_GUIDE.md`, `README.md`).
2. Add or update smoke test checklists or specifications as needed.

**Example:**
```bash
touch docs/llm-agent-smoke-test.md
echo "# LLM Agent Smoke Test" > docs/llm-agent-smoke-test.md
```

## Testing Patterns

- **Framework:** Not explicitly defined; test files follow the `*.test.ts` pattern (TypeScript), but Python modules use `test_*.py` for tests.
- **Location:** Tests are placed in `tests/dev_tools/<module_name>/`.
- **Structure:** Each module has a mirrored test directory.
- **Example:**
  ```python
  # tests/dev_tools/llm_agent/test_action_schema.py
  from src.dev_tools.llm_agent.action_schema import ActionSchema

  def test_action_schema_valid():
      schema = ActionSchema(...)
      assert schema.is_valid()
  ```

## Commands

| Command                 | Purpose                                                        |
|-------------------------|----------------------------------------------------------------|
| /new-dev-tool-module    | Scaffold a new dev tool module with initial code and tests     |
| /add-feature-with-tests | Add a feature to an existing module with corresponding tests   |
| /update-docs            | Update or add documentation, guides, or checklists            |
```
