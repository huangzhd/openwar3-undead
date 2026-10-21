import unittest
import test_destroyer_01139 as old
from test_baseline import unit
from undead.destroyer import HERO_DEBUFFS,ENEMY_BUFFS
from undead.policy import Action


class DispelPriorityTests(unittest.TestCase):
    def scene(self,destroyer=True):
        g,b,d,own,foes,orders,events,cd,res=old.DestroyerTests().scene()
        if destroyer:own[0].type='ubsp'
        hero=unit('Udea',20,owner=0,x=-400);hero.has_detail=True;own.append(hero)
        enemy=unit('ogru',21,owner=1,x=400);enemy.has_detail=True;foes.append(enemy)
        effects={hero.handle:['BOhx'],enemy.handle:['Bblo']}
        g.buffs=lambda u:effects.get(u.handle,[])
        g.my_heroes=lambda:[hero]
        return g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy

    def test_hero_hex_beats_summons_and_enemy_buffs(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        d.tick(b,own,foes,10)
        self.assertEqual(orders[-1][2],dict(x=hero.x,y=hero.y))
        self.assertEqual(events[-1]['reason'],'ally_hex')

    def test_summons_beat_buff_then_buff_alone_is_dispelled(self):
        for summon in (True,False):
            g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
            effects[hero.handle]=[]
            if not summon:foes[:]=[enemy]
            d.tick(b,own,foes,10)
            self.assertEqual(events[-1]['reason'],'enemy_summon' if summon else 'enemy_buff')

    def test_each_supported_debuff_triggers_morph_without_enemies(self):
        for effect in HERO_DEBUFFS:
            with self.subTest(effect=effect):
                g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene(False)
                effects[hero.handle]=[effect];foes.clear();b.action=Action.CREEP
                d.tick(b,own,[],10)
                self.assertEqual(orders[-1][1],'avengerform')
                self.assertEqual(events[-1]['trigger_priority'],0 if effect=='BOhx' else 2)

    def test_each_supported_enemy_buff_triggers_morph_without_summons(self):
        for effect in ENEMY_BUFFS:
            with self.subTest(effect=effect):
                g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene(False)
                effects[hero.handle]=[];effects[enemy.handle]=[effect];foes[:]=[enemy]
                d.tick(b,own,foes,10)
                self.assertEqual(orders[-1][1],'avengerform')
                self.assertEqual(events[-1]['trigger_priority'],3)

    def test_auras_poison_stun_invulnerability_and_unknown_do_not_trigger(self):
        for effect in ('BHab','BUau','Bpoi','BPSE','Bprg','BHds','Bvul','BNdo','Bzzz'):
            g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
            effects[hero.handle]=[effect];effects[enemy.handle]=[effect];foes[:]=[enemy]
            d.tick(b,own,foes,10);self.assertFalse(orders)

    def test_hidden_or_unknown_detail_enemy_buff_does_not_trigger(self):
        for hidden in (True,False):
            g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
            effects[hero.handle]=[];foes[:]=[enemy]
            if hidden:enemy.visible_to=lambda me:False
            else:enemy.has_detail=False
            d.tick(b,own,foes,10);self.assertFalse(orders)

    def test_blocked_hero_outside_army_still_gets_dispelled(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        d.tick(b,[u for u in own if u!=hero],[],10,{hero.handle})
        self.assertEqual(events[-1]['reason'],'ally_hex')

    def test_existing_destroyer_can_free_hero_on_retreat_without_new_morph(self):
        for existing in (True,False):
            g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene(existing)
            b.action=Action.RETREAT;d.tick(b,own,foes,10)
            self.assertEqual(bool(orders),existing)
            if existing:self.assertEqual(events[-1]['reason'],'ally_hex')

    def test_range_and_caster_pullback_still_block_cast(self):
        for why in ('range','pull','cooldown'):
            g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
            foes.clear();blocked=set()
            if why=='range':hero.x=2000
            if why=='pull':blocked={own[0].handle}
            if why=='cooldown':cd[(own[0].handle,'Advm')]=5
            d.tick(b,own,foes,10,blocked);self.assertFalse(orders)

    def test_cooldown_receipt_and_observed_buff_removal_are_separate(self):
        for removed in (True,False):
            g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
            d.tick(b,own,foes,10);cd[(own[0].handle,'Advm')]=7
            if removed:effects[hero.handle]=[]
            d.observe(b,11)
            event=events[-1];self.assertEqual(event['event'],'destroyer_dispel_cast_observed')
            self.assertEqual(event['effects'][0]['absent'],['BOhx'] if removed else [])

    def test_spell_immune_infernal_is_not_a_dispel_target(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        effects.clear();foes[:]=[foes[0]];foes[0].type='ninf'
        d.tick(b,own,foes,10);self.assertFalse(orders)

    def test_exhausted_target_does_not_block_other_actionable_dispels(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        d.attempts[(own[0].handle,hero.handle)]=3
        d.tick(b,own,foes,10)
        self.assertEqual(events[-1]['reason'],'enemy_summon')

    def test_enemy_hero_buff_is_dispelled_until_silence_is_present(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        effects[hero.handle]=[];foes[:]=[enemy]
        enemy.type='Otch';enemy.is_hero=True
        effects[enemy.handle]=['Broa']
        d.tick(b,own,foes,10)
        self.assertEqual(events[-1]['reason'],'enemy_buff')

        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        effects[hero.handle]=[];foes[:]=[enemy]
        enemy.type='Otch';enemy.is_hero=True
        effects[enemy.handle]=['Broa','BNsi']
        d.tick(b,own,foes,10)
        self.assertFalse(orders)

    def test_blast_does_not_strip_enemy_silence_near_summon(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        effects[hero.handle]=[]
        chief=unit('Otch',22,owner=1,x=foes[0].x+60);chief.has_detail=True
        foes[:]=[foes[0],chief];effects[chief.handle]=['BNsi']
        d.tick(b,own,foes,10)
        self.assertFalse(orders)
        chief.x=1500
        d.tick(b,own,foes,11)
        self.assertEqual(events[-1]['reason'],'enemy_summon')

    def test_safe_summon_can_be_dispelled_when_other_cluster_is_protected(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        effects[hero.handle]=[]
        safe=unit('efon',23,owner=1,x=-350)
        chief=unit('Otch',22,owner=1,x=foes[0].x+60);chief.has_detail=True
        foes[:]=[foes[0],safe,chief];effects[chief.handle]=['BNsi']
        d.tick(b,own,foes,10)
        self.assertEqual(orders[-1][2],dict(x=safe.x,y=safe.y))

    def test_blast_does_not_strip_friendly_hero_frost_armor(self):
        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        effects[hero.handle]=['BOhx','BUfa'];foes.clear()
        d.tick(b,own,foes,10)
        self.assertEqual(events[-1]['reason'],'ally_hex') # Freeing Hex outranks retaining this hero's armor.

        g,b,d,own,foes,orders,events,cd,res,effects,hero,enemy=self.scene()
        effects[hero.handle]=['BUfa'];hero.x=foes[0].x+60
        foes[:]=[foes[0]]
        d.tick(b,own,foes,10)
        self.assertFalse(orders)


if __name__=='__main__':unittest.main()
