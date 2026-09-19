# Internal contract

Use Python 3.11+, standard library where practical. Normalized snapshots are JSON dictionaries:

```
{schema_version:1, league_id:int, league_name:str, season:int, week:int,
 completed:bool, settings:{lineup_slots:{slot_id:count}, playoff_team_count:int|null, faab_budget:number|null},
 teams:[{id:int,name:str,managers:[str],rank:int|null,wins:int,losses:int,ties:int,
 points_for:number,points_against:number,faab_remaining:number|null}],
 matchups:[{id:str,home_team_id:int,away_team_id:int|null,home_score:number,
 away_score:number|null,home_projected:number|null,away_projected:number|null}],
 rosters:[{team_id:int,players:[{id:int,name:str,score:number|null,projected:number|null,
 slot_id:int,eligible_slots:[int],starter:bool}]}],
 transactions:[{id:str,date:str,week:int,team_id:int,type:str,player_added:int|null,
 player_dropped:int|null,player_name:str|null,faab_bid:number|null}],
 availability:{transactions:bool,projections:bool,rosters:bool}, warnings:[str]}
```

Missing optional data is null/unavailable, never falsely zero. Bench slots 20/21 excluded from active lineup slots. Ties and byes supported. History consists of earlier snapshots from same league/season, sorted by week.

Interfaces:
- ESPNClient(league_id,season,espn_s2='',swid=''); get_status(); latest_completed_week() -> int|None; fetch_week(week) -> tuple[raw dict,normalized snapshot]. Network errors raise ESPNFetchError. Explicit incomplete weeks rejected.
- src.analytics.engine.analyze(snapshot, history) -> analysis dict; validate_analysis(analysis) raises ValueError.
- src.reports.weekly_report.generate_report(analysis, *, api_key='', model='', no_llm=False) -> dict with markdown, html, audit (dict). No-LLM yields deterministic preview, not eligible for emailing.
- Parent owns config, storage, jobs, email, main, scheduler, README and integration tests. Agents own their module packages, associated tests and docs only.

Analysis keys follow PRD section 22; at least season, week, league_summary, weekly_scoring, standings, top_matchups, all_matchups, transactions, waiver_analysis, manager_analysis, team_trends, league_trends, all_play, expected_wins, notable_events. Include normalized snapshot in analysis under source_snapshot for traceability.
