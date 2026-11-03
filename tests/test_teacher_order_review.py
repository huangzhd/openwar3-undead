import unittest

from learning.teacher_order_review import review_requests


class TeacherOrderReviewTests(unittest.TestCase):
    def test_separates_units_targets_gaps_and_time_boundaries(self):
        def order(i, unit, clock, tick, x=32):
            return dict(id=i, clock=clock, tick=tick,
                        candidate=dict(op='move', unit=[unit, unit+1], x=x, y=64))

        requests = [order(1, 8, 5.1, 1), order(2, 10, 5.2, 1),
                    order(3, 8, 7.1, 2), order(4, 8, 7.1, 2, x=0),
                    order(5, 8, 7.1, 2, x=0), dict(id=6),
                    order(7, 8, 7.2, 3, x=0), order(8, 8, 9.201, 4, x=0)]
        result = review_requests(requests, {1, 2, 3, 4, 5, 7, 8})['operations']['move']
        self.assertEqual([(e['previous_request'], e['request']) for e in result['examples']], [(1, 3), (4, 5)])
        self.assertEqual(result['rapid_exact_reissues'], 2)
        self.assertEqual(result['rapid_exact_within_tick'], 1)
        self.assertEqual(result['multi_unit_ticks'], 1)
        self.assertEqual(result['same_unit_extra_orders_in_tick'], 2)
