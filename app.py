import threading
import time
from datetime import datetime
from random import choice, randint, shuffle
from typing import List, Optional

from flask import Flask, request

from game import Game
from player import join, level_of, player_of, update_elo, update_elo_after_game
from share import (Reasons, create_socketio, get_logger, running, send_command,
                   send_message)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chessroad-up-up-day-day'
socketio = create_socketio(app)

logger = get_logger(__name__)


@app.route('/')
def index():
    return 'Welcome to Chessroad!\n' \
           + f"Server time: {datetime.now().strftime('%H:%M')}\n" \
           + f'Current online players: {len(running.online_players)}\n' \
           + f'Current matching game waiting list: {len(running.waiting_players)}\n'


@socketio.on('connect')
def on_connect():
    # what happens when somebody connects
    logger.info(f'New connection made: {request.sid}')

    running.online_players.append(request.sid)

    welcome()

    send_message(running.waiting_players.keys(), 'New player connected, waiting for a match!')


@socketio.on('disconnect')
def on_disconnect():
    # Maintaining numbers and lists of ALL connected players
    running.online_players.remove(request.sid)

    # Disconnected player was in a waiting list - using pop() with a default value
    running.waiting_players.pop(request.sid, None)

    # Disconnected player was in a game, checking
    for game in running.games:
        if request.sid in game.players:
            logger.info('Player in a chess game has disconnected')
            game.player_disconnected(request.sid)

    logger.info('Connection Lost and handled by the server')


@socketio.on('join')
def on_join(data):
    logger.info(f'{request.sid} logged in with {data}.')

    if 'pid' not in data or 'name' not in data:
        send_message(request.sid, 'Login failed, please check the client version!')
        return

    join(request.sid, data['pid'], data['name'])

    on_match(data)


@socketio.on('match')
def on_match(data):
    logger.info(f'{request.sid} wants to play with time control: {data}')

    game = find_game(request.sid)
    if game:
        logger.info(f'{request.sid} is already in a game.')
        return

    time_control_index = data.get('time_control', 0)  # 默认使用第一个时间规则

    # 将玩家加入等待队列，同时保存他们选择的时间规则
    if request.sid not in running.waiting_players:
        running.waiting_players[request.sid] = {'join_time': time.time(), 'time_control': time_control_index}


@socketio.on('move')
def on_move(data):
    logger.info(f'{request.sid} wants to move {data}.')

    game = find_game(request.sid)
    if game:
        if not game.on_move(data, request.sid):
            logger.info(f'{request.sid} sent an invalid move.')
    else:
        logger.info(f'{request.sid} is not in a game.')


@socketio.on('propose_draw')
def on_propose_draw(_):
    logger.info(f'{request.sid} proposed a draw.')

    game = find_game(request.sid)
    if game:
        if game.on_draw_proposal(request.sid):
            logger.info(f'{request.sid} proposed a draw')
        else:
            logger.info(f'{request.sid} draw proposal failed')


@socketio.on('draw_response')
def on_draw_response(data):
    logger.info(f'{request.sid} responded to draw: {data}')

    game = find_game(request.sid)
    if game:
        accepted = data.get('accepted', False)
        if game.on_draw_response(request.sid, accepted):
            logger.info(f'{request.sid} responded to draw: {accepted}')
        else:
            logger.info(f'{request.sid} draw response failed')


@socketio.on('propose_takeback')
def on_propose_takeback(_):
    game = find_game(request.sid)
    if game:
        if game.on_takeback_proposal(request.sid):
            logger.info(f'{request.sid} requested takeback')
        else:
            logger.info(f'{request.sid} takeback request failed')


@socketio.on('takeback_response')
def on_takeback_response(data):
    game = find_game(request.sid)
    if game:
        accepted = data.get('accepted', False)
        if game.on_takeback_response(request.sid, accepted):
            logger.info(f'{request.sid} responded to takeback: {accepted}')
        else:
            logger.info(f'{request.sid} takeback response failed')


@socketio.on('resign')
def on_resign(_):
    logger.info(f'{request.sid} wants to resign.')

    game = find_game(request.sid)
    if game:
        game.on_resign(request.sid)
    else:
        logger.info(f'{request.sid} is not in a game.')


@socketio.on('message')
def on_message(data):
    # we got something from a client
    logger.info(f'{request.sid} sent a message: {data}')


# Constant definitions
WELCOME_MESSAGE = 'Welcome to Chessroad!'
SERVER_SECRET = 'chessroad-up-up-day-day'


class MatchConfig:
    DIFF_INIT = 1          # Initial level difference
    DIFF_INCREMENT = 1     # Incremental level difference
    DIFF_MAX = 4           # Maximum level difference
    BOT_WAIT_TIME = 15     # Waiting time for bot matching (seconds)
    CHECK_INTERVAL = 5     # Matching check interval (seconds)

    BOT_NAMES = [
        "Chess Master", "Chess Grandmaster", "Chess Expert",
        "Rising Star", "Chess Proficient", "Chess Virtuoso",
        "Chess Champion", "Chess Phenomenon"
    ]


class GameConfig:
    # 定义不同的时间规则 (总时间(分钟), 增量(秒))
    TIME_CONTROLS = [
        (5 * 60, 2),    # 5分钟+2秒增量
        (10 * 60, 0),   # 10分钟无增量
        (15 * 60, 10),  # 15分钟+10秒增量
        (30 * 60, 15)   # 30分钟+15秒增量
    ]

    @staticmethod
    def get_time_control(index: int) -> tuple:
        if 0 <= index < len(GameConfig.TIME_CONTROLS):
            minutes, increment = GameConfig.TIME_CONTROLS[index]
            return minutes, increment  # 转换为秒
        return GameConfig.TIME_CONTROLS[0]  # 默认使用第一个时间规则


