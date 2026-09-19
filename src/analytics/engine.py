"""Reproducible analytics; all history-dependent claims carry sample coverage."""
import math
import statistics as stats
from .roster_analysis import roster_metrics


def rounded(value):
    return round(value, 4) if value is not None else None


def scores_for(snapshot):
    scores = {}
    for match in snapshot['matchups']:
        for side in ('home', 'away'):
            tid, score = match.get(side+'_team_id'), match.get(side+'_score')
            if tid is not None and score is not None:
                if tid in scores and scores[tid] != score:
                    raise ValueError('Conflicting weekly team scores')
                scores[tid] = score
    return scores


def rank(value, values):
    return 1 + sum(v > value for v in values)


def outcome(snapshot, tid):
    for m in snapshot['matchups']:
        if m.get('away_team_id') is None:
            continue
        if tid in (m['home_team_id'], m['away_team_id']):
            own, other = (m['home_score'], m['away_score']) if tid == m['home_team_id'] else (m['away_score'], m['home_score'])
            return 'W' if own > other else 'L' if own < other else 'T'
    return None


def transaction_totals(snapshots, tid):
    tx = [t for s in snapshots for t in s.get('transactions', []) if t.get('team_id') == tid]
    available = all(s.get('availability', {}).get('transactions', False) for s in snapshots)
    claims = [t for t in tx if t['type'] == 'WAIVER']
    return dict(transactions=len({(t.get('week'),t.get('transaction_id',t['id'])) for t in tx}) if available else None, adds=sum(t.get('player_added') is not None for t in tx) if available else None, drops=sum(t.get('player_dropped') is not None for t in tx) if available else None, waiver_claims=len(claims) if available else None, free_agent_adds=sum(t['type'] == 'FREE_AGENT' for t in tx) if available else None, trades=len({(t.get('week'),t.get('transaction_id',t['id'])) for t in tx if t['type']=='TRADE'}) if available else None, faab_spent=rounded(sum(t['faab_bid'] for t in claims)) if available and all(t.get('faab_bid') is not None for t in claims) else None, available=available)


