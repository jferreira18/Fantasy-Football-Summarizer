# Deterministic metric definitions

All calculations run in Python; the report consumes the saved analysis JSON. Decimal outputs round to four places after calculation. Tied scores receive competition rank (1, 1, 3). Score variance and standard deviation use the population formula. Missing optional inputs produce null; unavailable transaction feeds never imply zero moves.

Byes contribute observed scores to weekly ranks/all-play and scoring history, but have no winner, loser, margin, interest rank, actual or expected head-to-head win. Head-to-head ties contribute half a win equivalent. Expected wins sum `(all_play_wins + 0.5 * all_play_ties) / opponents` for weeks with an actual matchup. Actual-minus-expected uses observed actual wins plus half ties over that same sample, never compares a partial expected total to ESPN's full-season wins. All-play percentage includes half credit for ties.

Every historical section is scoped to observed completed snapshots from the same league/season. `league_summary.history_complete` means weeks 1 through the report week are all present. Sample counts and observed weeks must accompany historical interpretation. Standings movement requires the immediately preceding week's snapshot with known ranks. Playoff entry/exit requires a known playoff-team count. Streaks stop at missing weeks or byes; truncated streaks are marked lower bounds. Points-against rank is descending (rank 1 faced the most points).

## Top three matchups

Exclude byes and calculate `4*C + 2*S + 3*L + U`, bounded to 0–10:

- C = `1 / (1 + margin/10)`.
- S = fraction of this week's games with combined score less than or equal to this game's combined score.
- L = `(team_count_with_scores - losing_score_rank) / (team_count_with_scores - 1)`; zero for ties.
- U = one when both projections exist and the projected lower scorer won, otherwise zero.

Sort by descending score, then ascending string matchup ID. Select at most three. Reasons flag margin <= 10, combined percentile >= .75, losing-score context >= .5, and a projection upset. Ties have zero high-scoring-loss weight and cannot be upsets.

## Lineups

Exact maximum-weight assignment uses each player once, respects eligible slot IDs and configured slot counts, and excludes bench/IR slot IDs 20/21. It uses dynamic programming across occupied slot masks; it is not a greedy positional selection. All active slots must be filled legally. An incomplete score set or impossible legal lineup produces a null optimum. `points_left_on_bench` is optimal lineup minus actual starter points, not total bench points. Efficiency is 100 times starter points divided by optimum and is null for nonpositive optimum. An invalid observed starter total above optimum yields null efficiency and missed points.

## Trends and events

Last-three/five averages use scoring weeks within the corresponding calendar scoring-period window. Scoring change compares the latest three complete consecutive weeks to the mean of earlier observed weeks, requiring at least three earlier observations. Trend up/down requires >= 10% / <= -10% change. Consistency requires at least three observations: population coefficient of variation <= .10 is high consistency; >= .25 is high volatility.

High-scoring loss means a losing score strictly above this week's median; low-scoring win is strictly below. Standings jump/drop means at least two places. Streak events require three wins/losses. Bench explosion requires at least 25 avoidable points, low efficiency is below 75%, and high FAAB spend is at least 20% of known initial budget. Schedule over/underperformance requires at least three observed games and an actual-minus-expected gap >= 1.5 or <= -1.5. Season-record events require prior observations and complete season coverage; otherwise they are explicitly observed-history records. Closest game is always reported when games exist; blowout event requires a margin >= 30.

## Transactions and acquisitions

Transaction count groups player legs by `(week, transaction_id)`, falling back to row ID; adds/drops count player legs. Trades count unique transactions. Waiver claims represent successful recorded acquisitions, not attempted bids; waiver-success rate remains null because losing claims are unavailable. FAAB is null when any successful waiver bid is missing. Season totals are observed-history totals, with global coverage metadata. Spending rate is recorded observed spend divided by original budget. Roster churn is additions plus drops.

Acquisition performance starts the week **after** acquisition because normalized rows do not reliably establish ownership before game kickoff. It ends at the first subsequent drop or first roster absence. Missing roster observations invalidate point totals; start/bench counts remain observed counts. Points-per-dollar is null for free/unknown cost, never infinity. `percentage_of_acquired_points_started` is started points divided by all attributed points, when total is positive. Acquisitions with no subsequent observations have sample_count zero and must not be interpreted as underperformers. Manager acquisition-started percentage counts acquisitions with at least one observed start; it is descriptive, not a forecast.
