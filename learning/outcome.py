"""Versioned terminal semantics shared by evidence and passive trajectories.

This pure projection never changes the original result or exception evidence.
Only the independent referee's confirmed natural result earns a win/loss reward.
"""

SCHEMA = 'dayuan-outcome-v1'
NATURAL = {'win': 'all_enemy_buildings_destroyed',
           'loss': 'all_own_buildings_destroyed'}
USER_ABORT = ('user_stop', 'manual_restart', 'manual_surrender', 'environment_close')
TIME_LIMIT = ('game_time_limit', 'automation_deadline')
EPOCH_CHANGED = ('game_epoch_changed', 'practice_match_changed')
SAFE_REASONS = (*NATURAL.values(), *USER_ABORT, *TIME_LIMIT, *EPOCH_CHANGED,
                'human_game_closed', 'stage_time_limit')


def classify_outcome(outcome, reason, *, natural_confirmed=False):
    natural = (natural_confirmed is True and outcome in NATURAL
               and reason == NATURAL[outcome])
    if natural:
        classification = 'natural_terminal'
    elif outcome == 'error' or reason == 'stage_time_limit':
        classification = 'runtime_failure'
    elif reason in USER_ABORT:
        classification = 'user_abort'
    elif reason in TIME_LIMIT:
        classification = 'time_limit'
    elif reason == 'human_game_closed':
        classification = 'process_exit'
    elif reason in EPOCH_CHANGED:
        classification = 'epoch_changed'
    else:
        classification = 'incomplete'
    return dict(schema=SCHEMA, classification=classification,
                outcome=outcome if outcome in ('win', 'loss', 'timeout', 'aborted', 'error') else 'unknown',
                reason=reason if reason in SAFE_REASONS else 'other',
                terminated=natural, truncated=not natural,
                reward=(1 if outcome == 'win' else -1) if natural else None)
