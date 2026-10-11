from __future__ import annotations

import json
from pathlib import Path

PALETTE = Path(r'D:\YAN_AGENT_LAB\docs\recon\generated\fact_grounded_palette.json')


def main() -> None:
    data = json.loads(PALETTE.read_text(encoding='utf-8'))
    slots = data['slots']

    def ids(role: str) -> set[str]:
        return {row['id'] for row in slots.get(role, [])}

    bulk = ids('structural') | ids('floor')
    shaped = ids('stairs') | ids('slab') | ids('wall') | ids('fence') | ids('gate') | ids('door')

    overlap = sorted(bulk & shaped)
    if overlap:
        raise SystemExit('FAIL shaped blocks leaked into bulk roles: ' + ', '.join(overlap[:20]))

    bad_decor = [x for x in ids('decor') if x.endswith('_leaves') or 'tripwire_hook' in x]
    if bad_decor:
        raise SystemExit('FAIL bad passive decor: ' + ', '.join(sorted(bad_decor)))

    print('PALETTE ROLE QA: PASS')
    print('bulk:', len(bulk))
    print('shaped:', len(shaped))
    print('decor:', len(ids('decor')))


if __name__ == '__main__':
    main()
