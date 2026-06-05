# agent.md

# Cursor Agent Rules for TeloraFooty

## Purpose

This file explains how Cursor should use agents on this repo.

Do not repeat the project requirements here. The actual project plan is in:

```txt
docs/Plan.md
docs/git.md
docs/test.md
docs/bestpractices.md
```

This file is only about agent coordination.

---

## Core Rule

Use parallel agents only when the tasks are independent and unlikely to touch the same files.

If two agents would edit the same file, do not run them in parallel.

---

## When to Run Parallel Agents

Run parallel agents for work that can be separated cleanly.

Good examples:

```txt
Agent 1: Build one isolated service.
Agent 2: Write tests for that service.
Agent 3: Review the implementation for bugs.
```

```txt
Agent 1: Work on frame extraction.
Agent 2: Work on motion analysis.
Agent 3: Work on annotation loading.
```

```txt
Agent 1: Implement backend code.
Agent 2: Update documentation examples.
Agent 3: Write tests.
```

Parallel agents are useful for:

```txt
- Independent backend modules
- Tests
- Documentation
- Code review
- Debugging a specific error
- Comparing two possible implementations
```

---

## When Not to Run Parallel Agents

Do not run parallel agents when the work depends on one shared decision.

Bad examples:

```txt
Agent 1: Design API structure.
Agent 2: Implement API routes.
Agent 3: Write frontend integration docs.
```

This is bad because the API structure should be decided first.

Also avoid parallel agents for:

```txt
- Large refactors
- Changing folder structure
- Changing API response formats
- Editing app/main.py from multiple agents
- Editing the same route file
- Editing the same service file
- Dependency installation
- Git operations
- Merge conflict resolution
```

These should be done sequentially.

---

## Agent Task Format

Every agent task should be written like this:

```txt
Agent:
Goal:
Files allowed to edit:
Files not allowed to edit:
Expected output:
Tests required:
```

Example:

```txt
Agent:
Testing Agent

Goal:
Write tests for the clip generation service.

Files allowed to edit:
backend/tests/unit/test_clip_service.py

Files not allowed to edit:
backend/app/services/clip_service.py
frontend/

Expected output:
Pytest tests for normal clipping, invalid ranges, and boundary cases.

Tests required:
Run pytest for the clip service tests.
```

---

## File Ownership Rule

Agents should have clear file ownership.

Recommended ownership:

```txt
API Agent:
backend/app/api/routes/

Service Agent:
backend/app/services/

CV Agent:
backend/app/cv/

Testing Agent:
backend/tests/

Docs Agent:
docs/
```

If a task crosses multiple areas, either:

```txt
1. Run the agents sequentially, or
2. Assign one integration agent after the parallel work is done.
```

---

## Integration Agent Rule

After parallel agents finish, use one integration pass.

The integration agent should:

```txt
- Check that files work together
- Remove duplicated logic
- Fix import errors
- Run tests
- Check API response consistency
- Make sure nothing touched the frontend accidentally
```

Parallel work should not be considered complete until integration is done.

---

## Review Agent Rule

Use a review agent after major changes.

The review agent should check:

```txt
- Does the code follow docs/bestpractices.md?
- Are routes thin?
- Are services modular?
- Are tests present?
- Are errors handled cleanly?
- Did any agent modify forbidden files?
- Did any agent break existing API responses?
```

The review agent should not rewrite everything. It should make small fixes or list issues.

---

## Parallel Agent Examples

### Good Batch: Upload System

```txt
Agent 1:
Implement video storage service.

Agent 2:
Implement metadata extraction service.

Agent 3:
Write upload endpoint tests.

Final Integration Agent:
Connect upload route to storage and metadata services.
```

---

### Good Batch: Clip System

```txt
Agent 1:
Implement FFmpeg clip generation.

Agent 2:
Write clip generation tests.

Agent 3:
Review edge cases around start/end timestamps.

Final Integration Agent:
Confirm clips are created and served correctly.
```

---

### Good Batch: Detection System

```txt
Agent 1:
Implement frame extractor.

Agent 2:
Implement motion analyzer.

Agent 3:
Implement event classifier.

Agent 4:
Write unit tests for motion analyzer and classifier.

Final Integration Agent:
Connect everything inside detection_service.py.
```

---

## Bad Parallel Agent Examples

Do not do this:

```txt
Agent 1: Edit detection_service.py
Agent 2: Edit detection_service.py
Agent 3: Edit detection_service.py
```

Do not do this:

```txt
Agent 1: Change API response shape.
Agent 2: Update tests based on old response shape.
Agent 3: Write frontend docs based on guessed response shape.
```

Do not do this:

```txt
Agent 1: Refactor backend structure.
Agent 2: Add routes.
Agent 3: Fix imports.
```

The refactor should happen first, then routes, then imports/tests.

---

## Conflict Rule

If agents produce conflicting changes:

```txt
1. Stop.
2. Do not guess.
3. Keep the version that best matches docs/Plan.md and docs/bestpractices.md.
4. Preserve tests.
5. Preserve stable API responses.
6. Ask before deleting or rewriting major code.
```

---

## Git Rule

Agents should not commit automatically.

Only commit when explicitly asked.

Before committing, check:

```bash
git status
```

Do not commit:

```txt
- Full MP4 game files
- .env
- node_modules
- __pycache__
- generated clips
- large storage files
```

---

## Final Rule

Parallel agents are for speed, not chaos.

Use them when work is isolated.

Avoid them when architecture, shared files, or API contracts are still being decided.
