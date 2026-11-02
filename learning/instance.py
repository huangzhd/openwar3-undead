"""Explicit ownership for up to four experimental local environments."""
import json
import re
import time
from contextlib import contextmanager

import psutil

from attach_match import atomic_json, read_atomic_json
from practice_control import launch_lock
from session import Session

INSTANCE_IDS = (81, 82, 83, 84)


class InstanceContext:
    def __init__(self, root, instance_id, cohort):
        if type(instance_id) is not int or instance_id not in INSTANCE_IDS:
            raise ValueError('Experimental instance must be in 81..84')
        if not isinstance(cohort, str) or not re.fullmatch(r'[0-9a-f]{32}', cohort):
            raise ValueError('A 32-character cohort UUID is required')
        self.root, self.instance_id, self.cohort = root, instance_id, cohort
        self.directory = root/'artifacts'/'instances'/str(instance_id)
        self.record = self.directory/'session.json'
        self.owner = self.directory/'owner.json'
        self.lock = self.directory/'environment.lock'
        self.stop = self.directory/'STOP'

    def processes(self):
        record = read_atomic_json(self.record)
        return [row for row in record['processes'] if Session.matches(row)]

    def cleaned(self):
        record = read_atomic_json(self.record)
        return record.get('closed') is True and record.get('processes') == []

    def register(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.record.exists() and self.processes():
            raise RuntimeError('Instance still owns live processes')
        if self.owner.exists():
            owner = read_atomic_json(self.owner)
            if not owner.get('closed') and Session.matches(owner['worker']):
                raise RuntimeError('Instance still has an active worker')
        process = psutil.Process()
        # SDK initialization sets a process-wide WAR3_PID; two engines must not
        # share a Python worker even though their file/OS channels are separate.
        for path in (self.root/'artifacts'/'instances').glob('*/owner.json'):
            owner = read_atomic_json(path)
            if (not owner.get('closed') and owner['worker']['pid'] == process.pid
                    and Session.matches(owner['worker'])):
                raise RuntimeError('Use a separate Python worker for each instance')
        atomic_json(self.record, dict(processes=[], closed=True))
        atomic_json(self.owner, dict(instance_id=self.instance_id, cohort=self.cohort, closed=False,
            worker=dict(pid=process.pid, created=process.create_time(), name=process.name())))

    def release(self):
        owner = read_atomic_json(self.owner)
        if owner['cohort'] != self.cohort or owner['worker']['pid'] != psutil.Process().pid:
            raise RuntimeError('Instance ownership changed')
        atomic_json(self.owner, {**owner, 'closed': True})

    def foreign_processes(self):
        from machine_start import active_processes
        allowed = set()
        for instance_id in INSTANCE_IDS:
            directory = self.root/'artifacts'/'instances'/str(instance_id)
            path = directory/'owner.json'
            if not path.exists():continue
            owner = read_atomic_json(path)
            if (owner.get('closed') or owner.get('cohort') != self.cohort
                    or owner.get('instance_id') != instance_id
                    or not Session.matches(owner['worker'])):continue
            allowed.add(owner['worker']['pid'])
            record = read_atomic_json(directory/'session.json')
            allowed.update(row['pid'] for row in record['processes'] if Session.matches(row))
        return [row for row in active_processes() if row['pid'] not in allowed]

    @contextmanager
    def launching(self, until):
        # Map generation/staging, registry video settings and launcher setup share
        # machine resources. Serialize startup only; existing games keep stepping.
        deadline = min(until or float('inf'), time.time()+125)
        lock = launch_lock(self.root/'artifacts'/'learning-launch.lock')
        while True:
            if (self.root/'artifacts'/'STOP').exists() or self.stop.exists():
                raise RuntimeError('STOP blocks instance launch')
            if time.time() >= deadline:raise TimeoutError('Instance launch lock deadline')
            try:
                lock.__enter__()
                break
            except RuntimeError:
                time.sleep(.1)
                lock = launch_lock(self.root/'artifacts'/'learning-launch.lock')
        try:
            if self.foreign_processes():raise RuntimeError('Unrelated active game/session blocks launch')
            yield
        finally:lock.__exit__(None, None, None)
