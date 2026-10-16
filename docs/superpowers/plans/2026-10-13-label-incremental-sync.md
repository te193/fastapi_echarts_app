# Label Input Incremental Sync

**Goal:** Bootstrap once, then transfer only changed input partitions without
rebuilding historical tables or their indexes.

**Architecture:** Keep the existing full loader for bootstrap and explicit
rebuilds. Compare content fingerprints by business date (or order ID bucket),
stage changed partitions, verify them, and commit the replacements with the
input manifest in one InnoDB transaction. Unchanged partitions stay local.
Existing complete input batches are adopted rather than downloaded again.

**Constraints:** No remote writes, no change to label rules, no loss of older
history, no stale-cache shortcut, no automatic production label recalculation
during verification. Preserve existing timezone dependency changes.

## Tasks

- [x] Add failing dispatch, partition, correction, deletion and rollback tests.
- [x] Implement partition fingerprints and incremental staging/publication.
- [x] Make automatic incremental sync the default; expose explicit full rebuild.
- [x] Run focused and full unit tests and isolated MySQL integration checks.
- [x] Verify the current input batch can be adopted without another full copy.

## Verification

The full suite and isolated MySQL integration tests passed. The integration
checks cover unchanged-cache reuse, historical corrections/deletions, duplicate
rows, FBA normalization, snapshot consistency during concurrent remote edits,
and rollback at source replacement, ledger insertion and marker update.

Read-only checks of all 14 production input tables confirmed that the existing
batch matches the manifest and required physical metadata, indexes, engines and
row counts. Production adoption was subsequently executed with user approval;
label recalculation was not run.

## Production Adoption

On 2026-10-13, the existing full batch
`c66f69a6-54f7-4ce1-8fdd-1bef9c941a8d` was adopted as incremental batch
`b6f6b8b2-1343-49eb-9940-83250a467389`.
All 14 inputs (25,044,300 rows) matched the remote fingerprints. No input rows
were transferred. Runtime was 837.1 seconds, including remote and local
fingerprint scans. A separate connection confirmed the manifest, all 14 ledger
entries, fingerprint versions, and released generation lock.

Log: `logs/label_incremental_adoption_20261013_164441.jsonl`.
The existing enabled `DashboardDailyUpdate` task points to this checkout and
has its next run at 2026-10-14 09:00 Asia/Shanghai. Its complete PowerShell
entry point passed dry-run, including the default incremental label step.
Label archives remain at 2026-10-11; the scheduled generator will replay missing
days. Dry-run validates configuration, not tomorrow's source availability or
successful label calculation.

Remote partition fingerprint checks still read source rows. They are not full
row transfers: history without a reliable modification timestamp requires this
check to detect older in-place updates and deletions. Do not claim CDC or
constant-time remote checks.
