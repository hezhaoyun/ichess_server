from typing import Any, Dict, Tuple, Optional

from flask_socketio import send
from dbc import load, upsert
from share import logger

# 定义常量
DEFAULT_ELO = 1500
MIN_LEVEL = 1
MAX_LEVEL = 20
ELO_K_FACTOR = 30

# 类型别名定义
PlayerData = Dict[str, Any]
JoinInfo = Tuple[str, str]

# 缓存
join_cache: Dict[str, JoinInfo] = {}
player_cache: Dict[str, PlayerData] = {}


def join(sid: str, pid: str, name: str) -> None:
    """存储玩家的登录信息
    
    Args:
        sid: 会话ID
        pid: 玩家ID
        name: 玩家名称
    """
    join_cache[sid] = (pid, name)


def pid_of(sid: str) -> Optional[str]:
    """获取玩家ID
    
    Args:
        sid: 会话ID
    
    Returns:
        玩家ID，如未登录则返回None
    """
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
    """根据ELO分数计算玩家等级
    
    Args:
        elo: 玩家的ELO分数
    
    Returns:
        玩家等级(1-20)
    """
    return max(MIN_LEVEL, min(MAX_LEVEL, (elo - 1000) // 100))


def update_elo_after_game(player_sid: str, opponent_sid: str, result: float) -> None:
    """更新游戏后双方的ELO分数
    
    Args:
        player_sid: 玩家会话ID
        opponent_sid: 对手会话ID
        result: 比赛结果(1.0为胜利，0.5为平局，0.0为失败)
    """
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
    """计算新的ELO分数
    
    Args:
        player_elo: 玩家当前ELO
        opponent_elo: 对手当前ELO
        result: 比赛结果(1.0为胜利，0.5为平局，0.0为失败)
        K: ELO计算系数，默认为30
        
    Returns:
        计算后的新ELO分数
    """
    expected_score = 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))
    return round(player_elo + K * (result - expected_score))
