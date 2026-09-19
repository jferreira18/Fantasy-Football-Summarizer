# ESPN ingestion

This is a read-only adapter for ESPN fantasy football seasons from 2019 onward. Private leagues use `ESPN_S2` and `ESPN_SWID` cookies, loaded by application configuration. No credentials are logged or stored in snapshots.

`ESPNClient.fetch_week(week)` returns raw responses plus a stable normalized snapshot. HTTP requests have a 30-second timeout and at most three attempts for transient failures. Authentication, malformed data, incomplete scores, incomplete schedules, and uncertain completion fail closed.

Completion requires ESPN's scoring period to advance, the league's period mapping to identify that week, and every contested matchup to have a finalized winner. It does not use calendar dates. This can conservatively delay a report until ESPN updates its status. A final season week requires ESPN to advance beyond it. Multi-scoring-period matchup leagues are explicitly rejected because weekly scores and matchup win/loss results differ; supporting these needs a separate matchup-versus-scoring-period analytics model.

Historical regular-season records and points are reconstructed from schedule scores. ESPN's current seed is used only when processing the latest completed week and current records agree with reconstructed records. Historical official ranks are null; current standings are never copied into a backfill. Division/tiebreaker rules are not guessed. Historical FAAB balance is null.

Boxscore rosters are requested for the precise scoring period. Actual and projected player scores use season/week-specific applied totals; missing stats are null, not zero. Team projections require projections for every visible starter. Benches and IR slots are excluded. Current live projection totals are not substituted for pregame projections.

Transactions use `mTransactions2` with scoring-period/type filtering, limit, and offset. Only executed transactions count. Pagination is bounded; duplicate pages, missing response fields, or hidden trade items mark activity unavailable. This API is undocumented: successful short-page pagination cannot guarantee ESPN disclosed every owner-private record. Acquisition plus drop legs share `transaction_id`; aggregate transaction counts must deduplicate that ID, while adds/drops count legs. FAAB bid appears only on the waiver add leg. Losing bids and historical balances are not fabricated. The raw response is retained for auditing.

The stored fixture is synthetic and representative of ESPN response shapes; it is not a captured production league response. Live validation remains necessary once the user configures a league.

Implementation behavior was checked against primary open-source adapter code on 2026-09-18:

- [ESPN API league retrieval, scoreboard, transactions](https://github.com/cwendt94/espn-api/blob/master/espn_api/football/league.py)
- [Cookie setup and season status](https://github.com/cwendt94/espn-api/blob/master/espn_api/base_league.py)
- [Boxscore fields](https://github.com/cwendt94/espn-api/blob/master/espn_api/football/box_score.py)
- [Transaction fields](https://github.com/cwendt94/espn-api/blob/master/espn_api/football/transaction.py)

ESPN does not provide a supported public API contract for this integration. The adapter deliberately surfaces missing information and requires fixture updates if ESPN changes its schema.
