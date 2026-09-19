"""Exact maximum-weight assignment of players to eligible lineup slots."""
from functools import lru_cache


def roster_metrics(players, lineup_slots):
    starters = [p for p in players if p.get('starter')]
    bench = [p for p in players if not p.get('starter')]
    def total(group):
        return sum(p['score'] for p in group) if group and all(p.get('score') is not None for p in group) else None
    def extreme(group, reverse):
        valid = [p for p in group if p.get('score') is not None]
        return sorted(valid, key=lambda p: ((-1 if reverse else 1)*p['score'], p['id']))[0] if valid else None
    result = dict(starter_points=total(starters), bench_points=total(bench), highest_scoring_player=extreme(players, True), lowest_scoring_starter=extreme(starters, False), highest_scoring_bench_player=extreme(bench, True), optimal_lineup_score=None, points_left_on_bench=None, lineup_efficiency=None)
    slots = [int(k) for k, n in lineup_slots.items() if int(k) not in (20, 21) for _ in range(n)]
    if not slots or not players or any(p.get('score') is None for p in players):
        return result
    # DP over occupied slot masks: O(players * slots * 2**slots).
    # Each player is considered once; this avoids illegal duplicate selections.
    dp = {0: 0.0}
    for player in players:
        nxt = dict(dp)
        for mask, score in dp.items():
            for i, slot in enumerate(slots):
                if not mask & (1 << i) and slot in player.get('eligible_slots', []):
                    new = mask | (1 << i)
                    nxt[new] = max(nxt.get(new, float('-inf')), score + player['score'])
        dp = nxt
    optimum = dp.get((1 << len(slots))-1)
    if optimum is not None:
        result['optimal_lineup_score'] = round(optimum, 4)
        if result['starter_points'] is not None and optimum >= result['starter_points'] - 1e-7:
            result['points_left_on_bench'] = round(optimum-result['starter_points'], 4)
            if optimum > 0:
                result['lineup_efficiency'] = round(100*result['starter_points']/optimum, 4)
    return result
