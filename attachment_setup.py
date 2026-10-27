"""Read current-match identity; never infer it from the launcher's default map."""
from pathlib import Path

import psutil

from undead.maps import catalog_for_path


def identify_map(pid, live_map):
    evidence = dict(status='unidentified', basis='game_open_map_file')
    try:
        paths = {Path(f.path).resolve() for f in psutil.Process(pid).open_files()
                 if Path(f.path).suffix.lower() in {'.w3x', '.w3m'}}
        if not paths:
            # This SDK fallback verifies that the launcher owns this exact PID.
            from openwar3.mapdata import running_map_path
            path = running_map_path(pid)
            if path:
                paths = {Path(path).resolve()}
                evidence['basis'] = 'owning_launcher_map_argument'
        if len(paths) != 1:
            return None, dict(evidence, reason='ambiguous_map_files' if paths else 'map_file_unavailable')
        path = next(iter(paths))
        evidence['path'] = str(path)
        catalog = catalog_for_path(path)
        if catalog is None:
            return None, dict(evidence, reason='unknown_map_fingerprint')
        expected = {(s['x'], s['y']) for s in catalog['starts']}
        actual = {tuple(s) for s in live_map.starts if tuple(s) != (0, 0)} if live_map else set()
        if not actual or actual != expected:
            return None, dict(evidence, reason='live_starts_mismatch')
        return catalog, dict(evidence, status='verified', alias=catalog['alias'],
                             name=catalog['name'], sha256=catalog['map_sha256'])
    except (OSError, ValueError, psutil.Error) as exc:
        return None, dict(evidence, reason='map_read_failed', error=type(exc).__name__)


class UnsupportedMatch(RuntimeError):
    pass


def identify_opponent(pid, local_player):
    """Only player setup metadata; do not read enemy units, economy or inventory."""
    from undead.game_view import Game
    audit = None
    try:
        audit = Game(pid=pid, fair=False)
        j = audit.jass
        active = [i for i in range(12) if j.GetPlayerSlotState(j.Player(i)) == 1]
        if len(active) != 2 or local_player not in active:
            raise UnsupportedMatch('接管仅支持两名活动玩家的1v1对局')
        slot = next(i for i in active if i != local_player)
        enemy, own = j.Player(slot), j.Player(local_player)
        if not j.IsPlayerEnemy(enemy, own):
            raise UnsupportedMatch('另一活动玩家不是敌方，不能使用1v1接管策略')
        controller = j.GetPlayerController(enemy)
        try:
            race = j.GetPlayerRace(enemy)
        except Exception:
            # Slot/enemy validation succeeded; missing race does not imply undead.
            race = 0
        try:
            local_name = j.GetPlayerName(own)
        except Exception:
            local_name = ''
        return dict(status='verified', slot=slot, controller=controller,
                    local_name=local_name,
                    race=race if race in (1, 2, 3, 4) else 0,
                    race_basis='player_setup' if race in (1, 2, 3, 4) else 'await_visible_enemy')
    except UnsupportedMatch:
        raise
    except Exception as exc:
        return dict(status='unavailable', race=0, race_basis='await_visible_enemy',
                    error=type(exc).__name__)
    finally:
        if audit is not None:
            audit.close()


def bind_map(bot, catalog):
    # Clear every map-dependent default, including search and tavern locations.
    bot.creeping.catalog = catalog['camps'] if catalog else []
    bot.creeping.map_alias = catalog['alias'] if catalog else None
    bot.start_search.camps = catalog['camps'] if catalog else []
    bot.critter_search.spawns = catalog['critters'] if catalog else []
    bot.tavern_sites = [(b['x'], b['y']) for b in catalog.get('neutral_buildings', [])
                        if b['code'] == 'ntav'] if catalog else []
