import unittest
from types import SimpleNamespace as N
from undead.destroyer import Destroyer
from undead.controller import Controller
from undead.economy import Economy
from undead.army_recovery import ArmyRecovery
from undead.policy import Action
from test_baseline import unit
from test_micro_loot import dist
import test_growth_expansion_0149 as growth
import test_economy_timing_01131 as timing


class DestroyerTests(unittest.TestCase):
    def scene(self):
        own=[unit('uobs',i,owner=0,x=0) for i in (1,2,3)]
        for u,m in zip(own,(300,10,180)):u.mana=m;u.has_detail=True
        foe=unit('efon',10,owner=1,x=450);foes=[foe];orders=[];events=[];cd={}
        res=dict(gold=300,lumber=200,food_used=47,food_cap=50)
        g=N(me=lambda:0,dist=dist,units=lambda owner,types:[u for u in own if u.type in types],
            unit=lambda h:next((u for u in own+foes if u.handle==h),None),
            resources=lambda:res,tech_many=lambda codes:{'Rusp':1},buffs=lambda u:[],
            cooldown=lambda u,c:cd.get((u.handle,c),0),
            cast=lambda u,c,**kw:orders.append((u.handle,c,kw)) or True,
            move=lambda u,*p:orders.append((u.handle,'move',p)) or True)
        b=N(g=g,action=Action.ATTACK,teleport=None,cast_until={},last={},
            economy=N(third_hero='Nngs',ever_heroes={'Udea','Ulic','Nngs'},upkeep_released=False))
        d=Destroyer(lambda ev,**kw:events.append(dict(event=ev,**kw)))
        return g,b,d,own,foes,orders,events,cd,res

    def test_lowest_mana_morph_is_observed_before_next_orders_and_cannot_duplicate(self):
        g,b,d,own,foes,orders,events,cd,res=self.scene()
        d.tick(b,own,foes,10)
        self.assertEqual(orders,[(own[1].handle,'avengerform',{})])
        Controller.go_raw(b,[own[1]],(100,100),11)
        d.tick(b,own,foes,11);self.assertEqual(len(orders),1)
        own[1].type='ubsp';own[1].mana=0;res['food_used']=49
        d.tick(b,own,foes,13)
        self.assertEqual(orders[-1][1],'devourmagic')
        self.assertTrue(any(e['event']=='destroyer_morph_confirmed' for e in events))
        d.tick(b,own,foes,14)
        self.assertEqual(sum(o[1]=='avengerform' for o in orders),1)

    def test_hidden_neutral_non_summon_retreat_unknown_research_and_food_block_morph(self):
        for why in ('hidden','neutral','ordinary','retreat','unknown','food','funds','blocked'):
            with self.subTest(why=why):
                g,b,d,own,foes,orders,events,cd,res=self.scene();blocked=set()
                if why=='hidden':foes[0].visible_to=lambda me:False
                if why=='neutral':foes[0].owner=12
                if why=='ordinary':foes[0].type='earc'
                if why=='retreat':b.action=Action.RETREAT
                if why=='unknown':g.tech_many=lambda c:{'Rusp':None}
                if why=='food':res['food_used']=49
                if why=='funds':res['gold']=99
                if why=='blocked':blocked={u.handle for u in own}
                d.tick(b,own,foes,10,blocked);self.assertFalse(orders)

    def test_unconfirmed_morph_has_three_attempt_limit_and_no_false_success(self):
        g,b,d,own,foes,orders,events,cd,res=self.scene();own[:]=[own[1]]
        for now in (10,19,28,37,46):d.tick(b,own,foes,now)
        self.assertEqual(len(orders),3);self.assertTrue(all(o[1]=='avengerform' for o in orders))
        self.assertFalse(any(e['event']=='destroyer_morph_confirmed' for e in events))

    def test_dispel_selects_cluster_and_confirms_cooldown_without_claiming_hidden_deaths(self):
        g,b,d,own,foes,orders,events,cd,res=self.scene();own[0].type='ubsp'
        foes[:]=[unit('efon',i,owner=1,x=x) for i,x in ((10,100),(11,450),(12,500))]
        d.tick(b,own,foes,10);self.assertEqual(orders[-1][2],dict(x=450,y=0))
        Controller.go_raw(b,[own[0]],(1000,0),10.5);self.assertEqual(len(orders),1)
        cd[(own[0].handle,'Advm')]=6;foes[1].hp=20;foes[2].visible_to=lambda me:False
        d.tick(b,own,foes,11)
        event=next(e for e in events if e['event']=='destroyer_dispel_cast_observed')
        self.assertEqual(event['targets'],[dict(handle=foes[1].handle,hp_before=100,hp_after=20,alive=True)])
        self.assertEqual(len(orders),1)

    def test_out_of_range_or_cast_blocked_does_not_chase_or_disrupt_retreat(self):
        for why in ('range','blocked','cooldown'):
            g,b,d,own,foes,orders,events,cd,res=self.scene();own[0].type='ubsp';blocked=set()
            if why=='range':foes[0].x=650
            if why=='blocked':blocked.add(own[0].handle)
            if why=='cooldown':cd[(own[0].handle,'Advm')]=4
            d.tick(b,own,foes,10,blocked);self.assertFalse(orders)

    def test_failed_dispel_stops_after_three_unconfirmed_attempts(self):
        g,b,d,own,foes,orders,events,cd,res=self.scene();own[0].type='ubsp'
        for now in (10,14,18,22,26):d.tick(b,own,foes,now)
        self.assertEqual(len(orders),3)
        self.assertFalse(any(e['event']=='destroyer_dispel_cast_observed' for e in events))

    def test_transforming_mana_statue_restores_one_life_and_one_mana_support(self):
        g,b,d,own,foes,orders,events,cd,res=self.scene()
        support=ArmyRecovery(lambda *a,**kw:None);support.statues(b,5)
        self.assertEqual(support.statue_modes[own[1].handle]['mode'],'mana')
        d.tick(b,own,foes,10);own[1].type='ubsp'
        support.statues(b,14)
        self.assertEqual({s['mode'] for s in support.statue_modes.values()},{'life','mana'})
        self.assertEqual(orders[-1],(own[2].handle,'replenishmanaon',{}))


