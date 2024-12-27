from typing import Any, Dict, Optional, Tuple

from flask_socketio import send

from dbc import load, upsert
from share import get_logger

# Constants definition
DEFAULT_ELO = 1500
MIN_LEVEL = 1
MAX_LEVEL = 20
ELO_K_FACTOR = 30

# Type alias definition
PlayerData = Dict[str, Any]
JoinInfo = Tuple[str, str]

# Cache
join_cache: Dict[str, JoinInfo] = {}
player_cache: Dict[str, PlayerData] = {}

logger = get_logger(__name__)


def join(sid: str, pid: str, name: str) -> None:
    join_cache[sid] = (pid, name)


def pid_of(sid: str) -> Optional[str]:
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
        player = {'pid': pid, 'elo': DEFAULT_ELO, 'name': name_of(sid)}
        upsert(player)

    player_cache[sid] = player

    return player


def level_of(elo: int) -> int:
    return max(MIN_LEVEL, min(MAX_LEVEL, (elo - 1000) // 100))


def update_elo_after_game(player_sid: str, opponent_sid: str, result: float) -> None:
    player = player_of(player_sid)
    opponent = player_of(opponent_sid)
    
    if not player or not opponent:
        logger.error("Cannot update ELO: player not found")
        return
        
    player['elo'] = calc_elo(player['elo'], opponent['elo'], result)
    opponent['elo'] = calc_elo(opponent['elo'], player['elo'], 1 - result)

    update_elo(player)
    update_elo(opponent)


def update_elo(player: Dict[str, Any]) -> bool:
    return upsert({'pid': player['pid'], 'elo': player['elo']})


def calc_elo(player_elo: int, opponent_elo: int, result: float, K: int = ELO_K_FACTOR) -> int:
    expected_score = 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))
    return round(player_elo + K * (result - expected_score))
