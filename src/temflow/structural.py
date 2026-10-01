"""Evidence-conditioned and prospective mass-flow uncertainty.

Nested accounting groups use the structural tree law. Crossing groups use
independent linear programs and explicit missing-record enumeration. Accounting
groups are never inferred from the display road network.
"""
from __future__ import annotations

import csv
import io
import json
import math
from itertools import combinations
from collections.abc import Mapping

import numpy as np
from scipy.optimize import linprog
from ._structural_tree import NestedLedger, Record
from ._version import VERSION

FORMULATION = 'TEMFLOW_STRUCTURAL_2026_10_01'
_CONTEXT = ('source', 'commodity', 'mass_unit', 'period_start', 'period_end')


def _number(value, name, nonnegative=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a number')
    value = float(value)
    if not math.isfinite(value) or (nonnegative and value < 0):
        raise ValueError(f'{name} must be finite' + (' and nonnegative' if nonnegative else ''))
    return value


def _names(value, name):
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f'{name} must be a nonempty list of names')
    if len(set(value)) != len(value):
        raise ValueError(f'{name} contains duplicate names')
    return value


def _validated(payload):
    if not isinstance(payload, Mapping):
        raise ValueError('structural_problem must be an object')
    allowed = {'total_mass', 'destinations', 'records', 'missing_record_budget', 'context',
               'known_missing_record_ids', 'unallocated_destination', 'schema', 'include_witnesses'}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError('Unsupported fields (additional constraints must use the general ERR solver): ' + ', '.join(sorted(unknown)))
    if payload.get('schema', 'temflow.aggregate.v1') != 'temflow.aggregate.v1':
        raise ValueError('Unsupported aggregate schema')
    M = _number(payload.get('total_mass'), 'total_mass')
    names = _names(payload.get('destinations'), 'destinations')
    context = payload.get('context')
    if not isinstance(context, Mapping) or any(not isinstance(context.get(k), str) or not context[k].strip() for k in _CONTEXT):
        raise ValueError('context requires source, commodity, mass_unit, period_start and period_end')
    from datetime import date
    try:
        start, end = (date.fromisoformat(context[k]) for k in ('period_start', 'period_end'))
    except ValueError as e:
        raise ValueError('Use YYYY-MM-DD for the accounting period') from e
    if end < start:
        raise ValueError('period_end precedes period_start')
    unallocated = payload.get('unallocated_destination')
    if unallocated is not None and unallocated not in names:
        raise ValueError('unallocated_destination must be included in destinations')
    budget = payload.get('missing_record_budget', 0)
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError('missing_record_budget must be a nonnegative integer')
    raw_records = payload.get('records', [])
    if not isinstance(raw_records, list):
        raise ValueError('records must be a list')
    records, ids = [], set()
    for i, row in enumerate(raw_records):
        if not isinstance(row, Mapping):
            raise ValueError(f'Record {i + 1} must be an object')
        extra = set(row) - {'id', 'destinations', 'error', 'value', 'observed_on', 'provenance'}
        if extra:
            raise ValueError('Unsupported record fields: ' + ', '.join(sorted(extra)))
        rid = row.get('id')
        if not isinstance(rid, str) or not rid.strip() or rid in ids:
            raise ValueError('Each independently acquired record needs a unique nonempty id')
        group = _names(row.get('destinations'), f'{rid} destinations')
        if set(group) - set(names):
            raise ValueError(f'{rid} names an unknown destination')
        error = _number(row.get('error'), f'{rid} error')
        value = None if row.get('value') is None else _number(row['value'], f'{rid} value', False)
        if row.get('observed_on'):
            try: date.fromisoformat(row['observed_on'])
            except (TypeError, ValueError) as e: raise ValueError(f'{rid} observed_on must be YYYY-MM-DD') from e
        records.append({**row, 'id': rid, 'destinations': group, 'error': error, 'value': value})
        ids.add(rid)
    missing = payload.get('known_missing_record_ids', [])
    if not isinstance(missing, list) or any(not isinstance(x, str) for x in missing) or len(set(missing)) != len(missing) or set(missing) - ids:
        raise ValueError('known_missing_record_ids must list unique existing record ids')
    available = [row for row in records if row['id'] not in missing]
    if budget > len(available):
        raise ValueError('missing_record_budget exceeds the number of available records')
    # Explicit computational limits, not statistical assumptions. Other cases
    # remain representable in the general ERR interface.
    if len(names) > 10000 or len(records) > 50000 or (len(names) + len(records) + 1) * (budget + 1)**2 > 10000000:
        raise ValueError('Requested profile exceeds the interactive calculation limit; reduce the budget or accounting problem size')
    if not isinstance(payload.get('include_witnesses', False), bool):
        raise ValueError('include_witnesses must be true or false')
    return M, names, records, available, budget, dict(context), missing


