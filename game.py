import threading
import time
from typing import Dict, List

import chess
import chess.engine

from player import level_of, player_of, update_elo_after_game
from share import logger, running, send_command, send_message

# for mac with apple silicon
STOCKFISH_PATH = "./stockfish/apple-silicon"

# for linux with popcnt (slower than avx2)
STOCKFISH_PATH = "./stockfish/linux-popcnt"


class Game:

    def __init__(self, pair: List[str], total_time: int, step_increment_time: int, bot_sid=None):

        self.players = pair
        self.player1 = self.players[0]
        self.player2 = self.players[1]
        self.game_id = hash(self.player1) + hash(self.player2)

        self.player_times = [total_time, total_time]
        self.step_increment_time = step_increment_time

        self.start_time = None
        self.current_player_index: int = 0

        self.board = chess.Board()
        self.is_game_over = False

        self.game_state = {
            'is_over': False,
            'previous_move': None,
            'draw_proposer': None,
            'takeback_proposer': None
        }

        self.bot_sid = bot_sid
        self.engine = None

        self.setup_bot(bot_sid)

        self.start_game()

    def setup_bot(self, bot_sid: str) -> None:

        if not bot_sid:
            return

        self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        bot_player = player_of(bot_sid)
        bot_level = level_of(bot_player['elo'])
        self.engine.configure({"Skill Level": bot_level})

    def start_game(self) -> None:

        self.start_time = time.time()
        running.socketio.start_background_task(target=self.timer_task)

        self.send_board_state()

        if self.bot_sid and self.players[self.current_player_index] == self.bot_sid:
            self.make_bot_move()
        else:
            send_command([self.players[self.current_player_index]], 'go', {})

        logger.info(f'等待玩家走子，对局ID = {self.game_id}')

    def timer_task(self):

        threading.current_thread().name = f'timer_task_{self.game_id}'

        while not self.is_game_over:

            running.socketio.sleep(1)
            self.update_timer()

            current = self.players[self.current_player_index]
            opponent = self.opponent_of(current)

            current_time = int(self.player_times[self.current_player_index])
            opponent_time = int(self.player_times[(self.current_player_index + 1) % 2])

            if current_time < 0 or opponent_time < 0:
                loser = current if current_time < 0 else opponent
                winner = self.opponent_of(loser)

                self.declare_loser([loser], '你超时了！')
                self.declare_winner([winner], '对手超时！')

                update_elo_after_game(winner, loser, 1)

            else:
                send_command([current], 'timer', {'mine': current_time, 'opponent': opponent_time})
                send_command([opponent], 'timer', {'mine': opponent_time, 'opponent': current_time})

    def update_timer(self):
        # Calculate elapsed time based on current time and subtract it from current player's remaining time
        current_time = time.time()
        elapsed = current_time - self.start_time
        self.player_times[self.current_player_index] -= elapsed
        self.start_time = current_time

    def send_board_state(self):
        # This send_to out the board state to both players
        send_message(self.players, f'\n{str(self.board)}')
        logger.info(f'GAME STATUS. ID = {self.game_id}')
        logger.info(self.board)

    def make_bot_move(self) -> None:

        result = self.engine.play(self.board, chess.engine.Limit(time=1.0))
        self.on_move({'move': str(result.move)}, self.bot_sid)

    def on_move(self, move: Dict[str, str], player: str) -> bool:

        if 'move' in move and self.verify_move(move['move']):

            self.make_move(move['move'], self.opponent_of(player))
            self.player_times[self.current_player_index] += self.step_increment_time

            self.after_move()
            return True

        else:
            send_message([player], f'指令错误：{move}，请重新输入。')
            return False

    def verify_move(self, move: str) -> bool:
        try:
            return chess.Move.from_uci(move) in self.board.legal_moves
        except (ValueError, IndexError):
            return False

    def make_move(self, move: str, opponent: str):
        self.board.push_uci(move)
        send_command([opponent], 'move', {'move': self.board.peek().uci()})

    def after_move(self):

        if not self.check_players_connected():
            return self.handle_disconnection()

        if self.check_game_end():
            return

        self.prepare_next_turn()

    def check_players_connected(self) -> bool:
        for player in self.players:
            if not self.is_player_connected(player):
                return False

        return True

    def handle_disconnection(self) -> None:
        disconnected_player = next(
            (player for player in [self.player1, self.player2]
             if not self.is_player_connected(player)),
            None
        )

        if disconnected_player:
            self.player_disconnected(disconnected_player)

    def is_player_connected(self, player: str) -> bool:
        if player in running.online_players or player.startswith('bot_'):
            return True
        else:
            self.players.remove(player)
            return False

    def player_disconnected(self, player: str):
        winner = self.player2 if self.player1 == player else self.player1
        self.declare_winner([winner], '对手退出对局了！')
        update_elo_after_game(winner, player, 1)

    def check_game_end(self) -> bool:

        if self.board.is_checkmate():
            self.handle_checkmate()
            return True

        if self.board.is_stalemate():
            self.draw('僵局！')
            update_elo_after_game(self.player1, self.player2, 0.5)
            return True

        if self.board.is_insufficient_material():
            self.draw('子力不足！')
            update_elo_after_game(self.player1, self.player2, 0.5)
            return True

        return False

    def prepare_next_turn(self) -> None:

        self.send_board_state()
        self.current_player_index = (self.current_player_index + 1) % 2

        if self.bot_sid and self.players[self.current_player_index] == self.bot_sid:
            self.make_bot_move()
        else:
            send_command([self.players[self.current_player_index]], 'go', {})

        self.update_timer()

    def game_over(self):
        logger.info(f'The game has ended. ID = {self.game_id}')

        send_command(self.players, 'game_over', {})
        self.is_game_over = True

        running.games.remove(self)

        self.return_to_lobby_after_game()

    def return_to_lobby_after_game(self):
        for player in self.players:
            send_message([player], '输入 MATCH 以立即匹配对局。')
            send_command([player], 'waiting_match', {})

    def declare_winner(self, players: List[str], reason: str):
        send_command(players, 'win', {'reason': reason})
        self.game_over()

    def declare_loser(self, players: List[str], reason: str):
        send_command(players, 'lost', {'reason': reason})

    def draw(self, reason: str):
        send_command(self.players, 'draw', {'reason': reason})
        self.game_over()

    def handle_checkmate(self) -> None:
        winner = self.players[self.current_player_index]
        loser = self.opponent_of(winner)

        self.declare_winner([winner], '绝杀！')
        self.declare_loser([loser], '你被绝杀了！')

        update_elo_after_game(winner, loser, 1)

    def on_resign(self, player: str):
        if player == self.player1:
            self.declare_winner([self.player2], '对手认输！')
            update_elo_after_game(self.player2, self.player1, 1)

        else:
            self.declare_winner([self.player1], '对手认输！')
            update_elo_after_game(self.player1, self.player2, 1)

    def on_draw_proposal(self, proposer: str) -> bool:

        if self.game_state['draw_proposer'] is None:

            self.game_state['draw_proposer'] = proposer
            opponent = self.opponent_of(proposer)

            if self.bot_sid and opponent == self.bot_sid:
                running.socketio.sleep(1)
                self.on_draw_response(self.bot_sid, True)
                return True

            send_command([opponent], 'draw_request', {
                'message': '对手提议和棋，接受吗？'
            })

            return True

        return False

    def on_draw_response(self, responder: str, accepted: bool) -> bool:

        if self.game_state['draw_proposer'] and responder == self.opponent_of(self.game_state['draw_proposer']):

            if accepted:
                self.draw('和棋达成！')
                update_elo_after_game(self.player1, self.player2, 0.5)

            else:
                send_command([self.game_state['draw_proposer']], 'draw_declined', {})

            self.game_state['draw_proposer'] = None

            return True

        return False

    def on_takeback_proposal(self, proposer: str) -> bool:

        if self.game_state['takeback_proposer'] is None and len(self.board.move_stack) > 0:

            self.game_state['takeback_proposer'] = proposer
            opponent = self.opponent_of(proposer)

            if self.bot_sid and opponent == self.bot_sid:
                running.socketio.sleep(1)
                self.on_takeback_response(self.bot_sid, True)
                return True

            send_command([opponent], 'takeback_request', {
                'message': '对手请求悔棋，接受吗？'
            })

            return True

        return False

    def on_takeback_response(self, responder: str, accepted: bool) -> bool:

        if self.game_state['takeback_proposer'] and responder == self.opponent_of(self.game_state['takeback_proposer']):

            if accepted:

                # 检查是否有至少两步可以撤销
                if len(self.board.move_stack) >= 2:
                    # 撤销双方最近的两步棋
                    _ = self.board.pop()  # 撤销对手的一步
                    _ = self.board.pop()  # 撤销自己的一步

                    # 恢复时间 (为双方都减去增量时间)
                    self.player_times[0] -= self.step_increment_time
                    self.player_times[1] -= self.step_increment_time
                    self.start_time = time.time()

                    # 轮到发起悔棋方重新走棋
                    self.current_player_index = self.players.index(self.game_state['takeback_proposer'])

                    # 通知双方
                    send_command(self.players, 'takeback_success', {})

                    self.send_board_state()
                    send_command([self.players[self.current_player_index]], 'go', {})

                else:
                    # 棋步不足,拒绝悔棋
                    send_command([self.game_state['takeback_proposer']], 'takeback_declined', {
                        'reason': '棋步不足，无法悔棋！'
                    })

            else:
                send_command([self.game_state['takeback_proposer']], 'takeback_declined', {})

            self.game_state['takeback_proposer'] = None

            return True

        return False

    def opponent_of(self, player: str) -> str:
        return self.player2 if player == self.player1 else self.player1

    def __del__(self):
        if self.engine:
            self.engine.quit()
