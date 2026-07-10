# Replenishment Tracking Summary Daily ETL Design

## Goal

Run `etl.replenishment_tracking_summary_update` in the daily dashboard task after the replenishment ETL and before the return-goods ETL.

## Scope

- Keep `etl.replenishment_tracking_update` disabled.
- Give the summary ETL its own stdout and stderr logs.
- Stop the daily chain and send a failure notification when the summary ETL fails.
- Keep DingTalk success output compatible with the summary ETL result format.
- Add a real `--dry-run` path that exits before environment loading or database connections.
- Suppress DingTalk transmission when the daily task is executed with `--dry-run`.

## Data Flow

`source preflight -> dashboard ETL -> replenishment ETL -> replenishment tracking summary ETL -> return-goods ETL -> DingTalk`

The summary ETL selects the latest replenishment date during a real run. In dry-run mode it only prints the planned cutoff-date strategy, source sync groups, target tables, and `writes=0`.

## Validation

- Unit test proves summary dry-run never calls environment or database connection functions.
- Script tests prove order, log paths, failure stage, notification arguments, and continued exclusion of the old tracking ETL.
- Notification test proves the new summary success line is rendered as a business result.
- Full daily task is executed with `--dry-run`; remote source preflight may read data, but no target database write is allowed and no DingTalk message is sent.