def _accounting_tree(names, records, mass):
    whole = frozenset(names)
    groups = {frozenset(r['destinations']) for r in records} | {frozenset([x]) for x in names} | {whole}
    for a, b in combinations(groups, 2):
        if a & b and not (a <= b or b <= a):
            return None
    ordered = [whole] + sorted(groups - {whole}, key=lambda s: (-len(s), sorted(s)))
    # Keep a separate root when the accounting system has one destination.
    if len(names) == 1:
        return NestedLedger([names[0]], [], [0], [], mass), {0: names[0]}, []
    index = {g: i for i, g in enumerate(ordered)}
    edges, edge_index = [], {}
    for g in ordered[1:]:
        parent = min((h for h in groups if g < h), key=lambda h: (len(h), sorted(h)))
        edge_index[g] = len(edges)
        edges.append((index[parent], index[g]))
    terminal_names = {index[frozenset([x])]: x for x in names}
    informative = [r for r in records if frozenset(r['destinations']) != whole]
    tree_records = [Record(r['id'], edge_index[frozenset(r['destinations'])], r['error']) for r in informative]
    return NestedLedger([f'group-{i}' for i in range(len(ordered))], edges, list(terminal_names), tree_records, mass), terminal_names, informative


def _solve_lp(c, A, b, Aeq, beq):
    result = linprog(c, A_ub=A if len(A) else None, b_ub=b if len(b) else None,
                     A_eq=Aeq, b_eq=beq, bounds=(0, None), method='highs')
    if result.status == 2: return None
    if not result.success: raise ValueError('Linear calculation failed: ' + result.message)
    return result


def _conditional(names, records, mass):
    missing_values = [r['id'] for r in records if r['value'] is None]
    if missing_values:
        return {'status': 'readings_required', 'record_ids': missing_values,
                'explanation': 'Enter every available reading or declare its record missing; no reading is silently dropped.'}
    L = len(names)
    if L > 500:
        return {'status': 'not_computed', 'explanation': 'Conditional calculation exceeds the interactive limit of 500 destinations. Prospective tree profiles can still be calculated.'}
    A, b = [], []
    for r in records:
        row = [int(x in r['destinations']) for x in names]
        A += [row, [-x for x in row]]
        b += [r['value'] + r['error'], r['error'] - r['value']]
    feasible = _solve_lp(np.zeros(L), A, b, [np.ones(L)], [mass])
    if feasible is None:
        return {'status': 'infeasible', 'explanation': 'The entered readings, error bounds and exact total are incompatible. No destination range is reported.'}
    bounds = {}
    for j, name in enumerate(names):
        c = np.eye(1, L, j).ravel()
        low, high = (_solve_lp(s*c, A, b, [np.ones(L)], [mass]) for s in (1, -1))
        bounds[name] = {'lower': max(0., float(low.fun)), 'upper': min(mass, float(-high.fun))}
    return {'status': 'ok', 'meaning': 'Sharp ranges for the entered readings and known missing records', 'bounds': bounds}


def _general_profiles(names, records, mass, budget):
    L, m = len(names), len(records)
    count = sum(math.comb(m, k) for k in range(budget + 1))
    if count * L > 20000 or L > 200:
        return {'status': 'not_computed', 'method': 'general_difference_linear_program',
                'reason': 'Crossing groups exceed the explicit enumeration limit (200 destinations or 20,000 target/set calculations). Conditional ranges remain available.'}
    widths = {name: [0.] * (budget + 1) for name in names}
    Aeq = np.zeros((2, 2*L)); Aeq[0, :L] = 1; Aeq[1, L:] = 1
    rows = [[int(x in r['destinations']) for x in names] for r in records]
    for k in range(budget + 1):
        for erased in combinations(range(m), k):
            A, b = [], []
            for i, r in enumerate(records):
                if i in erased: continue
                row = rows[i] + [-x for x in rows[i]]
                A += [row, [-x for x in row]]; b += [2*r['error']] * 2
            for j, name in enumerate(names):
                c = np.zeros(2*L); c[j] = -1; c[L+j] = 1
                result = _solve_lp(c, A, b, Aeq, [mass, mass])
                widths[name][k] = max(widths[name][k], min(mass, max(0., float(-result.fun))))
    return {'status': 'ok', 'method': 'general_difference_linear_program', 'widths': widths,
            'enumerated_missing_sets': count}


