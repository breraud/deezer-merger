# Deezer Mix & Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a FastAPI app that merges three Deezer source playlists into one target playlist and can surgically refresh one player's share without touching the others.

**Architecture:** A small FastAPI server owns an in-memory `STATE` cache with source pools and current per-player selections. A `deezer_client.py` module wraps `deezer-python-gql` access, while a static Vanilla JS frontend drives generation and refresh actions through REST endpoints.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, deezer-python-gql, python-dotenv, HTML/CSS/Vanilla JS, Apache2, systemd.

### Task 1: Bootstrap project files

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `.env.example`

**Step 1: Write the failing test**

Check that the repository has no ignored env template or dependency manifest yet.

**Step 2: Run test to verify it fails**

Run: `test -f .gitignore && test -f requirements.txt && test -f .env.example`
Expected: non-zero exit code

**Step 3: Write minimal implementation**

Create the three files with the required entries.

**Step 4: Run test to verify it passes**

Run: `test -f .gitignore && test -f requirements.txt && test -f .env.example`
Expected: zero exit code

**Step 5: Commit**

```bash
git add .
git commit -m "chore: init project and env"
```

### Task 2: Build Deezer connector

**Files:**
- Create: `deezer_client.py`
- Create: `tests/test_deezer_client.py`

**Step 1: Write the failing test**

Add tests for track ID extraction and 50-track batch splitting with clear fake client objects.

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_deezer_client -v`
Expected: FAIL because `deezer_client` does not exist yet

**Step 3: Write minimal implementation**

Add a Deezer service wrapper with auth bootstrap, `get_playlist_tracks`, and `update_target_playlist`.

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_deezer_client -v`
Expected: PASS

**Step 5: Commit**

```bash
git add .
git commit -m "feat: deezer gql client and batch update logic"
```

### Task 3: Build backend state and API

**Files:**
- Create: `main.py`
- Create: `tests/test_main.py`

**Step 1: Write the failing test**

Add tests for mix generation, surgical refresh, and API status/generate/refresh behavior.

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_main -v`
Expected: FAIL because `main.py` behavior is not implemented yet

**Step 3: Write minimal implementation**

Implement config loading, in-memory state, selection logic, and REST routes.

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_main -v`
Expected: PASS

**Step 5: Commit**

```bash
git add .
git commit -m "feat: fastapi endpoints and memory cache logic"
```

### Task 4: Build static frontend

**Files:**
- Create: `static/index.html`
- Create: `static/style.css`
- Create: `static/app.js`

**Step 1: Write the failing test**

Check that static assets are missing before creation.

**Step 2: Run test to verify it fails**

Run: `test -f static/index.html && test -f static/style.css && test -f static/app.js`
Expected: non-zero exit code

**Step 3: Write minimal implementation**

Create UI, loading states, and fetch integration with backend API.

**Step 4: Run test to verify it passes**

Run: `test -f static/index.html && test -f static/style.css && test -f static/app.js`
Expected: zero exit code

**Step 5: Commit**

```bash
git add .
git commit -m "feat: vanilla JS frontend and API integration"
```

### Task 5: Add deployment assets and verify

**Files:**
- Create: `deploy/deezer.beraud.dev.conf`
- Create: `deploy/deezer-mix.service`
- Create: `deploy/SETUP.md`

**Step 1: Write the failing test**

Check that deployment files are missing before creation.

**Step 2: Run test to verify it fails**

Run: `test -f deploy/deezer.beraud.dev.conf && test -f deploy/deezer-mix.service && test -f deploy/SETUP.md`
Expected: non-zero exit code

**Step 3: Write minimal implementation**

Add Apache vhost, systemd service, and VPS setup guide.

**Step 4: Run test to verify it passes**

Run: `test -f deploy/deezer.beraud.dev.conf && test -f deploy/deezer-mix.service && test -f deploy/SETUP.md`
Expected: zero exit code

**Step 5: Commit**

```bash
git add .
git commit -m "chore: apache, systemd and deployment configs"
```
