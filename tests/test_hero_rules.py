import unittest
from types import SimpleNamespace as N
from test_micro_loot import unit,dist
from test_upgrades_portal import UpgradeGame
from undead.controller import Controller
from undead.economy import Economy
from undead.micro import Micro
from undead.policy import Action


class HeroRuleTests(unittest.TestCase):
    def test_lich_spends_level_points_in_user_order_and_disables_autocast(self):
        lich=unit('Ulic',1,0);levels={};learned=[];casts=[]
        def learn(hero,code):
            levels[code]=levels.get(code,0)+1;hero.skill_points-=1;learned.append(code);return True
        g=N(my_heroes=lambda:[lich],units=lambda *a:[],learn=learn,
            abilities=lambda h:[dict(code=c,level=n) for c,n in levels.items()],
            cast=lambda h,order:casts.append(order) or True)
        bot=Controller(g,lambda *a,**kw:None)
        for level in range(1,5):
            lich.level=level;lich.skill_points=1;bot.skills(level*10)
        self.assertEqual(learned,['AUfn','AUfu','AUfn','AUdr'])
        self.assertEqual(levels,{'AUfn':2,'AUfu':1,'AUdr':1})
        self.assertIn('frostarmoroff',casts);self.assertNotIn('frostarmoron',casts)

    def test_naga_learns_arrows_first_and_restores_autocast_after_revive(self):
        naga=unit('Nngs',1,0);naga.skill_points=1;own=[naga];levels={};casts=[]
        def learn(hero,code):levels[code]=1;hero.skill_points=0;return True
        g=N(my_heroes=lambda:own,units=lambda *a:[],learn=learn,
            abilities=lambda h:[dict(code=c,level=n) for c,n in levels.items()],
            cast=lambda h,order:casts.append(order) or True)
        bot=Controller(g,lambda *a,**kw:None,4);bot.skills(1)
        self.assertEqual(levels,{'ANfa':1});self.assertEqual(casts,['coldarrows'])
        own.clear();bot.skills(3);own.append(naga);bot.skills(4)
        self.assertEqual(casts,['coldarrows','coldarrows'])
        bot.skills(25);self.assertEqual(casts[-1],'coldarrows')

    def armor_game(self):
        lich=unit('Ulic',1,0);dk=unit('Udea',2,100,100);enemy=unit('ogru',3,200)
        dk.mana=0;enemy.owner=1;own=[lich,dk];casts=[];buffs={};events=[]
        g=N(dist=dist,me=lambda:0,is_building=lambda u:False,cooldown=lambda *a:0,
            abilities=lambda h:[dict(code='AUfu',level=1)],
            current_target=lambda e:dk if e is enemy else None,
            buffs=lambda u:buffs.get(u.handle,[]),unit=lambda h:next((u for u in own if u.handle==h),None),
            cast=lambda h,order,**kw:casts.append((h,order,kw.get('target'))) or True,
            attack=lambda *a,**kw:True)
        bot=Controller(g,lambda event,**kw:events.append((event,kw)))
        return bot,lich,dk,enemy,own,casts,buffs,events

    def test_melee_target_gets_armor_and_nova_does_not_cancel_it(self):
        b,l,d,e,own,casts,buffs,events=self.armor_game()
        b.frost_armor(own,[e],1);b.fight(own,[e],1)
        self.assertEqual([(order,target.type) for _,order,target in casts],[('frostarmor','Udea')])
        buffs[d.handle]=['BUfa'];b.frost_armor(own,[e],2)
        self.assertIn('frost_armor_observed',[event for event,_ in events])
        self.assertEqual(len([r for r in casts if r[1]=='frostarmor']),1)

    def test_ranged_or_distant_pursuit_does_not_spend_armor_mana(self):
        for code,x in [('earc',200),('ogru',800)]:
            with self.subTest(code=code,x=x):
                b,l,d,e,own,casts,_,_=self.armor_game();e.type=code;e.x=x
                b.frost_armor(own,[e],1);self.assertFalse(casts)

    def test_armor_prioritizes_wounded_hero_over_wounded_fiend(self):
        b,l,d,e,own,casts,_,_=self.armor_game()
        fiend=unit('ucry',5,150,10);own.append(fiend)
        other=unit('ogru',6,160);other.owner=1
        b.g.current_target=lambda x:fiend if x is other else d
        b.frost_armor(own,[e,other],1)
        self.assertIs(casts[0][2],d)

    def test_retreat_pullback_and_shield_keep_lich_moving(self):
        for protection in ('retreat','pullback','shield','casting','mana'):
            with self.subTest(protection=protection):
                b,l,d,e,own,casts,_,_=self.armor_game()
                if protection=='retreat':b.action=Action.RETREAT
                if protection=='pullback':b.micro.pulling.add(l.handle)
                if protection=='shield':b.shield_moves[l.handle]=(1000,0)
                if protection=='casting':b.cast_until[l.handle]=3
                if protection=='mana':l.mana=39
                b.frost_armor(own,[e],1);self.assertFalse(casts)

    def test_naga_cannot_wait_for_coil_when_targeted_at_low_health(self):
        dk=unit('Udea',1,0);naga=unit('Nngs',2,100,150);e=unit('ogru',3,200)
        micro=Micro(lambda *a,**kw:None)
        moves=micro.plan([dk,naga],[e],1,lambda _:naga.handle,dist,lambda *p:True,(-2000,0))
        self.assertIn(naga.handle,moves)
        g=N(units=lambda *a:[u for u in [dk,naga] if u.type in a[1]],dist=dist)
        self.assertFalse(Controller(g,lambda *a,**kw:None).heal_candidates(dk))

    def test_third_hero_hire_and_budget_follow_opponent(self):
        for race,expected in [(3,'Nbrn'),(4,'Nngs')]:
            with self.subTest(race=race):
                dk=unit('Udea',1,0,600);lich=unit('Ulic',2,0);tavern=unit('ntav',3,0);fiend=unit('ucry',4,0);buys=[]
                g=N(my_heroes=lambda:[dk,lich],dist=dist,path_distance=dist,
                    inventory=lambda h:['stwp','rnec'] if h is dk else ['ocor'],
                    units=lambda side,codes:[tavern] if codes=={'ntav'} else [],
                    resources=lambda:dict(gold=1000,lumber=500,food_cap=60,food_used=40),
                    nearest=lambda units,h:units[0],buy=lambda shop,c:buys.append(c) or N(reason=0),
                    use_item=lambda *a:True)
                b=Controller(g,lambda *a,**kw:None,race);b.home=N(x=0,y=0)
                g.all_production=lambda owner:[]
                b.economy.ready=lambda *a:[];b.situation.fiends=4;b.situation.statues=1
                b.recruit_tavern([dk,lich,fiend],[],10,3,set());self.assertEqual(buys,[expected])
                b.economy.ever_heroes.add(expected);b.recruit_tavern([dk,lich,fiend],[],20,3,set())
                self.assertEqual(buys,[expected])
                game=UpgradeGame()
                for u in game.own:
                    if u.type=='Nbrn':u.type=expected
                economy=Economy(lambda *a,**kw:None,expected)
                economy.ever_heroes={h.type for h in game.my_heroes()}
                game.gold=150;game.lumber=50
                self.assertTrue(economy.research_upgrades(game,1))
                self.assertEqual(game.commands,['Rura'])

if __name__=='__main__':unittest.main()
