# AGENTS.md

These instructions apply to the entire repository.

## Working guidelines

- Keep changes focused on the requested task.
- Follow the existing project structure and conventions as they emerge.
- Preserve unrelated work and avoid destructive Git operations.
- Add or update tests when behavior changes.
- Update documentation when setup, usage, or architecture changes.

## Agent development

- Keep agent rules focused on design principles; revisit the design and fix root causes instead of adding case-specific rules.

## Architecture

- Keep the frontend and backend as separate applications.
- Connect them only through documented, versioned APIs.
- Keep business logic, data access, agent orchestration, and R execution in the backend.
- Keep presentation, user interaction, and API consumption in the frontend.
- Do not expose backend file paths, storage details, or internal modules to the frontend.
- Define shared request and response contracts explicitly.

## Project structure

- Organize code by responsibility with clear, predictable directories.
- Keep modules focused, cohesive, and small enough to understand.
- Use descriptive, consistent names for files, directories, and public interfaces.
- Keep source code, tests, documentation, configuration, and generated artifacts separate.
- Avoid miscellaneous utility files, duplicated logic, and unnecessary abstractions.
- Place shared code in a shared module only when it has multiple real consumers.

## Verification

Run the relevant formatting, linting, tests, and build checks before considering a change complete. If a check cannot be run, explain why in the handoff.