def analyze(snapshot, history=()):
    if not snapshot.get('completed'):
        raise ValueError('Analytics requires a completed week')
    teams = {t['id']: t for t in snapshot['teams']}
    if len(teams) != len(snapshot['teams']):
        raise ValueError('Duplicate team ID')
    prior = {s['week']: s for s in history if s['season'] == snapshot['season'] and s['league_id'] == snapshot['league_id'] and s['week'] < snapshot['week'] and s.get('completed')}
    weeks = [prior[k] for k in sorted(prior)] + [snapshot]
    coverage = dict(observed_weeks=[s['week'] for s in weeks], sample_count=len(weeks), history_complete=[s['week'] for s in weeks] == list(range(1, snapshot['week']+1)))
    scores = scores_for(snapshot)
    if not scores or any(tid not in teams or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for tid, v in scores.items()):
        raise ValueError('Invalid team scores')
    values = list(scores.values())
    ranks = {tid: rank(v, values) for tid, v in scores.items()}
    rosters = {r['team_id']: roster_metrics(r['players'], snapshot.get('settings', {}).get('lineup_slots', {})) for r in snapshot.get('rosters', [])}
    previous = {t['id']: t for t in weeks[-2]['teams']} if len(weeks)>1 and weeks[-2]['week']==snapshot['week']-1 else {}
    standings, all_play, expected, trends, managers, events = [], [], [], [], [], []
    for tid, team in sorted(teams.items()):
        prev_rank = previous.get(tid, {}).get('rank')
        current_rank = team.get('rank')
        change = prev_rank-current_rank if prev_rank is not None and current_rank is not None else None
        streak, last = 0, outcome(snapshot, tid)
        expected_week = snapshot['week']
        for s in reversed(weeks):
            if s['week'] != expected_week or outcome(s, tid) != last or last not in ('W', 'L'):
                break
            streak += 1
            expected_week -= 1
        playoff = snapshot.get('settings', {}).get('playoff_team_count')
        standing = dict(team_id=tid, team=team['name'], current_rank=current_rank, previous_rank=prev_rank, rank_change=change, wins=team['wins'], losses=team['losses'], ties=team['ties'], points_for=team['points_for'], points_against=team['points_against'], points_against_rank=rank(team['points_against'], [t['points_against'] for t in teams.values()]), winning_streak=streak if last=='W' else 0, losing_streak=streak if last=='L' else 0, streak_is_lower_bound=streak>0 and expected_week>0, entered_playoff_position=(prev_rank>playoff>=current_rank) if playoff and prev_rank and current_rank else None, left_playoff_position=(current_rank>playoff>=prev_rank) if playoff and prev_rank and current_rank else None, new_first_place=prev_rank != 1 and current_rank == 1 if prev_rank else None)
        standings.append(standing)
        apw = apl = apt = actual = actual_ties = eligible = high_losses = low_wins = 0
        exp = 0.0
        team_scores = []
        for s in weeks:
            sc = scores_for(s)
            if tid not in sc:
                continue
            own = sc[tid]
            team_scores.append((s['week'], own))
            others = [v for other, v in sc.items() if other != tid]
            w, l, t = sum(own>v for v in others), sum(own<v for v in others), sum(own==v for v in others)
            apw += w; apl += l; apt += t
            result = outcome(s, tid)
            if others and result is not None:
                exp += (w + t/2)/len(others)
                eligible += 1
                actual += result == 'W'
                actual_ties += result == 'T'
                high_losses += result == 'L' and own > stats.median(sc.values())
                low_wins += result == 'W' and own < stats.median(sc.values())
        apden = apw+apl+apt
        all_play.append(dict(team_id=tid, team=team['name'], all_play_wins=apw, all_play_losses=apl, all_play_ties=apt, all_play_pct=rounded((apw+apt/2)/apden) if apden else None, sample_count=len(team_scores)))
        expected.append(dict(team_id=tid, team=team['name'], actual_wins=actual, actual_ties=actual_ties, actual_win_equivalents=actual+actual_ties/2, expected_wins=rounded(exp), actual_minus_expected=rounded(actual+actual_ties/2-exp), sample_count=eligible, high_scoring_losses=high_losses, low_scoring_wins=low_wins))
        arr = [v for _, v in team_scores]
        recent = [v for w,v in team_scores if w >= snapshot['week']-2]
        older = [v for w,v in team_scores if w < snapshot['week']-2]
        delta = stats.mean(recent)-stats.mean(older) if len(recent)==3 and len(older)>=3 else None
        pct = 100*delta/abs(stats.mean(older)) if delta is not None and stats.mean(older)!=0 else None
        cv = stats.pstdev(arr)/abs(stats.mean(arr)) if len(arr)>=3 and stats.mean(arr) else None
        trend = 'UP' if pct is not None and pct>=10 else 'DOWN' if pct is not None and pct<=-10 else None
        trends.append(dict(team_id=tid, team=team['name'], sample_count=len(arr), season_scoring_average=rounded(stats.mean(arr)) if arr else None, last_3_week_average=rounded(stats.mean(recent)) if recent else None, last_3_sample_count=len(recent), last_5_week_average=rounded(stats.mean([v for w,v in team_scores if w>=snapshot['week']-4])) if arr else None, season_median=rounded(stats.median(arr)) if arr else None, season_variance=rounded(stats.pvariance(arr)) if arr else None, season_standard_deviation=rounded(stats.pstdev(arr)) if arr else None, scoring_change=rounded(delta), scoring_change_pct=rounded(pct), trend=trend, consistency='HIGH_CONSISTENCY' if cv is not None and cv<=.1 else 'HIGH_VOLATILITY' if cv is not None and cv>=.25 else None))
        weekly_tx, season_tx = transaction_totals([snapshot], tid), transaction_totals(weeks, tid)
        budget = snapshot.get('settings', {}).get('faab_budget')
        managers.append(dict(team_id=tid, team=team['name'], weekly=weekly_tx, season=season_tx, transactions_per_week=rounded(season_tx['transactions']/len(weeks)) if season_tx['transactions'] is not None else None, last_3_week_transactions=transaction_totals(weeks[-3:],tid)['transactions'], faab_remaining=team.get('faab_remaining'), faab_spending_rate=rounded(season_tx['faab_spent']/budget) if budget and season_tx['faab_spent'] is not None else None, roster_churn=season_tx['adds']+season_tx['drops'] if season_tx['available'] else None, waiver_success=None))
        for typ, condition, metric in [('STANDINGS_JUMP', change is not None and change>=2, change), ('STANDINGS_DROP', change is not None and change<=-2, change), ('WINNING_STREAK',last=='W' and streak>=3,streak), ('LOSING_STREAK',last=='L' and streak>=3,streak), ('SCORING_TREND_UP',trend=='UP',pct), ('SCORING_TREND_DOWN',trend=='DOWN',pct), ('ALL_PLAY_OVERPERFORMANCE',eligible>=3 and actual+actual_ties/2-exp>=1.5,actual+actual_ties/2-exp), ('ALL_PLAY_UNDERPERFORMANCE',eligible>=3 and actual+actual_ties/2-exp<=-1.5,actual+actual_ties/2-exp)]:
            if condition:
                events.append(dict(type=typ,team_id=tid,team=team['name'],value=rounded(metric)))
    matchups=[]
    for m in snapshot['matchups']:
        hid, aid = m['home_team_id'], m.get('away_team_id')
        if hid not in teams or (aid is not None and aid not in teams):
            raise ValueError('Unknown matchup participant')
        hs, ass = m['home_score'], m.get('away_score')
        if aid is not None and (ass is None or hid==aid):
            raise ValueError('Invalid matchup')
        tied = aid is not None and hs==ass
        winner = hid if aid is not None and hs>ass else aid if aid is not None and ass>hs else None
        loser = aid if winner==hid else hid if winner is not None else None
        entry=dict(id=str(m['id']),home_team_id=hid,away_team_id=aid,home_team=teams[hid]['name'],away_team=teams[aid]['name'] if aid else None,home_score=hs,away_score=ass,bye=aid is None,tied=tied,winner=teams[winner]['name'] if winner else None,loser=teams[loser]['name'] if loser else None,winner_team_id=winner,loser_team_id=loser,winner_score=scores[winner] if winner else None,loser_score=scores[loser] if loser else None,margin_of_victory=rounded(abs(hs-ass)) if aid else None,combined_score=rounded(hs+ass) if aid else None,winner_weekly_score_rank=ranks[winner] if winner else None,loser_weekly_score_rank=ranks[loser] if loser else None,winner_season_record={k:teams[winner][k] for k in ('wins','losses','ties')} if winner else None,loser_season_record={k:teams[loser][k] for k in ('wins','losses','ties')} if loser else None,home_roster=rosters.get(hid),away_roster=rosters.get(aid))
        for side in ('home','away'):
            projection=m.get(side+'_projected')
            entry[side+'_projected']=projection
            entry[side+'_difference_from_projection']=rounded(m[side+'_score']-projection) if m.get(side+'_score') is not None and projection is not None else None
        matchups.append(entry)
    games=[m for m in matchups if not m['bye']]
    for m in games:
        # Components each bounded to [0,1]; fixed weights sum to ten.
        closeness=1/(1+m['margin_of_victory']/10)
        combined=sum(g['combined_score']<=m['combined_score'] for g in games)/len(games)
        loss_context=(len(scores)-m['loser_weekly_score_rank'])/max(1,len(scores)-1) if m['loser'] else 0
        upset=bool(m['winner'] and m['home_projected'] is not None and m['away_projected'] is not None and (m['home_score']-m['away_score'])*(m['home_projected']-m['away_projected'])<0)
        m['interest_components']=dict(closeness=rounded(closeness),combined_percentile=rounded(combined),high_scoring_loss=rounded(loss_context),projection_upset=int(upset))
        m['interest_score']=rounded(4*closeness+2*combined+3*loss_context+int(upset))
        m['reasons']=['close finish'] if m['margin_of_victory']<=10 else []
        if combined>=.75: m['reasons'].append('high combined scoring')
        if loss_context>=.5: m['reasons'].append('high-scoring loss')
        if upset: m['reasons'].append('projection upset')
        if m['loser_score'] is not None and m['loser_score']>stats.median(values): events.append(dict(type='HIGH_SCORING_LOSS',team=m['loser'],score=m['loser_score'],weekly_score_rank=m['loser_weekly_score_rank'],opponent_score=m['winner_score']))
        if m['winner_score'] is not None and m['winner_score']<stats.median(values): events.append(dict(type='LOW_SCORING_WIN',team=m['winner'],score=m['winner_score']))
    top=[dict(m,rank=i+1) for i,m in enumerate(sorted(games,key=lambda m:(-m['interest_score'],m['id']))[:3])]
    closest=min(games,key=lambda m:(m['margin_of_victory'],m['id'])) if games else None
    blowout=max(games,key=lambda m:(m['margin_of_victory'],m['id'])) if games else None
    if closest: events.append(dict(type='CLOSEST_GAME',matchup_id=closest['id'],margin=closest['margin_of_victory']))
    if blowout and blowout['margin_of_victory']>=30: events.append(dict(type='LARGEST_BLOWOUT',matchup_id=blowout['id'],margin=blowout['margin_of_victory']))
    historical_scores=[v for s in weeks[:-1] for v in scores_for(s).values()]
    for tid, score in scores.items():
        if historical_scores and score>max(historical_scores): events.append(dict(type='SEASON_HIGH_SCORE' if coverage['history_complete'] else 'OBSERVED_HIGH_SCORE',team=teams[tid]['name'],score=score))
        if historical_scores and score<min(historical_scores): events.append(dict(type='SEASON_LOW_SCORE' if coverage['history_complete'] else 'OBSERVED_LOW_SCORE',team=teams[tid]['name'],score=score))
        rm=rosters.get(tid,{})
        if rm.get('points_left_on_bench') is not None and rm['points_left_on_bench']>=25: events.append(dict(type='BENCH_EXPLOSION',team=teams[tid]['name'],points_left_on_bench=rm['points_left_on_bench']))
        if rm.get('lineup_efficiency') is not None and rm['lineup_efficiency']<75: events.append(dict(type='LOW_LINEUP_EFFICIENCY',team=teams[tid]['name'],lineup_efficiency=rm['lineup_efficiency']))
    acquisitions = acquisition_metrics(weeks)
    for manager in managers:
        acquired=[a for a in acquisitions if a['team_id']==manager['team_id']]
        manager['acquisition_points']=rounded(sum(a['points_after_acquisition'] for a in acquired)) if all(a['points_after_acquisition'] is not None for a in acquired) else None
        manager['percentage_of_acquisitions_started']=rounded(100*sum(a['starts_after_acquisition']>0 for a in acquired)/len(acquired)) if acquired else None
    for t in snapshot.get('transactions',[]):
        budget=snapshot.get('settings',{}).get('faab_budget')
        if budget and t.get('faab_bid') is not None and t['faab_bid']>=budget*.2: events.append(dict(type='HIGH_FAAB_SPEND',team_id=t['team_id'],faab_bid=t['faab_bid']))
    weekly_averages=[dict(week=s['week'],average=rounded(stats.mean(scores_for(s).values()))) for s in weeks if scores_for(s)]
    result=dict(schema_version=1,season=snapshot['season'],week=snapshot['week'],source_snapshot=snapshot,league_summary=dict(league_id=snapshot['league_id'],league_name=snapshot['league_name'],team_count=len(teams),**coverage,warnings=snapshot.get('warnings',[])),weekly_scoring=dict(weekly_average_score=rounded(stats.mean(values)),weekly_median_score=rounded(stats.median(values)),weekly_standard_deviation=rounded(stats.pstdev(values)),highest_score=max(values),lowest_score=min(values),score_ranks=[dict(team_id=tid,team=teams[tid]['name'],score=v,rank=ranks[tid]) for tid,v in sorted(scores.items())],closest_matchup=closest['id'] if closest else None,largest_blowout=blowout['id'] if blowout else None,highest_combined_score=max(m['combined_score'] for m in games) if games else None,lowest_combined_score=min(m['combined_score'] for m in games) if games else None),standings=standings,top_matchups=top,all_matchups=matchups,transactions=dict(available=snapshot.get('availability',{}).get('transactions',False),items=snapshot.get('transactions',[]),by_team=[dict(team_id=m['team_id'],team=m['team'],weekly=m['weekly'],season=m['season']) for m in managers]),waiver_analysis=dict(acquisitions=acquisitions,history_complete=coverage['history_complete']),manager_analysis=managers,team_trends=trends,league_trends=dict(weekly_averages=weekly_averages,change_from_previous_week=rounded(weekly_averages[-1]['average']-weekly_averages[-2]['average']) if len(weekly_averages)>1 and weekly_averages[-2]['week']==snapshot['week']-1 else None,**coverage),all_play=all_play,expected_wins=expected,notable_events=events)
    validate_analysis(result)
    return result


