import unittest
from review_opening_timing import analyze


class TimingReviewTests(unittest.TestCase):
    def test_separates_decision_foundation_and_actual_tier_observation(self):
        rows=[dict(event='purchase',clock=2,kind='build',code='uaod'),
              dict(event='home_foundation_observed',clock=17,code='uaod'),
              dict(event='purchase',clock=160,kind='train',code='unp1',accepted=True),
              dict(event='decision',clock=300,tier=2,heroes=[])]
        r=analyze(rows,{},'v1');self.assertEqual(r['baseline_status'],'not_calibrated')
        self.assertEqual(r['milestones']['build:uaod:1:foundation'],17)
        self.assertEqual(r['milestones']['tier:2:observed'],300)
        self.assertFalse(r['comparable_version']);self.assertFalse(r['deviations'])

    def test_deviation_retains_interference_and_version_caveats(self):
        baseline=dict(status='candidate',version='v1',milestones={'tier:2:observed':300})
        rows=[dict(event='player_contact_interrupt',clock=250),dict(event='decision',clock=390,tier=2,heroes=[])]
        r=analyze(rows,baseline,'v2');d=r['deviations'][0]
        self.assertEqual(d['delta'],90);self.assertTrue(d['interference_before_actual'])
        self.assertFalse(d['comparable_version']);self.assertEqual(d['priority'],'investigate')

    def test_failed_placement_retry_is_not_an_extra_actual_tower(self):
        rows=[dict(event='purchase',clock=404,kind='build',code='uzig'),
              dict(event='home_foundation_unconfirmed',clock=429,code='uzig'),
              dict(event='purchase',clock=429,kind='build',code='uzig'),
              dict(event='home_foundation_observed',clock=436,code='uzig')]
        report=analyze(rows,{},'v1');m=report['milestones']
        self.assertEqual(len(report['placement_failures']),1)
        self.assertEqual(m['build_attempt:uzig:2:decision'],429)
        self.assertEqual(m['build:uzig:1:foundation'],436)
        self.assertNotIn('build:uzig:2:foundation',m)


if __name__=='__main__':unittest.main()
