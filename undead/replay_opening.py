"""User-requested LR openings, independently transcribed from two replays.

These are command destinations, not measured completed foundations or a unit
position trace. See docs/LR_REPLAY_OPENING.md for provenance and limitations.
Never mirror this template onto another spawn or address a replay object ID.
"""
REFERENCE_SHA256='7d858deddb81f49815d274bd188190c7a0b3df1c65a61be6fd0280fb8b7279e1'
LR_NE_HOME=(3840,3328)
LR_NE_BUILDINGS={'uaod':(3616,2784),'uzig':(4192,3424),
                 'usep':(3264,3712),'utom':(4352,3136),'ugrv':(3904,3776)}
SW_REFERENCE_SHA256='6d220d73cfab0b94d8ce0eb62fc0ff2991b27df3f06e24a0ed73b486c190d89f'
LR_SW_HOME=(-3904,-3968)
# The SW replay first tried (-3552,-3296), then moved the altar here.
# Retain the final location, not those earlier attempts.
LR_SW_BUILDINGS={'uaod':(-3616,-3360),'uzig':(-4256,-4064),
                 'usep':(-3328,-4352),'utom':(-4416,-3776),'ugrv':(-3968,-4416)}
# Planning half-widths from the local pathing definitions; no extra generic
# 128-unit spacing on the user's compact template. Engine placement still rules.
LR_HALF={'uaod':160,'uzig':96,'usep':192,'utom':192,'ugrv':192}
# Second Acolyte training order in the same SW/NE Happy recordings.
HAPPY_SECOND_ACOLYTE_MS={LR_SW_HOME:11640,LR_NE_HOME:13500}
# Same-side complete openings against Human, fixed before the game. The SW
# source has a single first-tower order; no picking a different replay per row.
HAPPY_LR={
    LR_SW_HOME: {'uaod':(4800,(-3616,-3552)), 'uzig':(8100,(-4256,-3936)),
                 'usep':(31320,(-3456,-4416)), 'utom':(55440,(-4352,-3648)),
                 'Udea':(66900,None), 'ugrv':(73860,(-4160,-4416))},
    LR_NE_HOME: {'uaod':(4300,(3872,2848)), 'uzig':(6800,(4256,3424)),
                 'usep':(31800,(3392,3584)), 'utom':(55000,(4288,3008)),
                 'Udea':(66400,None), 'ugrv':(74100,(3968,3776))},
}
# Last move destination before the long trip, then the final search destination
# before the attack. Intermediate rapid right-clicks are not reached waypoints.
LR_NE_APPROACH=((1347.833251953125,3575.42529296875),
                (1160.0050048828125,3527.070068359375))
LR_SW_APPROACH=((-1398.711181640625,-4169.20654296875),
                (-1607.8560791015625,-4611.68310546875))


def matches(alias,home):
    return alias=='LR' and (home.x,home.y) in (LR_NE_HOME,LR_SW_HOME)


def approach(alias,home):
    if not matches(alias,home):return ()
    return LR_NE_APPROACH if (home.x,home.y)==LR_NE_HOME else LR_SW_APPROACH


def fixed_slot(alias,home,code,buildings):
    if not matches(alias,home) or code not in LR_NE_BUILDINGS:return None
    family={'uzig','uzg1','uzg2'} if code=='uzig' else {code}
    # Subsequent supply/production buildings keep the ordinary planner.
    if any(b.type in family for b in buildings):return None
    sites=LR_NE_BUILDINGS if (home.x,home.y)==LR_NE_HOME else LR_SW_BUILDINGS
    return sites[code]