class DestroyerEconomyTests(unittest.TestCase):
    def scene(self):
        g=growth.GrowthGame();g.food=44;g.cap=50;g.gold=600;g.lumber=500
        fiends=g.units('me',{'ucry'});g.own=[u for u in g.own if u not in fiends[4:] and u.type!='ubsp']
        g.levels['Rusp']=0;g.costs['Rusp']=(75,150)
        e=Economy(lambda *a,**kw:None);e.ever_heroes={h.type for h in g.my_heroes()}
        return g,e

    def test_tier_three_research_then_spare_statue_then_morph_restores_two_supports(self):
        g,e=self.scene();e.tick(g,500)
        self.assertEqual(g.commands,['Rusp']);self.assertEqual((g.gold,g.lumber),(525,350))
        house=g.my_buildings({'uslh'})[0]
        e.tick(g,504);self.assertEqual(g.commands,['Rusp'])
        self.assertEqual(g.builds[-1][1],'uzig') # Third hero exists: next supply may build.
        g.cap=60
        g.busy.pop(house.handle);g.levels['Rusp']=1;e.tick(g,565)
        self.assertEqual(g.commands,['Rusp','uobs']);self.assertEqual(g.food,47)
        g.busy.pop(house.handle);g.own.append(unit('ubsp',995,owner=0));g.food=49
        self.assertEqual(e.army_targets(g,570),(4,2))
        g.own.remove(g.units('me',{'uobs'})[0]);g.food=46;g.gold=200
        e.tick(g,574);self.assertEqual(g.commands[-1],'uobs');self.assertEqual(g.food,49)

    def test_research_waits_for_tier_three_and_unknown_is_not_completed(self):
        for tier,level in ((2,0),(3,None)):
            g,e=self.scene();g.own[0].type='unp1' if tier==2 else 'unp2';g.levels['Rusp']=level
            if tier==2:g.busy[g.own[0].handle]=N(kind='upgrade',queue=['unp2'])
            e.tick(g,500);self.assertNotIn('Rusp',g.commands)

    def test_research_rejections_are_bounded(self):
        g,e=self.scene();g.can_do=lambda *a:183;events=[];e.log=lambda ev,**kw:events.append(ev)
        house=g.my_buildings({'uslh'})
        for now in (500,505,510,515,520):e.research_destroyer(g,house,now)
        self.assertFalse(g.commands);self.assertEqual(events.count('destroyer_research_attempt'),3)

    def test_third_fiend_waits_for_both_tech_and_lich_payment(self):
        g,e=timing.TransitionBudgetTests().game(2);g.gold=1600;g.lumber=900
        fiends=g.units('me',{'ucry'});g.own=[u for u in g.own if u not in fiends[2:]]
        crypt=g.my_buildings({'usep'})[0]
        self.assertFalse(e.train(g,crypt,'ucry',290))
        e.tick(g,300);self.assertEqual(g.commands,['unp2'])
        g.busy[g.own[0].handle]=N(kind='upgrade',queue=['unp2'])
        self.assertFalse(e.train(g,crypt,'ucry',302))
        e.tick(g,304);self.assertEqual(g.commands,['unp2','Ulic'])
        self.assertTrue(e.train(g,crypt,'ucry',308));self.assertEqual(g.commands[-1],'ucry')

    def test_fifth_tower_waits_for_observed_third_hero_not_hire_queue(self):
        g,e=self.scene();g.own=[u for u in g.own if u.type!='Nbrn'];e.ever_heroes.discard('Nbrn')
        while len(g.my_buildings({'uzig'}))<4:g.own.append(unit('uzig',900+len(g.own),owner=0))
        g.busy[g.my_buildings({'uaod'})[0].handle]=N(kind='queue',queue=['Nbrn'])
        self.assertFalse(e.build(g,'uzig',g.own[0],500));self.assertFalse(g.builds)
        g.own.append(unit('Nbrn',998,owner=0));e.save_for_trade=True;e.tick(g,504)
        self.assertTrue(e.build(g,'uzig',g.own[0],508));self.assertEqual(g.builds[-1][1],'uzig')

    def test_four_fiend_limit_and_two_food_reserve_leave_room_to_morph(self):
        g,e=self.scene();e.mass_army=True;g.levels['Rusp']=1;g.food=47
        self.assertFalse(e.train(g,g.my_buildings({'usep'})[0],'ucry',500))
        self.assertFalse(e.train(g,g.my_buildings({'uslh'})[0],'uobs',500))
        self.assertFalse(g.commands);self.assertEqual(g.food,47)


if __name__=='__main__':unittest.main()