def acquisition_metrics(weeks):
    results=[]
    for s in weeks:
        for tx in s.get('transactions',[]):
            if tx.get('player_added') is None or tx['type'] not in ('WAIVER','FREE_AGENT','ADD'):
                continue
            tid,pid=tx['team_id'],tx['player_added']
            started=benched=0.0; starts=bench_games=0; missing=False
            # Only weeks strictly after acquisition are attributable without kickoff timestamps.
            for later in weeks:
                if later['week']<=s['week']: continue
                if any(t.get('team_id')==tid and t.get('player_dropped')==pid for t in later.get('transactions',[])): break
                roster=next((r for r in later.get('rosters',[]) if r['team_id']==tid),None)
                if roster is None: missing=True; continue
                p=next((p for p in roster['players'] if p['id']==pid),None)
                if p is None: break
                if p.get('score') is None: missing=True; continue
                if p['starter']: started+=p['score']; starts+=1
                else: benched+=p['score']; bench_games+=1
            total=started+benched; cost=tx.get('faab_bid')
            results.append(dict(transaction_id=tx['id'],team_id=tid,player_id=pid,player_name=tx.get('player_name'),acquisition_week=s['week'],points_after_acquisition=rounded(total) if not missing else None,points_started=rounded(started) if not missing else None,points_benched=rounded(benched) if not missing else None,starts_after_acquisition=starts,bench_games_after_acquisition=bench_games,sample_count=starts+bench_games,percentage_of_acquired_points_started=rounded(100*started/total) if total>0 and not missing else None,faab_cost=cost,points_per_faab_dollar=rounded(total/cost) if cost is not None and cost>0 and not missing else None,missing_roster_data=missing))
    return results


