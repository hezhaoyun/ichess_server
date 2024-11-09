from typing import Any, Dict, Tuple

from flask_socketio import send
from dbc import load, upsert
from share import logger

join_cache: Dict[str, Tuple[str, str]] = {}
player_cache: Dict[str, Dict[str, Any]] = {}


def join(sid: str, pid: str, name: str):
    join_cache[sid] = (pid, name)


def pid_of(sid: str) -> str:
    if sid not in join_cache:
        logger.error(f'Player {sid} not logged in')
        return None

    return join_cache[sid][0]


def name_of(sid: str) -> str:
    return join_cache[sid][1]


def player_of(sid: str) -> Dict[str, Any]:

    if sid in player_cache:
        return player_cache[sid]

    pid = pid_of(sid)
    if not pid:
        send('Please login first!')
        return None

    player = load(pid)

    if player is None:
        player = {'pid': pid, 'elo': 1500, 'name': name_of(sid)}
        upsert(player)

    player_cache[sid] = player

    return player


def level_of(elo: int) -> int:
    return max(min((elo - 1000) // 100, 1), 20)


def update_elo_after_game(player_sid: str, opponent_sid: str, result: int):
    player = player_of(player_sid)
    opponent = player_of(opponent_sid)

    player['elo'] = calc_elo(player['elo'], opponent['elo'], result)
    opponent['elo'] = calc_elo(opponent['elo'], player['elo'], 1 - result)

    update_elo(player)
    update_elo(opponent)


def update_elo(player: Dict[str, Any]) -> bool:
    return upsert({'pid': player['pid'], 'elo': player['elo']})


def calc_elo(player_elo: int, opponent_elo: int, result: int, K: int = 30) -> int:
    """result 1 for win, 0.5 for draw, 0 for loss"""
    expected_score = 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))
    return round(player_elo + K * (result - expected_score))
