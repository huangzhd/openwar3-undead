"""A real .164 run exhausted recovery before the skill row disappeared."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import test_hero_spell_recovery_01164 as recovery
from undead.game_view import SDKGame


class SpellBudgetTests(unittest.TestCase):
    def test_normal_orders_cannot_spend_missing_spell_budget_for_any_hero(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/lich_nova_budget_012301.json').read_text(encoding='utf-8'))
        count=max(r.get('unconfirmed_attempts',0) for r in fixture['events'])
        self.assertEqual(count,12)
        for kind,code,spell,cooldown in (
            ('Ulic','AUfn','frostnova',8),('Nngs','ANfl','forkedlightning',11),
            ('Nbrn','ANsi','silence',15),('Udea','AUdc','deathcoil',6)):
            for accepted in (False,True):
                with self.subTest(kind=kind,accepted=accepted):
                    g,h,e,own,t,orders,logs=recovery.HeroSpellRecoveryTests().scene()
                    own[:]=[h]
                    h.type=kind;h.mana=500
                    h.abilities=[N(code=code,level=1,cooldown=0,flags=0)]
                    with patch.object(SDKGame,'cast',return_value=accepted):
                        for _ in range(count):
                            self.assertEqual(bool(g.cast(h,spell,target=e)),accepted)
                            t[0]+=4
                            g.observe_coil(own,t[0],lambda event,**kw:logs.append(dict(event=event,**kw)))
                    h.abilities=[N(code='AIar',level=1,cooldown=0,flags=0)]
                    h.items[0]='afac'
                    ready=lambda:g.coil_ready(h) if code=='AUdc' else g.hero_spell_ready(h,code)
                    self.assertFalse(ready())
                    t[0]+=cooldown+3
                    # Recovery starts with its own full budget; it still stops at
                    # three attempts without expenditure, even on accepted orders.
                    with patch.object(SDKGame,'cast',return_value=True) as send:
                        for _ in range(3):
                            self.assertTrue(ready())
                            self.assertTrue(g.cast(h,spell,target=e))
                            t[0]+=cooldown+3
                        self.assertFalse(ready())
                        self.assertFalse(g.cast(h,spell,target=e))
                        self.assertEqual(send.call_count,3)
                    self.assertIsNone(g.cooldown(h,code))
                    self.assertIn('afac',g.inventory(h))


if __name__=='__main__':unittest.main()
