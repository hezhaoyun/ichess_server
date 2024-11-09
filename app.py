import threading
import time
from datetime import datetime
from random import choice, randint, shuffle
from typing import List, Optional

from flask import Flask, request

from game import Game
from player import join, level_of, name_of, player_of, update_elo
from share import create_socketio, logger, running, send_command, send_message

# 机器人名字池
BOT_NAMES = ["棋艺高手", "棋道大师", "棋林高手", "棋坛新秀", "棋艺精湛", "棋道高人", "棋坛高手", "棋艺超群"]

# 等待多久后使用机器人（秒）
BOT_WAIT_TIME = 5

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chessroad-up-up-day-day'
socketio = create_socketio(app)


@app.route('/')
def index():
    return '欢迎来到 Chessroad!\n' \
           + f"服务器时间: {datetime.now().strftime('%H:%M')}\n" \
           + f'当前在线玩家: {len(running.online_players)}\n' \
           + f'当前匹配对局等待列表: {len(running.waiting_players)}\n'


@socketio.on('connect')
def on_connect():
    # what happens when somebody connects
    logger.info(f'New connection made: {request.sid}')

    running.online_players.append(request.sid)

    welcome()

    send_message(running.waiting_players.keys(), '新玩家已连接，等待匹配对局！')


@socketio.on('disconnect')
def on_disconnect():
    # Maintaining numbers and lists of ALL connected players
    running.online_players.remove(request.sid)

    # Disconnected player was in a waiting list - 使用 pop() 带默认值
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
        send_message(request.sid, '登录失败，请检查客户端版本！')
        return

    join(request.sid, data['pid'], data['name'])

    on_match(data)


@socketio.on('match')
def on_match(_):
    logger.info(f'{request.sid} wants to play.')

    game = find_game(request.sid)
    if game:
        logger.info(f'{request.sid} is already in a game.')
        return

    # the client is not playing in a game
    if request.sid not in running.waiting_players:
        running.waiting_players[request.sid] = time.time()


@socketio.on('move')
def on_move(data):
    logger.info(f'{request.sid} wants to move {data}.')

    game = find_game(request.sid)
    if game:
        if game.on_move(data, request.sid):
            # Engage the next turn function
            game.after_move()
        else:
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


@socketio.on('forfeit')
def on_forfeit(_):
    logger.info(f'{request.sid} wants to forfeit.')

    game = find_game(request.sid)
    if game:
        game.on_forfeit(request.sid)
    else:
        logger.info(f'{request.sid} is not in a game.')


@socketio.on('message')
def on_message(data):
    # we got something from a client
    logger.info(f'{request.sid} sent a message: {data}')


def welcome():
    # a bunch of on-login messages
    send_message([request.sid], '欢迎来到 Chessroad!')
    send_message([request.sid], f"服务器时间: {datetime.now().strftime('%H:%M')}")
    send_message([request.sid], f'当前在线玩家: {len(running.online_players)}')
    send_message([request.sid], f'当前匹配对局等待列表: {len(running.waiting_players) + 1}')


# 后台配对任务
def match_players():

    MATCH_DIFF_INIT = 1     # 初始等级差距
    MATCH_DIFF_INC = 1      # 每次递增的等级差距
    MATCH_DIFF_MAX = 4      # 最大等级差距

    threading.current_thread().name = 'match_players'

    while True:
        socketio.sleep(5)  # 每5秒检查一次匹配情况

        current_time = time.time()
        to_remove = []  # 将要从等待队列中移除的配对玩家

        for sid, join_time in running.waiting_players.items():

            # 跳过已配对的玩家
            if sid in to_remove:
                continue

            time_waited = current_time - join_time
            level = level_of(player_of(sid)['elo'])

            allowed_difference = min(
                MATCH_DIFF_INIT + (MATCH_DIFF_INC * int(time_waited / 5)),
                MATCH_DIFF_MAX
            )

            for other_sid, _ in running.waiting_players.items():

                # 跳过自己或已配对的玩家
                if other_sid == sid or other_sid in to_remove:
                    continue

                other_level = level_of(player_of(other_sid)['elo'])

                # 寻找合适对手
                if abs(level - other_level) <= allowed_difference:
                    # 找到合适对手，进行配对
                    pair = [sid, other_sid]
                    to_remove.extend(pair)

                    send_message(pair, '找到匹配对局.. 连接中')
                    make_game(pair)
                    break

            # 如果等待时间超过阈值，创建机器人对手
            if time_waited > BOT_WAIT_TIME and sid not in to_remove:
                # 创建机器人玩家
                bot_sid = f"bot_{time.time()}"
                bot_name = choice(BOT_NAMES)

                # 注册机器人
                join(bot_sid, bot_sid, bot_name)

                # 根据玩家等级设置机器人等级
                bot_player = player_of(bot_sid)
                bot_player['elo'] = player_of(sid)['elo'] + randint(-100, 100)
                update_elo(bot_player)

                # 创建游戏
                pair = [sid, bot_sid]
                to_remove.append(sid)

                send_message([sid], '找到匹配对局.. 连接中')
                make_game(pair, is_bot=bot_sid)
                break

        # 从等待队列中移除已配对的玩家
        for sid in to_remove:
            running.waiting_players.pop(sid, None)


def make_game(pair: List[str], is_bot: str = None):

    shuffle(pair)

    white, black = pair[0], pair[1]

    # Sending over the command codes to initialize game modes on clients
    send_command([white], 'game_mode', {
        'side': 'white', 'opponent': name_of(black), 'opponent_elo': player_of(black)['elo']
    })
    send_command([black], 'game_mode', {
        'side': 'black', 'opponent': name_of(white), 'opponent_elo': player_of(white)['elo']
    })

    # running the game
    game = Game(pair, 180, 5, bot_sid=is_bot)
    running.games.append(game)

    logger.info(f'Hosted a game. ID = {game.game_id}' + (' (with bot)' if is_bot else ''))


def find_game(sid: str) -> Optional[Game]:
    for game in running.games:
        if sid in game.players:
            return game

    return None


if __name__ == '__main__':
    logger.info('Starting server...')
    socketio.start_background_task(target=match_players)
    socketio.run(app)
