import copy
import json
import statistics
import unittest
from pathlib import Path

from src.analytics.engine import analyze, validate_analysis, transaction_totals
from src.analytics.roster_analysis import roster_metrics


def fixture():
    return json.loads((Path(__file__).parent/'fixtures/demo_week_01.json').read_text())


class AnalyticsTests(unittest.TestCase):
    def test_scores_margins_rank_and_population_stats(self):
        result=analyze(fixture(),[])
        scoring=result['weekly_scoring']
        self.assertEqual(scoring['weekly_average_score'],110)
        self.assertEqual(scoring['weekly_median_score'],110)
        self.assertAlmostEqual(scoring['weekly_standard_deviation'],round(statistics.pstdev([150,145,120,100,80,65]),4))
        self.assertEqual(result['all_matchups'][0]['margin_of_victory'],5)
        self.assertEqual(result['all_matchups'][0]['winner'],'Lakefront Legends')
        self.assertEqual(result['all_matchups'][0]['loser_weekly_score_rank'],2)
        self.assertEqual(len(result['top_matchups']),3)
        self.assertEqual(result['top_matchups'][0]['id'],'1')
        self.assertEqual(result,analyze(fixture(),[]))
        self.assertIn('HIGH_SCORING_LOSS',[e['type'] for e in result['notable_events']])

    def test_all_play_expected_wins(self):
        result=analyze(fixture(),[])
        self.assertEqual(result['all_play'][0]['all_play_wins'],5)
        self.assertEqual(result['all_play'][1]['all_play_losses'],1)
        self.assertEqual(result['expected_wins'][1]['expected_wins'],.8)
        self.assertEqual(result['expected_wins'][1]['actual_minus_expected'],-.8)
        self.assertEqual(sum(r['expected_wins'] for r in result['expected_wins']),3)

    def test_ties_competition_rank_and_win_credit(self):
        s=fixture();s['matchups'][0]['away_score']=150
        result=analyze(s,[])
        self.assertTrue(result['all_matchups'][0]['tied'])
        self.assertIsNone(result['all_matchups'][0]['winner'])
        self.assertEqual([r['rank'] for r in result['weekly_scoring']['score_ranks']][:3],[1,1,3])
        self.assertEqual(result['all_play'][0]['all_play_ties'],1)
        self.assertEqual(result['expected_wins'][0]['actual_win_equivalents'],.5)
        self.assertEqual(result['expected_wins'][0]['expected_wins'],.9)

    def test_bye_not_head_to_head_win_or_top_matchup(self):
        s=fixture();s['matchups'][0].update(away_team_id=None,away_score=None)
        result=analyze(s,[])
        self.assertEqual(len(result['top_matchups']),2)
        self.assertEqual(result['expected_wins'][0]['sample_count'],0)
        self.assertEqual(result['expected_wins'][0]['expected_wins'],0)
        self.assertEqual(result['all_play'][0]['all_play_wins'],4)

    def test_standings_history_and_partial_expected(self):
        old=fixture();s=copy.deepcopy(old);s['week']=2
        old['teams'][0]['rank']=3;s['teams'][0]['rank']=1
        result=analyze(s,[old])
        self.assertEqual(result['standings'][0]['rank_change'],2)
        self.assertTrue(result['standings'][0]['new_first_place'])
        self.assertTrue(result['league_summary']['history_complete'])
        s['week']=4
        result=analyze(s,[old])
        self.assertIsNone(result['standings'][0]['rank_change'])
        self.assertFalse(result['league_summary']['history_complete'])
        self.assertEqual(result['expected_wins'][0]['sample_count'],2)
        self.assertEqual(result['standings'][0]['winning_streak'],1)

    def test_transaction_grouping_and_missing_faab(self):
        s=fixture();tx=s['transactions'][0];tx['transaction_id']='combined'
        s['transactions'].append(dict(tx,id='drop',type='DROP',player_added=None,player_dropped=999,faab_bid=None))
        totals=transaction_totals([s],1)
        self.assertEqual(totals['transactions'],1)
        self.assertEqual(totals['adds'],1)
        self.assertEqual(totals['drops'],1)
        self.assertEqual(totals['faab_spent'],25)
        tx['faab_bid']=None
        self.assertIsNone(transaction_totals([s],1)['faab_spent'])
        s['availability']['transactions']=False
        self.assertIsNone(transaction_totals([s],1)['transactions'])

    def test_optimal_lineup_uses_matching_not_greedy(self):
        players=[dict(id=1,name='Flexible',score=30,eligible_slots=[2,23],starter=True),dict(id=2,name='Only RB',score=29,eligible_slots=[2],starter=False),dict(id=3,name='Only Flex',score=1,eligible_slots=[23],starter=True)]
        result=roster_metrics(players,{'2':1,'23':1,'20':9})
        self.assertEqual(result['optimal_lineup_score'],59)
        self.assertEqual(result['points_left_on_bench'],28)
        self.assertEqual(result['lineup_efficiency'],round(31/59*100,4))
        players[1]['score']=None
        self.assertIsNone(roster_metrics(players,{'2':1,'23':1})['optimal_lineup_score'])

    def test_impossible_lineup_and_negative_score(self):
        players=[dict(id=1,name='QB',score=-2,eligible_slots=[0],starter=True)]
        self.assertIsNone(roster_metrics(players,{'0':2})['optimal_lineup_score'])
        result=roster_metrics(players,{'0':1})
        self.assertEqual(result['optimal_lineup_score'],-2)
        self.assertIsNone(result['lineup_efficiency'])

    def test_acquisition_after_week_and_free_cost(self):
        old=fixture();s=copy.deepcopy(old);s['week']=2;s['transactions']=[]
        player=old['transactions'][0]['player_added']
        s['rosters'][0]['players'][0]['id']=player
        result=analyze(s,[old]);acq=result['waiver_analysis']['acquisitions'][0]
        self.assertEqual(acq['sample_count'],1)
        self.assertEqual(acq['points_after_acquisition'],30)
        self.assertEqual(acq['points_per_faab_dollar'],1.2)
        old['transactions'][0]['faab_bid']=0
        self.assertIsNone(analyze(s,[old])['waiver_analysis']['acquisitions'][0]['points_per_faab_dollar'])

    def test_trend_requires_six_observations(self):
        history=[]
        for week in range(1,7):
            s=fixture();s['week']=week;s['matchups'][0]['home_score']=100 if week<=3 else 150
            history.append(s)
        self.assertEqual(analyze(history[-1],history[:-1])['team_trends'][0]['scoring_change_pct'],50)
        self.assertEqual(analyze(history[-1],history[:-1])['team_trends'][0]['trend'],'UP')
        self.assertIsNone(analyze(history[3],history[:3])['team_trends'][0]['trend'])

    def test_validation_rejects_corruption(self):
        result=analyze(fixture(),[]);result['all_matchups'][0]['winner_team_id']=2
        with self.assertRaises(ValueError):validate_analysis(result)
        result=analyze(fixture(),[]);result['top_matchups'][1]['rank']=1
        with self.assertRaises(ValueError):validate_analysis(result)
        result=analyze(fixture(),[]);result['weekly_scoring']['highest_score']=float('nan')
        with self.assertRaises(ValueError):validate_analysis(result)
        s=fixture();s['transactions'][0]['team_id']=100
        with self.assertRaises(ValueError):analyze(s,[])


if __name__=='__main__':unittest.main()
