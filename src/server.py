from datetime import datetime

from flask import request
from flask_socketio import send


class running:
    players = []  # list of all players connected
    waiting_players = []  # list of players waiting to be matched
    games = []  # list of all games


def on_connect():

    # what happens when somebody connects
    print(datetime.now().strftime("%H:%M") + " New connection made")

    running.players.append(request.sid)

    welcome()

    send_to(running.waiting_players, "New player has connected and wants to play!")

    running.waiting_players.insert(0, request.sid)

    match_making()


def on_disconnect():

    # Maintaining numbers and lists of ALL connected players
    running.players.remove(request.sid)

    # Disconnected player was in a waiting list
    if request.sid in running.waiting_players:
        running.waiting_players.remove(request.sid)

    # Disconnected player was in a game, checking
    for game in running.games:
        if request.sid in game.players:
            print("Player in a chess game has disconnected")
            game.player_disconnected(request.sid)

    print("Connection Lost and handled by the server")


def on_message(line):

    # we got something from a client
    print(datetime.now().strftime("%H:%M ") + f"Received a message: {line}")
    
    if not line:
        # the message was somehow incorrect, sending special client side code to try again
        send_to([request.sid], "TRYAGAIN")

    # is the client playing in a game
    player_in_game = False

    for game in running.games:

        if request.sid in game.players:

            player_in_game = True

            if request.sid == game.players[game.player_turn] and not game.is_gameover:

                if game.get_message(line, request.sid):
                    print(datetime.now().strftime("%H:%M") + " Legit command was received and processed")
                    # Engange the next turn function
                    game.after_move()

                else:
                    # the message was somehow incorrect, sending special client side code to try again
                    send_to([request.sid], "TRYAGAIN")

    if not player_in_game and line == "MATCH" and request.sid not in running.waiting_players:
        # the client is not playing in a game
        running.waiting_players.append(request.sid)
        match_making()


def send_to(sids, text):
    # message privately everyone on the list
    for sid in sids:
        send(text, to=sid)


def welcome():
    # a bunch of on-login messages
    send("Welcome to Chessroad.")
    send("Server time: " + datetime.now().strftime("%H:%M"))
    send("Connected players: " + str(len(running.players)))
    send("Available players for matchmaking: " + str(len(running.waiting_players) + 1))


def match_making():
    # Find two players on a waiting list and make them play
    # Is there enough players in waiting queue
    if (len(running.waiting_players) >= 2):
        
        print(datetime.now().strftime("%H:%M") + " Matchmaking two players..")

        # Creating a shortlist of matched players at the moment
        pair = []
        pair.append(running.waiting_players.pop(0))
        pair.append(running.waiting_players.pop(0))

        # Messaging players that a game has been found
        send_to(pair, "Found a pair.. Connecting")

        make_game(pair)

    else:
        # Not enough players, you have to wait!
        send("Please wait to be matched with another player")


def make_game(pair):

    # Makes the game given list of any free two players

    # Sending over the command codes to initialize game modes on clients
    send_to(pair, "GAMEMODE")

    # running the game
    import src.game as game
    the_game = game.Game(pair)
    running.games.append(the_game)
    
    print(datetime.now().strftime("%H:%M") + " Hosted a game. ID = " + str(the_game.game_id))
