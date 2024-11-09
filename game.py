import threading
import time
from typing import Dict, List

import chess
import chess.engine

from player import level_of, player_of, update_elo_after_game
from share import logger, running, send_command, send_message

STOCKFISH_PATH = "./stockfish-17-m1"


class Game:

    def __init__(self, pair: List[str], total_time: int, step_increment_time: int, bot_sid=None):

        self.players = pair
        self.player1 = self.players[0]
        self.player2 = self.players[1]
        self.game_id = hash(self.player1) + hash(self.player2)

        self.game_times = [total_time, total_time]
        self.step_increment_time = step_increment_time

        self.start_time = None

        self.player_turn = 0
        self.this_turn_move_made = False

        self.board = chess.Board()
        self.is_game_over = False

        self.previous_move = None  # 记录上一步
        self.draw_proposer = None  # 记录谁发起求和
        self.takeback_proposer = None  # 记录谁请求悔棋

        self.bot_sid = bot_sid
        self.engine = None

        if bot_sid:
            self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            # 设置合适的引擎强度
            bot_player = player_of(self.bot_sid)
            bot_level = level_of(bot_player['elo'])
            self.engine.configure({"Skill Level": bot_level})  # 1-20之间调整

        self.first_turn()

    def opponent_of(self, player: str) -> str:
        return self.players[(self.players.index(player) + 1) % 2]

    def timer_task(self):

        threading.current_thread().name = f'timer_task_{self.game_id}'

        while not self.is_game_over:

            running.socketio.sleep(1)
            self.update_timer()

            current = self.players[self.player_turn]
            opponent = self.opponent_of(current)

            current_time = int(self.game_times[self.player_turn])
            opponent_time = int(self.game_times[(self.player_turn + 1) % 2])

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
        self.game_times[self.player_turn] -= elapsed
        self.start_time = current_time

    def first_turn(self):
        self.player_turn = 0  # index of player that is ought to make a move
        self.last_player = 1  # index of a player that made move last time

        self.start_time = time.time()
        running.socketio.start_background_task(target=self.timer_task)

        self.new_board_state()

        if self.bot_sid and self.players[self.player_turn] == self.bot_sid:
            # 机器人思考并走子
            result = self.engine.play(self.board, chess.engine.Limit(time=1.0))
            if self.on_move({'move': str(result.move)}, self.bot_sid):
                self.after_move()

        else:
            send_command([self.players[self.player_turn]], 'go', {})

        logger.info(f'Waiting for a move from player, game ID = {self.game_id}')

    def new_board_state(self):
        # This send_to out the board state to both players
        send_message(self.players, f'\n{str(self.board)}')
        logger.info(f'GAME STATUS. ID = {self.game_id}')
        logger.info(self.board)

    def after_move(self):

        # Verify if both players are still connected
        if self.is_player_connected(self.player1) and self.is_player_connected(self.player2):
            # draw conditions
            if not self.board.is_stalemate():
                if not self.board.is_insufficient_material():
                    # has the game been won
                    if not self.board.is_checkmate():
                        if not self.is_game_over:
                            # WE GET TO PLAY, HURRAY
                            # sending board state to players
                            self.new_board_state()

                            # changing turns
                            self.this_turn_move_made = False
                            self.player_turn = (self.player_turn + 1) % 2
                            self.last_player = (self.last_player + 1) % 2

                            if self.bot_sid and self.players[self.player_turn] == self.bot_sid:
                                # 机器人思考并走子
                                result = self.engine.play(self.board, chess.engine.Limit(time=1.0))
                                if self.on_move({'move': str(result.move)}, self.bot_sid):
                                    self.after_move()

                            else:
                                # message next player of his turn
                                send_command([self.players[self.player_turn]], 'go', {})

                            # update timer, and reset the start time for next turn
                            self.update_timer()

                    else:
                        # player who made the last move won
                        self.declare_loser([self.players[self.last_player]], '绝杀！')
                        self.declare_winner([self.players[self.player_turn]], '绝杀！')
                        update_elo_after_game(self.players[self.player_turn], self.players[self.last_player], 1)

                else:
                    # is a stalemate due to insufficient material
                    self.draw('子力不足！')
                    update_elo_after_game(self.player1, self.player2, 0.5)

            else:
                # is a stalemate
                self.draw('僵局！')
                update_elo_after_game(self.player1, self.player2, 0.5)

        else:
            # one of the players has disconnected
            # declaring winners
            if not self.is_player_connected(self.player1):
                self.declare_winner([self.player2], '对手退出对局了！')
                update_elo_after_game(self.player2, self.player1, 1)

            else:
                self.declare_winner([self.player1], '对手退出对局了！')
                update_elo_after_game(self.player1, self.player2, 1)

    def is_player_connected(self, player: str) -> bool:
        if player in running.online_players or player.startswith('bot_'):
            return True
        else:
            self.players.remove(player)
            return False

    def declare_winner(self, players: List[str], reason: str):
        send_command(players, 'win', {'reason': reason})
        self.game_over()

    def declare_loser(self, players: List[str], reason: str):
        send_command(players, 'lost', {'reason': reason})

    def draw(self, reason: str):
        send_command(self.players, 'draw', {'reason': reason})
        self.game_over()

    def player_disconnected(self, player: str):
        if self.player1 == player:
            self.declare_winner([self.player2], '对手退出对局了！')
            update_elo_after_game(self.player2, self.player1, 1)

        elif (self.player2 == player):
            self.declare_winner([self.player1], '对手退出对局了！')
            update_elo_after_game(self.player1, self.player2, 1)

    def game_over(self):

        logger.info(f'The game has ended. ID = {self.game_id}')
        send_command(self.players, 'game_over', {})
        self.is_game_over = True

        # remove the game from games list
        running.games.remove(self)
        logger.info(f'Removed a finished game from games')

        self.return_to_lobby_after_game()

    def return_to_lobby_after_game(self):
        # add the players to waiting list, maintain numbers and run matchmaking (since we're adding new players)
        for player in self.players:
            send_message([player], "你已被放入匹配对局等待列表中。")

        # SPECIAL COMMAND CODE to clients
        for player in self.players:
            send_message([player], '输入 MATCH 以立即匹配对局。')
            send_command([player], 'waiting_match', {})

    def on_forfeit(self, player: str):

        if player == self.player1:
            self.declare_winner([self.player2], '对手认输！')
            update_elo_after_game(self.player2, self.player1, 1)

        else:
            self.declare_winner([self.player1], '对手认输！')
            update_elo_after_game(self.player1, self.player2, 1)

    def on_move(self, move: Dict[str, str], player: str) -> bool:
        # processes messages and return True/False depending if it was valid

        if 'move' in move and self.verify_move(move['move']):
            self.make_move(move['move'], self.opponent_of(player))
            self.game_times[self.player_turn] += self.step_increment_time
            return True

        else:
            send_message([player], f'指令错误：{move}，请重新输入。')
            return False

    def verify_move(self, move: str) -> bool:
        # verifies moves
        try:
            if chess.Move.from_uci(move) in self.board.legal_moves:
                return True
            else:
                return False
        except (ValueError, IndexError) as wrong_format_or_illegal_move:
            return False

    def make_move(self, move: str, opponent: str):
        # Makes the move on the board
        self.board.push_uci(move)

        send_command([opponent], 'move', {'move': self.board.peek().uci()})

        self.this_turn_move_made = True

    def on_draw_proposal(self, proposer: str) -> bool:

        if self.draw_proposer is None:

            self.draw_proposer = proposer
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

        if self.draw_proposer and responder == self.opponent_of(self.draw_proposer):

            if accepted:
                self.draw('和棋达成！')
                update_elo_after_game(self.player1, self.player2, 0.5)

            else:
                send_command([self.draw_proposer], 'draw_declined', {})

            self.draw_proposer = None

            return True

        return False

    def on_takeback_proposal(self, proposer: str) -> bool:

        if self.takeback_proposer is None and len(self.board.move_stack) > 0:

            self.takeback_proposer = proposer
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

        if self.takeback_proposer and responder == self.opponent_of(self.takeback_proposer):

            if accepted:

                # 检查是否有至少两步可以撤销
                if len(self.board.move_stack) >= 2:
                    # 撤销双方最近的两步棋
                    _ = self.board.pop()  # 撤销对手的一步
                    _ = self.board.pop()  # 撤销自己的一步

                    # 恢复时间 (为双方都减去增量时间)
                    self.game_times[0] -= self.step_increment_time
                    self.game_times[1] -= self.step_increment_time
                    self.start_time = time.time()

                    # 轮到发起悔棋方重新走棋
                    self.player_turn = self.players.index(self.takeback_proposer)
                    self.last_player = (self.player_turn + 1) % 2

                    # 通知双方
                    send_command(self.players, 'takeback_success', {})

                    self.new_board_state()
                    send_command([self.players[self.player_turn]], 'go', {})

                else:
                    # 棋步不足,拒绝悔棋
                    send_command([self.takeback_proposer], 'takeback_declined', {
                        'reason': '棋步不足，无法悔棋！'
                    })

            else:
                send_command([self.takeback_proposer], 'takeback_declined', {})

            self.takeback_proposer = None

            return True

        return False

    def __del__(self):
        if self.engine:
            self.engine.quit()