def validate_analysis(analysis):
    required=('season','week','league_summary','weekly_scoring','standings','top_matchups','all_matchups','transactions','waiver_analysis','manager_analysis','team_trends','league_trends','all_play','expected_wins','notable_events','source_snapshot')
    if any(key not in analysis for key in required): raise ValueError('Missing analysis fields')
    def walk(obj):
        if isinstance(obj,float) and not math.isfinite(obj): raise ValueError('Nonfinite metric')
        if isinstance(obj,dict):
            for v in obj.values(): walk(v)
        if isinstance(obj,list):
            for v in obj: walk(v)
    walk(analysis)
    ids={t['id'] for t in analysis['source_snapshot']['teams']}
    for row in analysis['standings']:
        if row['team_id'] not in ids or any(row[k]<0 for k in ('wins','losses','ties')): raise ValueError('Invalid standings')
    for m in analysis['all_matchups']:
        if m['home_team_id'] not in ids or (m['away_team_id'] is not None and m['away_team_id'] not in ids): raise ValueError('Unknown matchup team')
        if not m['bye']:
            if abs(abs(m['home_score']-m['away_score'])-m['margin_of_victory'])>1e-6: raise ValueError('Inconsistent margin')
            expected=m['home_team_id'] if m['home_score']>m['away_score'] else m['away_team_id'] if m['away_score']>m['home_score'] else None
            if m['winner_team_id']!=expected: raise ValueError('Inconsistent winner')
    top=analysis['top_matchups']
    if [m['rank'] for m in top]!=list(range(1,len(top)+1)) or len({m['id'] for m in top})!=len(top): raise ValueError('Invalid top matchup ranking')
    for t in analysis['transactions']['items']:
        if t.get('team_id') is not None and t['team_id'] not in ids: raise ValueError('Unknown transaction team')