def run_structural_payload(payload):
    """Shared scientific entry point for CLI, HTTP and desktop calculations."""
    M, names, records, available, budget, context, missing = _validated(payload)
    conditional = _conditional(names, available, M)
    tree = _accounting_tree(names, available, M)
    if tree is None:
        prospective = _general_profiles(names, available, M, budget)
        structure = 'crossing_groups'
    else:
        ledger, labels, informative = tree
        calc = ledger.profiles(budget)
        prospective = {'status': 'ok', 'method': 'nested_group_tree_law',
                       'widths': {labels[k]: v for k, v in calc['widths'].items()},
                       'accounting_nodes': ledger.n, 'informative_records': len(informative)}
        if payload.get('include_witnesses', False):
            if len(names)**2 * (budget + 1) > 200000:
                raise ValueError('Witness output is too large; set include_witnesses to false')
            prospective['witnesses'] = {labels[t]: [ledger.witness(t, k, calc) for k in range(budget + 1)] for t in ledger.terminals}
            prospective['witness_destination_order'] = [labels[t] for t in ledger.terminals]
            prospective['witness_record_order'] = [r.id for r in ledger.records]
        structure = 'nested_groups'
    prospective['missing_record_budgets'] = list(range(budget + 1))
    prospective['meaning'] = 'Worst possible range over compatible readings, after up to this many additional records become unavailable; not a confidence interval or the range for current readings'
    prospective['conditional_on_known_missing_record_ids'] = missing
    return {'status': 'ok', 'engine_version': VERSION, 'formulation': FORMULATION, 'context': context,
            'total_mass': M, 'structure': structure, 'conditional': conditional, 'prospective': prospective,
            'assumptions': ['Exact source total remains known', 'Nonnegative destination masses sum to that total',
                            'No extra allocation constraints', 'Each reading has its own absolute error bound',
                            'Missing record identities are known; copied reports are not independent records'],
            'boundary': 'The accounting hierarchy does not alter or establish geographic routes.'}


def structural_csv_to_payload(text):
    """Plain table input: one aggregate measurement per row, | separates names."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
    if not rows: raise ValueError('CSV contains no records')
    common = ('total_mass', 'destinations', 'missing_record_budget', *_CONTEXT)
    fields = set(common) | {'record_id', 'group_destinations', 'error', 'value', 'observed_on', 'provenance'}
    if set(rows[0]) != fields:
        raise ValueError('Use the aggregate-record CSV template with its complete, unchanged column names')
    if any(any(row[k] != rows[0][k] for k in common) for row in rows):
        raise ValueError('All rows must have the same source, commodity, period, unit, exact total, destination list and budget')
    def split(value): return [v.strip() for v in value.split('|')]
    try:
        p = {'total_mass': float(rows[0]['total_mass']), 'destinations': split(rows[0]['destinations']),
             'missing_record_budget': int(rows[0]['missing_record_budget']),
             'context': {k: rows[0][k] for k in _CONTEXT},
             'records': [{'id': r['record_id'], 'destinations': split(r['group_destinations']),
                          'error': float(r['error']), 'value': float(r['value']) if r['value'].strip() else None,
                          'observed_on': r['observed_on'], 'provenance': r['provenance']} for r in rows]}
    except (TypeError, ValueError) as e:
        raise ValueError('Check the numeric cells and separator in the aggregate-record CSV') from e
    _validated(p)
    return p


def load_structural_file(path):
    from pathlib import Path
    p = Path(path)
    text = p.read_text(encoding='utf-8-sig')
    return structural_csv_to_payload(text) if p.suffix.lower() == '.csv' else json.loads(text)
