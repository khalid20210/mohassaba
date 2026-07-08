# Internal Architecture Boundaries

This document defines internal dependency boundaries for maintainability.

## Layer Rules

1. `modules/blueprints/*` may import from:
- `modules.engines.*`
- framework/shared utilities (`modules.middleware`, `modules.extensions`, etc.)

2. `modules/blueprints/*` must not import directly from:
- `modules.approval_service`
- `modules.execution_service`
- `modules.rbac_service`

3. `modules/engines/*` are facades and may import service modules.

4. Service modules (`modules/*_service.py`) should remain framework-agnostic.

## Why

- Reduce coupling between HTTP routes and domain logic.
- Keep refactoring safe with stable import boundaries.
- Make testing easier by targeting engine/service seams.

## Enforcement

CI runs `scripts/check_architecture_imports.py`.
Any banned direct import in blueprints fails the workflow.
