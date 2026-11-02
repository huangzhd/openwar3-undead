"""Owned real-time environment; rule control or explicit partial primitives.

observe() is a cached whitelist frame. The engine continues between calls.
Deadlines are cooperative API checkpoints, not an idle-client watchdog.
"""
import copy
import hashlib
import json
import math
import time
import uuid

from bootstrap import ROOT
from machine_start import active_processes
from practice_control import launch_lock
from run_guard import RunInterrupted
from undead.version import VERSION
from learning.evidence import safe_path, digest


class RuleEnvironment:
    def __init__(self, *, instance_id=None, cohort=None, control='rule'):
        if control not in ('rule', 'primitives'):raise ValueError('Unsupported control mode')
        self.control = control
        self.context = None
        if instance_id is not None:
            from learning.instance import InstanceContext
            self.context = InstanceContext(ROOT, instance_id, cohort)
        elif cohort is not None:raise ValueError('Cohort requires an explicit instance')
        self._registered = False
        self._generator = None
        self._frame = None
        self._result = None
        self._run_id = None
        self._token = None
        self._nonce = 0
        self._instance = uuid.uuid4().hex
        self._episode = None
        self._read_time = None
        self._lock = None
        self._broken = False

    def __enter__(self):return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:self.close()
        else:
            try:self.close()
            except BaseException:pass  # Preserve the caller's original exception.

    def _release(self):
        if self._lock is not None:
            if self._registered:
                self.context.release()
                self._registered = False
            lock, self._lock = self._lock, None
            lock.__exit__(None, None, None)

    def _cleanup_confirmed(self, result):
        if any(value for key, value in result.items()
               if key.endswith('cleanup_error') or key == 'evidence_error'):
            return False
        try:
            saved = json.loads((ROOT/'artifacts'/self._run_id/'result.json').read_text(encoding='utf-8'))
            if any(value for key,value in saved.items()
                   if key.endswith('cleanup_error') or key == 'evidence_error'):return False
            audit = json.loads((ROOT/'artifacts'/self._run_id/'source-audit.json').read_text(encoding='utf-8'))
            if self.context and (audit.get('process_scope') != 'owned_instance'
                    or audit.get('instance_id') != self.context.instance_id
                    or audit.get('cohort') != self.context.cohort
                    or not self.context.cleaned()):return False
            return (audit.get('source_unchanged') is True and audit.get('session_closed') is True
                    and audit.get('active_processes') == [] and audit.get('errors') == []
                    and (self.context.processes() if self.context else active_processes()) == [])
        except Exception:return False  # Unknown process/audit state never proves cleanup.

    def _same_revision(self):
        """Recheck actual current bytes before a subsequent launch, under the lock."""
        try:
            folder=ROOT/'artifacts'/self._run_id
            manifest=json.loads((folder/'source-manifest.json').read_text(encoding='utf-8'))
            contract=json.loads((folder/'interface-contract.json').read_text(encoding='utf-8'))
            dependencies=contract.get('dependencies')
            if (not isinstance(manifest,dict) or not manifest or not isinstance(dependencies,dict)
                    or not dependencies or contract.get('dependency_errors') != []):return False
            expected=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if contract.get('source_manifest_sha256') != expected:return False
            return all(digest(safe_path(ROOT,name)) == expected_hash
                       for entries in (manifest,dependencies) for name,expected_hash in entries.items())
        except (OSError,ValueError,TypeError,AttributeError):return False

    def _accept_frame(self, frame):
        if (not isinstance(frame, dict) or frame.get('player') != 1
                or type(frame.get('pid')) is not int or frame['pid'] <= 0
                or type(frame.get('epoch')) is not int or frame['epoch'] <= 0
                or not isinstance(frame.get('observation'), dict)
                or frame['observation'].get('player') != 1):
            raise RuntimeError('Invalid environment frame')
        run_id = frame.get('run_id')
        if not isinstance(run_id, str) or not run_id or any(c in run_id for c in '/\\:') or run_id in ('.','..'):
            raise RuntimeError('Invalid environment run identity')
        if self._frame is not None and any(frame.get(k) != self._frame.get(k)
                                           for k in ('run_id','pid','epoch','player')):
            raise RuntimeError('Environment frame identity changed')
        if self.control == 'primitives':
            from learning.actions import SCHEMA,checked_bounds
            context=frame.get('action_context')
            if not isinstance(context,dict) or context.get('schema') != SCHEMA:
                raise RuntimeError('Primitive action context missing or changed')
            checked_bounds(context.get('bounds'))
        self._run_id = run_id
        self._frame = copy.deepcopy(frame)
        self._read_time = time.time()
        self._nonce += 1
        self._token = dict(instance=self._instance, episode=self._episode, nonce=self._nonce,
                           **{k:frame[k] for k in ('run_id','pid','epoch','player','observation_id')})

    def _finish(self, result):
        self._generator = None
        self._broken = True
        if not isinstance(result, dict):raise RuntimeError('Missing environment result')
        run_id = result.get('id')
        if (not isinstance(run_id,str) or not run_id or any(c in run_id for c in '/\\:')
                or run_id in ('.','..') or self._run_id is not None and run_id != self._run_id):
            raise RuntimeError('Environment result identity changed')
        self._run_id = run_id
        final = result.get('environment_final_frame')
        if final is not None:self._accept_frame(final)
        confirmed = self._cleanup_confirmed(result)
        termination = result.get('termination', {})
        self._result = dict(run_id=run_id, cleanup_confirmed=confirmed,
                            termination={k:copy.deepcopy(termination.get(k)) for k in
                                ('schema','classification','outcome','reason','terminated','truncated','reward')})
        self._token = None
        if confirmed:
            self._broken = False
            self._release()
        return self.observe()

    def _failure(self):
        self._broken = True
        self._token = None
        generator, self._generator = self._generator, None
        if generator is not None:
            try:generator.close()
            except BaseException:pass
        # Keep the single-instance lock when cleanup cannot be established.

    def reset(self, map_alias='LR', opponent='kfai-human', seed=None, policy_version=VERSION,
              game_seconds=60, wall_seconds=180, until=None):
        if map_alias != 'LR' or opponent != 'kfai-human' or policy_version != VERSION:
            raise ValueError('Only the current LR/KFAI rule baseline is supported')
        if seed is not None:raise ValueError('Deterministic engine seeds are not supported')
        for value in (game_seconds, wall_seconds):
            if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
                raise ValueError('Episode limits must be finite and positive')
        if until is not None and (type(until) not in (int,float) or not math.isfinite(until) or until <= time.time()):
            raise ValueError('Absolute deadline must be in the future')
        self.close()
        if self._broken or self._result is not None and not self._result['cleanup_confirmed']:
            raise RuntimeError('Previous environment cleanup is unconfirmed')
        lock = launch_lock(self.context.lock if self.context else ROOT/'artifacts'/'learning-environment.lock')
        lock.__enter__()
        self._lock = lock
        try:
            if (ROOT/'artifacts'/'STOP').exists():raise RuntimeError('STOP blocks environment reset')
            if self.context:
                if self.context.stop.exists():raise RuntimeError('Instance STOP blocks environment reset')
                if self._result is not None and not self._cleanup_confirmed(self._result):
                    raise RuntimeError('Previous environment audit changed or is missing')
                self.context.register()
                self._registered = True
            elif active_processes():raise RuntimeError('An active game blocks environment reset')
            # Re-read the previous audit at reset, not only at its earlier close.
            if self._result is not None and not self._cleanup_confirmed(self._result):
                raise RuntimeError('Previous environment audit changed or is missing')
            if self._result is not None and not self._same_revision():
                raise RuntimeError('Previous environment source or dependencies changed or are missing')
            from run_match import _match_steps
            self._episode = uuid.uuid4().hex
            self._frame = self._result = self._run_id = self._token = None
            deadline = time.time()+wall_seconds
            if until is not None:deadline = min(deadline, until)
            self._generator = _match_steps(sparring=opponent, map_alias=map_alias, speed=400,
                trajectory=True, step_mode=True, max_game_seconds=game_seconds, until=deadline,
                **({'control':self.control} if self.control != 'rule' else {}),
                **({'instance_context':self.context} if self.context else {}))
        except BaseException:
            self._release()
            raise
        try:
            self._accept_frame(next(self._generator))
            return self.observe()
        except StopIteration as stop:return self._finish(stop.value)
        except BaseException:
            self._failure()
            raise

    def observe(self, player=1):
        if type(player) is not int or player != 1:raise ValueError('Only P1 observations are exposed')
        return copy.deepcopy(dict(observation=self._frame.get('observation') if self._frame else None,
            token=self._token, receipts=self._frame.get('receipts',[]) if self._frame else [],
            **({key:self._frame.get(key) if self._frame else None for key in
                ('action_context','action_receipts')} if self.control == 'primitives' else {}),
            cached=True, read_time=self._read_time, done=self._result is not None,
            termination=self._result['termination'] if self._result else None))

    def step(self, action):
        expected = {'kind','token'} if self.control == 'rule' else {'kind','token','action'}
        kind = 'rule_tick' if self.control == 'rule' else 'primitive'
        if (self._generator is None or self._broken or not isinstance(action,dict)
                or set(action) != expected or action['kind'] != kind
                or self._token is None or action['token'] != self._token):
            raise ValueError('Expected a fresh bound '+kind+' action')
        command = 'rule_tick'
        if self.control == 'primitives':
            from learning.actions import validate
            command = validate(action['action'])
        self._token = None  # Consume before touching the engine, including failures.
        try:
            self._accept_frame(self._generator.send(command))
            return self.observe()
        except StopIteration as stop:return self._finish(stop.value)
        except BaseException:
            self._failure()
            raise

    def result(self):return copy.deepcopy(self._result)

    def preflight(self, actions):
        """Cached candidate checks, not a complete legal-action mask or reservation."""
        if self.control != 'primitives' or self._token is None:
            raise ValueError('An active primitive environment is required')
        if type(actions) is not list or len(actions) > 64:
            raise ValueError('Expected at most 64 candidates')
        from learning.actions import preflight
        output = []
        for action in actions:
            try:reason = preflight(action, self._frame['observation'], self._frame['action_context']['bounds'])
            except ValueError:reason = 'invalid_schema'
            output.append(dict(allowed=reason == 'allowed', reason=reason, cached=True))
        return output

    def close(self):
        if self._generator is None:return self.result()
        clock = self._frame['observation'].get('clock') if self._frame else None
        self._token = None
        try:
            self._generator.throw(RunInterrupted('environment_close', clock))
        except StopIteration as stop:
            self._finish(stop.value)
            return self.result()
        except BaseException:
            self._failure()
            raise
        self._failure()
        raise RuntimeError('Environment ignored close request')
