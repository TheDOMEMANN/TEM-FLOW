"""Dated, reversible changes to active topology; frozen inputs are untouched."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from uuid import uuid4

from .curation import _datetime


class FeatureChangeStore:
    def __init__(self, directory: Path | str):
        self.path = Path(directory) / 'feature_changes.jsonl'
        self._lock = threading.Lock()

    def events(self):
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                event = json.loads(line)
                if event['action'] not in {'remove', 'restore'}:
                    raise ValueError('invalid feature change action')
                _datetime(event['effective_at'])
                _datetime(event['entered_at'])
                events.append(event)
        return events

    def removed(self, as_of=None):
        cutoff = _datetime(as_of) if as_of else datetime.now(timezone.utc)
        latest = {}
        for index, event in enumerate(self.events()):
            effective = _datetime(event['effective_at'])
            if effective > cutoff:
                continue
            key = (effective, _datetime(event['entered_at']), index)
            for target in event['targets']:
                identity = (target['object_kind'], target['object_id'])
                if identity not in latest or key > latest[identity][0]:
                    latest[identity] = (key, event, target)
        return {identity: {'event': event, 'target': target}
                for identity, (_, event, target) in latest.items() if event['action'] == 'remove'}

    def append(self, plan, *, actor, provenance, change_reason):
        for label, value in [('actor', actor), ('provenance', provenance), ('change_reason', change_reason)]:
            if not str(value).strip():
                raise ValueError(f'{label} is required')
        if not plan['can_apply'] or not plan['targets']:
            raise ValueError('feature change plan cannot be applied')
        event = {
            'event_id': 'FEATURE_' + uuid4().hex.upper(),
            'action': plan['action'], 'effective_at': plan['effective_at'],
            'entered_at': datetime.now(timezone.utc).isoformat(),
            'actor': actor, 'provenance': provenance, 'change_reason': change_reason,
            'targets': plan['targets'], 'plan_id': plan['plan_id'],
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
                handle.flush()
        return event

    def digest(self):
        return hashlib.sha256(self.path.read_bytes() if self.path.exists() else b'').hexdigest()


def change_plan(payload, nodes, routes, store, registry_digest):
    """Resolve the exact affected objects before a curator applies the change."""
    action = str(payload.get('action', 'remove'))
    if action not in {'remove', 'restore'}:
        raise ValueError('action must be remove or restore')
    effective = str(payload.get('effective_at', '')).strip()
    _datetime(effective)
    raw_targets = payload.get('targets')
    if not isinstance(raw_targets, list) or not 1 <= len(raw_targets) <= 2000:
        raise ValueError('select between 1 and 2000 features')
    requested = set()
    for item in raw_targets:
        if not isinstance(item, dict):
            raise ValueError('each target must identify an object kind and ID')
        identity = (str(item.get('object_kind', '')), str(item.get('object_id', '')))
        source = nodes if identity[0] == 'node' else routes if identity[0] == 'route' else {}
        if identity[1] not in source:
            raise ValueError(f'feature is unknown or not yet effective: {identity[1]}')
        requested.add(identity)
    removed = store.removed(effective)
    for identity in requested:
        if (identity in removed) != (action == 'restore'):
            raise ValueError(f'feature is already {"removed" if action == "remove" else "active"}: {identity[1]}')
    chosen_nodes = {oid for kind, oid in requested if kind == 'node'}
    connected = set()
    if action == 'remove':
        for rid, route in routes.items():
            if {route.get('from_node_id'), route.get('to_node_id')} & chosen_nodes and ('route', rid) not in removed:
                connected.add(('route', rid))
    implicit = connected - requested
    targets = requested | (implicit if payload.get('include_connected_routes') is True else set())
    blockers = []
    if implicit and payload.get('include_connected_routes') is not True:
        blockers.append(f'Include the {len(implicit)} connected routes before removing these nodes.')
    if action == 'restore':
        for kind, oid in targets:
            if kind == 'route':
                for endpoint in (routes[oid].get('from_node_id'), routes[oid].get('to_node_id')):
                    if endpoint not in nodes or (('node', endpoint) in removed and ('node', endpoint) not in targets):
                        blockers.append(f'Restore endpoint node {endpoint} with route {oid}.')
    def describe(identity):
        kind, oid = identity
        value = (nodes if kind == 'node' else routes)[oid]
        name = value.get('name') or f"{value.get('from_name', value.get('from_node_id', ''))} → {value.get('to_name', value.get('to_node_id', ''))}"
        return {'object_kind': kind, 'object_id': oid, 'name': name,
                'country': value.get('country', ''), 'connected_route': identity in implicit}
    plan = {'action': action, 'effective_at': effective, 'targets': [describe(item) for item in sorted(targets)],
            'connected_routes': [describe(item) for item in sorted(implicit)],
            'can_apply': not blockers, 'blockers': sorted(set(blockers)), 'frozen_register_modified': False}
    signed = {'plan': plan, 'changes_digest': store.digest(), 'registry_digest': registry_digest}
    plan['plan_id'] = hashlib.sha256(json.dumps(signed, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return plan
