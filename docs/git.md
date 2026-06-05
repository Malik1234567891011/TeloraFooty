read this but forget pull requests its just me and omar, never push to main until i say so we will stay on our branch 
---

# `git.md`

```md
# TeloraFooty Git Workflow

## 1. Main Rule

Never work directly on `main`.

All backend work should happen on Malik's backend branch.

Recommended branches:

```txt
main
backend/malik
frontend/omar

Malik should use:

git checkout -b backend/malik

If the branch already exists:

git checkout backend/malik
git pull origin backend/malik
2. Repo Structure

Recommended monorepo structure:

TeloraFooty/
  backend/
  frontend/
  docs/

Backend changes should stay inside:

backend/
docs/

Frontend changes should stay inside:

frontend/

Do not mix backend and frontend changes in the same commit unless required for API integration.

3. Commit Often

Commit after each meaningful working step.

Good commit examples:

git add backend docs
git commit -m "Set up FastAPI backend structure"
git add backend/app/api/routes/health.py
git commit -m "Add backend health check endpoint"
git add backend/app/services/clip_service.py backend/tests
git commit -m "Add FFmpeg clip generation service"
git add backend/app/cv backend/tests
git commit -m "Add demo clip motion analysis pipeline"

Bad commit examples:

git commit -m "stuff"
git commit -m "changes"
git commit -m "fix"
git commit -m "idk"
4. Recommended Commit Style

Use short but meaningful messages.

Format:

Verb + what changed

Examples:

Add video upload endpoint
Create annotation loader
Generate clips from event timestamps
Add demo clip analysis endpoint
Fix clip duration boundary bug
Refactor detection service
Add tests for video metadata extraction
5. Pull Before You Push

Before pushing:

git status
git pull origin backend/malik

If there are conflicts, resolve them carefully.

Then:

git push origin backend/malik
6. Before Making a Pull Request

Run backend checks:

cd backend
pytest

Also start the backend:

uvicorn app.main:app --reload

Check:

GET /api/health

Confirm:

Backend starts.
Tests pass.
Upload endpoint works.
Clip generation still works.
Existing API responses did not change unexpectedly.
7. Pull Request Rules

When ready to merge into main:

Push branch.
Open PR from backend/malik into main.
Explain what changed.
Mention how it was tested.
Do not merge broken code.

PR description template:

## What changed

- Added ...
- Updated ...
- Fixed ...

## How I tested it

- Ran pytest
- Tested /api/health
- Uploaded demo clip
- Generated clip from timestamp

## Notes

- Full-game processing currently uses manual annotations.
- Demo clip analysis uses hybrid detection/heuristics.
8. Handling Frontend/Backend Integration

The frontend should not guess backend response shapes.

If backend API changes:

Update backend route.
Update API response schema.
Tell Omar the exact response format.
Add example JSON to docs or README.
Commit the change.

Backend should avoid breaking changes once Omar starts using an endpoint.

If a change is unavoidable, version or clearly document it.

9. Files That Should Not Be Committed

Do not commit:

backend/storage/uploads/*
backend/storage/clips/*
backend/storage/processed/*
backend/.env
__pycache__/
.venv/
node_modules/
.DS_Store

Use .gitignore.

Exception:

Tiny sample videos can be committed only if intentionally added to backend/tests/fixtures.
Prefer not to commit large videos.
10. Large Video Files

Full Veo MP4 files should not be committed.

Use local storage or shared drive.

Recommended:

backend/storage/uploads/game_001.mp4
backend/storage/uploads/game_002.mp4
backend/storage/uploads/game_003.mp4

Commit only the annotation metadata:

backend/storage/annotations/game_001.json
backend/storage/annotations/game_002.json
backend/storage/annotations/game_003.json
11. Emergency Recovery Commands

Check current branch:

git branch

Check changed files:

git status

See recent commits:

git log --oneline --max-count=10

Undo unstaged changes to one file:

git checkout -- path/to/file

Undo last commit but keep changes:

git reset --soft HEAD~1

Stash current changes:

git stash

Bring stashed changes back:

git stash pop