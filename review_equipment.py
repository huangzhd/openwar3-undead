"""Offline equipment evidence; receipts alone never count as completed transfers."""
import json,sys
from pathlib import Path
from collections import Counter
from undead.equipment import LICH_ITEMS


def review(run):
    rows=[json.loads(l) for l in (run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    confirmed=[r for r in rows if r['event']=='equipment_transfer_confirmed']
    bags=[];full_without_orb=[]
    for r in rows:
        if r['event']!='summary':continue
        lich=next((h for h in r['heroes'] if h['type']=='Ulic'),None)
        if not lich or lich.get('inventory') is None:continue
        bag=lich['inventory'];sample=dict(clock=r['clock'],inventory=bag)
        bags.append(sample)
        if len(bag)==6 and None not in bag and 'ocor' not in bag:full_without_orb.append(sample)
    result=dict(run=run.name,confirmed_transfers=confirmed,
                transfer_counts=dict(Counter(r['code'] for r in confirmed)),
                unconfirmed_transfers=sum(r['event']=='equipment_transfer_unconfirmed' for r in rows),
                lich_inventory_samples=bags,full_without_orb_samples=full_without_orb,
                orb_observed=any('ocor' in s['inventory'] for s in bags),
                priority_items_observed=sorted({c for s in bags for c in s['inventory'] if c in LICH_ITEMS}),
                limitations=['Inventory summaries are sampled every 15 game seconds',
                             'Equipment transfer confirmation requires both sender and recipient inventory changes'])
    (run/'equipment-review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'confirmed_transfers','lich_inventory_samples','full_without_orb_samples','limitations'}},ensure_ascii=False))
    print(json.dumps(dict(full_without_orb_samples=len(full_without_orb))))
    return result


if __name__=='__main__':
    for name in sys.argv[1:]:review(Path('artifacts')/name)
