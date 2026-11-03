"""Offline command-frequency diagnostics for an audited rule-teacher episode."""
from collections import Counter, defaultdict
from decimal import Decimal


def review_requests(requests, retained):
    previous = {}
    totals = Counter()
    rapid = Counter()
    same_tick = Counter()
    per_tick = defaultdict(list)
    examples = defaultdict(list)
    for request in requests:
        if request['id'] not in retained:
            # An omitted request may hide its issuing unit. Never compare across it.
            previous.clear()
            continue
        action = request['candidate']
        op = action['op']
        unit = tuple(action['unit'])
        tick = request['tick']
        totals[op] += 1
        per_tick[op, tick].append(unit)
        prior = previous.get(unit)
        previous[unit] = request
        if prior is None or prior['candidate'] != action:
            continue
        elapsed = Decimal(str(request['clock'])) - Decimal(str(prior['clock']))
        if 0 <= elapsed <= 2:
            rapid[op] += 1
            same_tick[op] += int(prior['tick'] == tick)
            if len(examples[op]) < 3:
                examples[op].append(dict(previous_request=prior['id'], request=request['id'],
                                         previous_tick=prior['tick'], tick=tick,
                                         previous_clock=prior['clock'], clock=request['clock']))

    operations = {}
    for op in sorted(totals):
        groups = [units for (operation, _), units in per_tick.items() if operation == op]
        operations[op] = dict(accepted_labels=totals[op], ticks=len(groups),
                              multi_unit_ticks=sum(len(set(units)) > 1 for units in groups),
                              max_distinct_units_in_tick=max(len(set(units)) for units in groups),
                              same_unit_extra_orders_in_tick=sum(len(units)-len(set(units)) for units in groups),
                              rapid_exact_reissues=rapid[op], rapid_exact_within_tick=same_tick[op],
                              examples=examples[op])
    return dict(schema='dayuan-rule-order-review-v1', dataset_use='diagnostic_only',
                behavior_quality='unreviewed', positive_demonstrations_approved=False,
                interval_seconds_inclusive=2, clock_basis='issue_observation_game_seconds',
                barriers='all_excluded_requests', operations=operations)