def welcome():
    """Send welcome message to the newly connected client"""
    messages = [
        WELCOME_MESSAGE,
        f"Server time: {datetime.now().strftime('%H:%M')}",
        f'Current online players: {len(running.online_players)}',
        f'Current matching game waiting list: {len(running.waiting_players) + 1}'
    ]
    for message in messages:
        send_message([request.sid], message)


def match_players():
    """
    Background matching system main loop
    - Handle player matching
    - Create bot opponents after timeout
    """
    threading.current_thread().name = 'match_players'

    while True:
        socketio.sleep(MatchConfig.CHECK_INTERVAL)
        process_matching_queue()


def process_matching_queue():
    """Process player matching in the waiting queue"""
    current_time = time.time()
    to_remove = []  # Players to be removed from the waiting queue

    for sid, data in running.waiting_players.items():
        if sid in to_remove:
            continue

        time_waited = current_time - data['join_time']
        if try_match_player(sid, time_waited, to_remove, data['time_control']):
            continue

        if try_create_bot_match(sid, time_waited, to_remove, data['time_control']):
            continue

    # Clean up matched players
    for sid in to_remove:
        running.waiting_players.pop(sid, None)


def try_match_player(sid: str, time_waited: float, to_remove: List[str], time_control_index: int) -> bool:
    """Try to match a player with an opponent"""
    level = level_of(player_of(sid)['elo'])

    allowed_difference = min(
        MatchConfig.DIFF_INIT + (MatchConfig.DIFF_INCREMENT * int(time_waited / 5)),
        MatchConfig.DIFF_MAX
    )
    for other_sid, other_data in running.waiting_players.items():
        if other_sid == sid or other_sid in to_remove:
            continue

        # 检查时间规则是否匹配
        if other_data['time_control'] != time_control_index:
            continue

        if is_suitable_opponent(level, other_sid, allowed_difference):
            create_match([sid, other_sid], to_remove, time_control_index)
            return True

    return False


def is_suitable_opponent(player_level: int, opponent_sid: str, allowed_difference: int) -> bool:
    """Check if the opponent is suitable for matching"""
    opponent_level = level_of(player_of(opponent_sid)['elo'])
    return abs(player_level - opponent_level) <= allowed_difference


def try_create_bot_match(sid: str, time_waited: float, to_remove: List[str], time_control_index: int) -> bool:
    """Try to create a bot match"""
    if time_waited > MatchConfig.BOT_WAIT_TIME and sid not in to_remove:
        bot_sid = create_bot_player(sid)
        create_match([sid, bot_sid], to_remove, time_control_index, is_bot=bot_sid)
        return True

    return False


def create_bot_player(player_sid: str) -> str:
    """Create and initialize a bot player"""
    bot_sid = f"bot_{time.time()}"
    bot_name = choice(MatchConfig.BOT_NAMES)

    join(bot_sid, bot_sid, bot_name)

    # Set bot level
    bot_player = player_of(bot_sid)
    bot_player['elo'] = player_of(player_sid)['elo'] + randint(-100, 100)
    update_elo(bot_player)

    return bot_sid


def create_match(pair: List[str], to_remove: List[str], time_control_index: int, is_bot: str = None):
    """Create a match and notify players"""
    to_remove.extend([p for p in pair if not p.startswith('bot_')])
    send_message(pair, 'Match found.. Connecting')
    make_game(pair, time_control_index=time_control_index, is_bot=is_bot)


def make_game(pair: List[str], time_control_index: int, is_bot: str = None):
    """Create a game and notify players"""
    shuffle(pair)

    white, black = pair[0], pair[1]
    white_player, black_player = player_of(white), player_of(black)

    total_time, increment = GameConfig.get_time_control(time_control_index)

    # Sending over the command codes to initialize game modes on clients
    send_command([white], 'game_mode', {
        'side': 'white', 'white_player': white_player, 'black_player': black_player
    })
    send_command([black], 'game_mode', {
        'side': 'black', 'white_player': white_player, 'black_player': black_player
    })

    # Running the game
    game = Game(pair, total_time, increment, bot_sid=is_bot)
    running.games.append(game)

    logger.info(f'Hosted a game. ID = {game.game_id}' + (' (with bot)' if is_bot else ''))


def find_game(sid: str) -> Optional[Game]:
    for game in running.games:
        if sid in game.players:
            return game

    return None


def timer_task():
    threading.current_thread().name = 'timer_task'

    while True:
        running.socketio.sleep(1)

        for game in running.games:
            if game.is_game_over:
                continue

            game.update_timer()

            current = game.players[game.current_player_index]
            opponent = game.opponent_of(current)

            current_time = int(game.player_times[game.current_player_index])
            opponent_time = int(game.player_times[(game.current_player_index + 1) % 2])

            if current_time < 0 or opponent_time < 0:
                loser = current if current_time < 0 else opponent
                winner = game.opponent_of(loser)

                game.declare_loser([loser], Reasons.Lose.OUT_OF_TIME)
                game.declare_winner([winner], Reasons.Win.OPPONENT_OUT_OF_TIME)

                update_elo_after_game(winner, loser, 1)

            else:
                send_command([current], 'timer', {'mine': current_time, 'opponent': opponent_time})
                send_command([opponent], 'timer', {'mine': opponent_time, 'opponent': current_time})


if __name__ == '__main__':
    logger.info('Starting server...')
    socketio.start_background_task(target=match_players)
    socketio.start_background_task(target=timer_task)
    socketio.run(app, host='0.0.0.0', port=8888)
