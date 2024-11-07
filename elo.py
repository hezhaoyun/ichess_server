from typing import Any, Dict
from dbc import load, upsert

player_cache: Dict[str, Dict[str, Any]] = {}


def player_of(sid: str) -> Dict[str, Any]:

    if sid in player_cache:
        return player_cache[sid]

    player = load(sid)

    if player is None:
        player = {'pid': sid, 'name': sid, 'elo': 1500}
        upsert(player)

    player_cache[sid] = player

    return player


def level_of(elo: int) -> int:
    return (elo - 1000) // 100


def update_elo_after_game(player_sid: str, opponent_sid: str, result: int):
    player = player_of(player_sid)
    opponent = player_of(opponent_sid)

    player['elo'] = calc_elo(player['elo'], opponent['elo'], result)
    opponent['elo'] = calc_elo(opponent['elo'], player['elo'], 1 - result)

    update_elo(player_sid, player['elo'])
    update_elo(opponent_sid, opponent['elo'])


def update_elo(pid: str, elo: int) -> bool:

    player = player_of(pid)

    # update the player in the cache
    if player:
        player['elo'] = elo

    return upsert({'pid': pid, 'elo': elo})


def calc_elo(player_elo: int, opponent_elo: int, result: int, K: int = 30) -> int:
    """result 1 for win, 0.5 for draw, 0 for loss"""
    expected_score = 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))
    return round(player_elo + K * (result - expected_score))
