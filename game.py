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
        """设置机器人引擎"""
        if not bot_sid:
            return
            
        self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        bot_player = player_of(bot_sid)
        bot_level = level_of(bot_player['elo'])
        self.engine.configure({"Skill Level": bot_level})

    def start_game(self) -> None:
        """开始新游戏"""
        self.start_time = time.time()
        running.socketio.start_background_task(target=self.timer_task)
        
        self.new_board_state()
        
        if self.bot_sid and self.players[self.current_player_index] == self.bot_sid:
            self.make_bot_move()
        else:
            send_command([self.players[self.current_player_index]], 'go', {})
            
        logger.info(f'等待玩家走子，对局ID = {self.game_id}')

    def make_bot_move(self) -> None:
        """机器人走子"""
        result = self.engine.play(self.board, chess.engine.Limit(time=1.0))
        if self.on_move({'move': str(result.move)}, self.bot_sid):
            self.after_move()

    def timer_task(self):

        threading.current_thread().name = f'timer_task_{self.game_id}'

        while not self.is_game_over:

            running.socketio.sleep(1)
            self.update_timer()

            current = self.players[self.current_player_index]
            opponent = self.opponent_of(current)

            current_time = int(self.game_times[self.current_player_index])
            opponent_time = int(self.game_times[(self.current_player_index + 1) % 2])

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
        self.game_times[self.current_player_index] -= elapsed
        self.start_time = current_time

    def new_board_state(self):
        # This send_to out the board state to both players
        send_message(self.players, f'\n{str(self.board)}')
        logger.info(f'GAME STATUS. ID = {self.game_id}')
        logger.info(self.board)

    def after_move(self):
        """处理走子后的状态"""
        if not self.check_players_connected():
            return self.handle_disconnection()
            
        if self.check_game_end():
            return
            
        self.prepare_next_turn()
        
    def check_game_end(self) -> bool:
        """检查游戏是否结束"""
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
        """准备下一回合"""
        self.new_board_state()
        self.current_player_index = (self.current_player_index + 1) % 2
        
        if self.bot_sid and self.players[self.current_player_index] == self.bot_sid:
            self.make_bot_move()
        else:
            send_command([self.players[self.current_player_index]], 'go', {})
            
        self.update_timer()

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
        """处理玩家断开连接的情况"""
        winner = self.player2 if self.player1 == player else self.player1
        self.declare_winner([winner], '对手退出对局了！')
        update_elo_after_game(winner, player, 1)

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
            self.game_times[self.current_player_index] += self.step_increment_time
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
                    self.game_times[0] -= self.step_increment_time
                    self.game_times[1] -= self.step_increment_time
                    self.start_time = time.time()

                    # 轮到发起悔棋方重新走棋
                    self.current_player_index = self.players.index(self.game_state['takeback_proposer'])

                    # 通知双方
                    send_command(self.players, 'takeback_success', {})

                    self.new_board_state()
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

    def __del__(self):
        if self.engine:
            self.engine.quit()

    def check_players_connected(self) -> bool:
        """检查所有玩家是否都保持连接
        
        Returns:
            bool: 如果所有玩家都在线返回True，否则返回False
        """
        for player in self.players:
            if not self.is_player_connected(player):
                return False
        return True

    def handle_disconnection(self) -> None:
        """处理玩家断开连接的情况"""
        # 找出断开连接的玩家
        disconnected_player = next(
            (player for player in [self.player1, self.player2] 
             if not self.is_player_connected(player)), 
            None
        )
        if disconnected_player:
            self.player_disconnected(disconnected_player)

    def handle_checkmate(self) -> None:
        """处理将军结束的情况"""
        # 获胜者是上一个走子的玩家（因为是他造成了将军）
        winner = self.players[self.current_player_index]
        loser = self.opponent_of(winner)
        
        # 通知玩家游戏结果
        self.declare_winner([winner], '绝杀！')
        self.declare_loser([loser], '你被绝杀了！')
        
        # 更新ELO分数
        update_elo_after_game(winner, loser, 1)

    def opponent_of(self, player: str) -> str:
        """返回指定玩家的对手
        
        Args:
            player: 当前玩家的ID
            
        Returns:
            str: 对手玩家的ID
        """
        return self.player2 if player == self.player1 else self.player1
