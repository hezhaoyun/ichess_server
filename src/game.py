import time

import chess

import src.server as server
from src.server import running


class Game:

    def __init__(self, sid, two_players, id_number):
        # setting up the game board and Chessgame instance
        self.player_turn = 0
        self.this_turn_move_made = False
        
        self.players = two_players
        self.player1 = two_players[0]
        self.player2 = two_players[1]
        self.sid = sid
        self.id_on_server = id_number
        
        self.board = chess.Board()
        self.is_gameover = False
        
        self.first_turn()

    def first_turn(self):

        self.player_turn = 0  # index of player that is ought to make a move
        self.last_player = 1  # index of a player that made move last time

        self.new_board_state()

        receivers = []
        receivers.append(self.players[self.player_turn])

        server.send_to(receivers, "YOUR MOVE")

        print(time.strftime("%H:%M") + " Waiting for a move from player, game ID = " + str(self.id_on_server))

    def new_board_state(self):
        # This send_to out the board state to both players
        server.send_to(self.players, str("\n" + str(self.board)))
        print(time.strftime("%H:%M") + " GAME STATUS. ID = " + str(self.id_on_server))
        print(self.board)

    def after_move(self):
        # Verify if both players are still connected
        if (self.is_player_connected(self.player1) and self.is_player_connected(self.player2)):
            # draw conditions
            if not (self.board.is_stalemate()):
                if not (self.board.is_insufficient_material()):
                    # has the game been won
                    if not (self.board.is_checkmate()):
                        if not (self.is_gameover):
                            # WE GET TO PLAY, HURRAY
                            # sending board state to players
                            self.new_board_state()

                            # changing turns
                            self.this_turn_move_made = False
                            self.player_turn = (self.player_turn + 1) % 2
                            self.last_player = (self.last_player + 1) % 2

                            # message next player of his turn
                            receivers = []
                            receivers.append(self.players[self.player_turn])
                            server.send_to(receivers, "YOUR MOVE")

                    else:
                        # player who made the last move won
                        list = []
                        list.append(self.players[self.player_turn])
                        listtwo = []
                        listtwo.append(self.players[self.last_player])
                        self.declare_loser(listtwo, "Checkmate")
                        self.declare_winner(list, "Checkmate")
                else:
                    # is a stalemate due to insufficient material
                    self.draw("Insufficient material")

            else:
                # is a stalemate
                self.draw("Stalemate")

        else:
            # one of the players has disconnected
            # declaring winners
            if not (self.is_player_connected(self.player1)):
                list = []
                list.append(self.player2)
                self.declare_winner(list, "Your opponent has disconnected")
            else:
                list = []
                list.append(self.player1)
                self.declare_winner(list, "Your opponent has disconnected")

    def is_player_connected(self, player):
        if (player in running.clients_list):
            return True
        else:
            self.players.remove(player)
            return False

    def declare_winner(self, player, reason):
        server.send_to(player, "YOU WON!")
        server.send_to(player, reason)
        self.gameover()

    def declare_loser(self, player, reason):
        server.send_to(player, "YOU LOST!")
        server.send_to(player, reason)

    def draw(self, reason):
        server.send_to(self.players, "The game has ended in a draw.")
        server.send_to(self.players, reason)
        self.gameover()

    def player_disconnected(self, player):
        if (self.player1 == player):
            list = []
            list.append(self.player2)
            self.declare_winner(list, "Your opponent has disconnected")
        elif (self.player2 == player):
            list = []
            list.append(self.player1)
            self.declare_winner(list, "Your opponent has disconnected")

    def gameover(self):
        print("The game has ended. ID = " + str(self.id_on_server))
        server.send_to(self.players, "GAMEOVER")
        self.is_gameover = True

        the_game = 0
        # remove the players from playing list
        for player in self.players:
            for player_and_game in running.playing_list:
                if (player in player_and_game):
                    game_id = player_and_game[1]
                    the_game = running.games_list[game_id]
                    running.playing_list.remove([player, game_id])
                    print(time.strftime("%H:%M ") + "Removed an in-game player from the players' list")

        # remove the game from games list
        running.games_list.remove(the_game)
        print(time.strftime("%H:%M") + " Removed a finished game from gamelist")

        self.return_to_lobby_after_game()

    def return_to_lobby_after_game(self):
        # add the players to waiting list, maintain numbers and run matchmaking (since we're adding new players)
        for player in self.players:
            # chess_server.ChessServer.waiting_list.append(player)
            list = []
            list.append(player)
            server.send_to(
                list,
                "You have been put in the matchmaking lobby again but won't be able to play the same opponent."
            )
            # maintaining numbers
            # chess_server.ChessServer.matchmakingplayers = chess_server.ChessServer.matchmakingplayers + 1
            running.playing_players = running.playing_players - 1

        # SPECIAL COMMAND CODE to clients
        for player in self.players:
            list_two = []
            list_two.append(player)
            server.send_to(list_two, "Type in MATCH to be matched again immediately.")
            server.send_to(list_two, "WAITINGMATCH")

    def get_message(self, message, player):
        # processes messages and return True/False depending if it was valid
        if (str(message) == "FORFEIT"):
            if (player == self.players[0]):
                list = []
                list.append(self.players[1])
                self.declare_winner(list, "The opposite player has forfeited the game")
                return True
            else:
                list = []
                list.append(self.players[0])
                self.declare_winner(list, "The opposite player has forfeited the game")
                return True

        elif (self.verify_move(message) == True):
            self.make_move(message)
            return True
        else:
            list = []
            list.append(player)
            server.send_to(list, "Incorrect command, try again")
            return False

    def verify_move(self, message):
        # verifies moves
        try:
            if (chess.Move.from_uci(message) in self.board.legal_moves):
                return True
            else:

                return False
        except (ValueError, IndexError) as wrongformatorillegalmove:
            return False

    def make_move(self, message):
        # Makes the move on the board
        self.board.push_uci(message)
        self.this_turn_move_made = True
