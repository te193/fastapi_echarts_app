# 页面访问统计 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. User approved the minimal design in chat.

**Goal:** Record visits to every HTML page and show a complete 7/30-day usage table, including zero-visit pages, for a month of observation.
**Architecture:** A shared browser script sends visible-page visits to a small FastAPI router. An independent SQLite file stores anonymous events with transaction-safe 30-second deduplication. Registry-driven summaries include all pages and use Asia/Shanghai calendar boundaries. No ETL changes or external analytics.
**Tech Stack:** Existing FastAPI/Jinja/JavaScript, Python sqlite3, pytest and Node built-in tests.
**Spec:** User-approved design in this chat: page-only events, browser IDs, formal/test separation, 7/30-day counts, active days, latest visit, zero-first sorting; ETL unchanged.

## Global Constraints
- Cover all 18 existing HTML routes plus the new statistics page; ignore API calls and automatic data refresh.
- Same-browser same-page visits within 30 seconds count once; retry IDs stay idempotent.
- No user names, IP addresses, search parameters, or business data are saved.
- Use a separate persistent local SQLite file; no new ETL, no source database writes.
- Existing working directory contains active uncommitted work needed by this app; make narrow edits in place without committing unrelated changes.

## Review Focus
- Concurrent or retried submissions must not inflate counts.
- Hidden tabs count only on first visibility; blocked storage/network cannot break pages.
- Test traffic stays excluded by default, including port 8001 and browser automation.
- New or infrequently visited pages stay visible at zero; early zeroes are not called unused before 30 days.
- Windows service restarts preserve data, and Shanghai day boundaries must be deterministic.

### Task 1: Event store and statistics API
**Files:** app/services/page_usage.py, app/page_usage_routes.py; tests/test_page_usage.py
**Interfaces:** PageUsageService.record_visit(page_id, browser_id, visit_id, environment), .summary(environment); PAGE_REGISTRY.
- [x] Write and run failing behavior tests: calendar windows, zero pages, dedup boundaries/concurrency/retry, environment isolation, bad input, persistence and storage outage.
- [x] Implement registry, SQLite indexes/metadata, transaction-safe dedup, validated router endpoints and page route.
- [x] Pass focused tests against temporary real SQLite files.

### Task 2: Shared collector and statistics UI
**Files:** app/static/js/page_usage.js, app/static/js/page_usage_stats.js, app/static/css/page_usage.css, app/templates/page_usage.html, app/templates/base.html, app/main.py, .gitignore; tests/page_usage_client.test.cjs
- [x] Write and run failing browser-script tests using Node mocks for visibility, reload dedup, local/session storage failures, test flags and failed requests.
- [x] Add collector to shared base, statistics navigation, readable zero-first table with formal/test selector and text filter.
- [x] Verify route coverage, zero rows, error UI and API behavior; run related existing regression tests.

### Task 3: Enable observation and verify
- [x] Review only this feature diff, run focused Python/JS tests and browser preview.
- [x] Initialize the durable usage store, restart only web service to load routes, verify HTTP and real test-mode collection without polluting formal statistics.
- [x] Document observation start, anonymous-browser limitations and test controls; report statistics URL and that ETL was untouched.

## Execution ledger
- Ruling: Use independent SQLite under data/ with ignore rules; very small append workload avoids introducing dependencies on business database availability.
- Ruling: Work in place because current running app relies on uncommitted changes in main.py/base.html; do not create a stale checkout or overwrite those edits.

- Completed: 88 focused/regression Python tests and 10 Node tests passed. Independent review found a rejected-duplicate cooldown bug; reproduced RED, fixed, and verified GREEN. Real browser verified test-only page collection and zero-first formal table. Existing 8000 web service restarted successfully; observation starts 2026-10-26 10:04:21. No ETL files modified by this feature.
