import socket
import sys
import selectors
import json
import bcrypt
from pathlib import Path


def load_config(config_path):
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        port = config.get('port')
        user_db_path = config.get('userDatabase')

        if not (1024 <= port <= 65535):
            raise ValueError("Error: port number out of range")

        user_db_path = Path(user_db_path).expanduser()
        if not user_db_path.exists():
            raise FileNotFoundError(f"Error: {user_db_path} doesn't exist.")

        return port, user_db_path
    except FileNotFoundError:
        print(f"Error: {config_path} doesn't exist.")
        exit(1)
    except json.JSONDecodeError:
        print(f"Error: {config_path} is not in a valid JSON format.")
        exit(1)
    except KeyError as e:
        print(f"Error: {config_path} missing key(s): {e}")
        exit(1)


def load_user_database(user_db_path):
    try:
        with open(user_db_path, 'r') as f:
            users = json.load(f)
        if not isinstance(users, list):
            raise ValueError("Error: user database is not a JSON array.")
        return users
    except json.JSONDecodeError:
        print(f"Error: {user_db_path} is not in a valid JSON format.")
        exit(1)
    except Exception as e:
        print(str(e))
        exit(1)

# Selector-based non-blocking I/O server setup
class TicTacToeServer:
    def __init__(self, config_path):
        self.port, self.user_db_path = load_config(config_path)
        self.user_db = load_user_database(self.user_db_path)
        self.sel = selectors.DefaultSelector()
        self.authenticated_users = {}  # socket: username
        self.rooms = {}  # room_name: Room object

    def start(self):
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Allow the server to reuse the address
        server_sock.bind(('0.0.0.0', self.port))
        server_sock.listen(5)
        server_sock.setblocking(False)
        self.sel.register(server_sock, selectors.EVENT_READ, self.accept)
        print(f"Server listening on port {self.port}")

        try:
            while True:
                events = self.sel.select()
                for key, mask in events:
                    callback = key.data
                    callback(key.fileobj)
        except KeyboardInterrupt:
            print("Server shutting down.")
        finally:
            self.sel.close()

    def accept(self, sock):
        client_sock, addr = sock.accept()
        print(f"Accepted connection from {addr}")
        client_sock.setblocking(False)
        self.sel.register(client_sock, selectors.EVENT_READ, self.handle_client)

    def handle_client(self, client_sock):
        try:
            data = client_sock.recv(8192)
            if data:
                self.process_request(client_sock, data.decode('ascii'))
            else:
                # Client disconnected
                self.handle_client_disconnect(client_sock)
        except ConnectionResetError:
            # Client disconnected abruptly
            self.handle_client_disconnect(client_sock)

    def handle_client_disconnect(self, client_sock):
        # Find the room the client was in, if any
        for room in self.rooms.values():
            if client_sock in room.players:
                room.forfeit_game(client_sock)
                break
        self.sel.unregister(client_sock)
        client_sock.close()

    def process_request(self, client_sock, request):
        command = request.strip().split(":")
        if command[0] == 'LOGIN':
            self.handle_login(client_sock, command[1:])
        elif command[0] == 'REGISTER':
            self.handle_register(client_sock, command[1:])
        elif command[0] == 'ROOMLIST':
            self.handle_roomlist(client_sock, command[1:])
        elif command[0] == 'CREATE':
            self.handle_create_room(client_sock, command[1:])
        elif command[0] == 'JOIN':
            self.handle_join_room(client_sock, command[1:])
        elif command[0] == 'PLACE':
            self.handle_place(client_sock, command[1:])
        elif command[0] == 'FORFEIT':
            self.handle_forfeit(client_sock)
        else:
            client_sock.sendall(b"Unknown command\n")

    # Authentication handling
    def handle_login(self, client_sock, args):
        if len(args) != 2:
            client_sock.sendall(b"LOGIN:ACKSTATUS:3\n")
            return

        username, password = args
        user = next((u for u in self.user_db if u['username'] == username), None)

        if user:
            if bcrypt.checkpw(password.encode(), user['password'].encode()):
                self.authenticated_users[client_sock] = username
                client_sock.sendall(b"LOGIN:ACKSTATUS:0\n")
                #print(f"User {username} authenticated.")
            else:
                client_sock.sendall(b"LOGIN:ACKSTATUS:2\n")
               # print(f"Wrong password for user {username}")
        else:
            client_sock.sendall(b"LOGIN:ACKSTATUS:1\n")
           # print(f"User {username} not found.")

    def handle_register(self, client_sock, args):
        if len(args) != 2:
            client_sock.sendall(b"REGISTER:ACKSTATUS:2\n")
            return

        username, password = args
        if any(u['username'] == username for u in self.user_db):
            client_sock.sendall(b"REGISTER:ACKSTATUS:1\n")
            #print(f"User {username} already exists.")
        else:
            hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            new_user = {"username": username, "password": hashed_pw}
            self.user_db.append(new_user)
            self.save_user_database()
            client_sock.sendall(b"REGISTER:ACKSTATUS:0\n")
            #print(f"User {username} registered.")

    def save_user_database(self):
        with open(self.user_db_path, 'w') as f:
            json.dump(self.user_db, f, indent=4)

    # Room management
    def handle_roomlist(self, client_sock, args):
        if client_sock not in self.authenticated_users:
            client_sock.sendall(b"BADAUTH\n")
            return
        if len(args) != 1 or args[0].upper() not in ['PLAYER', 'VIEWER']:
            client_sock.sendall(b"ROOMLIST:ACKSTATUS:1\n")
            return

        mode = args[0].upper()
        room_list = [room.name for room in self.rooms.values() if (mode == 'PLAYER' and not room.is_full()) or mode == 'VIEWER']
        room_list_str = ','.join(sorted(room_list))
        client_sock.sendall(f"ROOMLIST:ACKSTATUS:0:{room_list_str}\n".encode())

    def handle_create_room(self, client_sock, args):
        if client_sock not in self.authenticated_users:
            client_sock.sendall(b"BADAUTH\n")
            return
        if len(args) != 1:  # Fix here: check for exactly one argument
            client_sock.sendall(b"CREATE:ACKSTATUS:4\n")
            return

        room_name = args[0]

        if not all(c.isalnum() or c in '-_ ' for c in room_name):
            client_sock.sendall(b"CREATE:ACKSTATUS:1\n")
            return

        if room_name in self.rooms:
            client_sock.sendall(b"CREATE:ACKSTATUS:2\n")
        elif len(self.rooms) >= 256:
            client_sock.sendall(b"CREATE:ACKSTATUS:3\n")
        else:
            new_room = Room(room_name, self)  # Pass self (server) to the Room constructor
            self.rooms[room_name] = new_room
            new_room.add_player(client_sock, self.authenticated_users[client_sock])
            client_sock.sendall(f"CREATE:ACKSTATUS:0\n".encode())
            #print(f"Room {room_name} created by {self.authenticated_users[client_sock]}.")

    def handle_join_room(self, client_sock, args):
        if client_sock not in self.authenticated_users:
            client_sock.sendall(b"BADAUTH\n")
            return
        if len(args) != 2 or args[1].upper() not in ['PLAYER', 'VIEWER']:
            client_sock.sendall(b"JOIN:ACKSTATUS:3\n")
            return

        room_name, mode = args
        if room_name not in self.rooms:
            client_sock.sendall(b"JOIN:ACKSTATUS:1\n")
        else:
            room = self.rooms[room_name]
            if mode.upper() == 'PLAYER':
                if room.is_full():
                    client_sock.sendall(b"JOIN:ACKSTATUS:2\n")
                else:
                    client_sock.sendall(b"JOIN:ACKSTATUS:0\n")
                    room.add_player(client_sock, self.authenticated_users[client_sock])
                    if room.is_full():
                        room.start_game()
            else:  # VIEWER
                client_sock.sendall(b"JOIN:ACKSTATUS:0\n")
                room.add_viewer(client_sock)
                if room.is_full():
                    current_turn_user = room.players[room.current_turn]
                    opposing_user = room.players[room.get_opposing_player()]
                    client_sock.sendall(f"INPROGRESS:{current_turn_user}:{opposing_user}\n".encode())



    def handle_place(self, client_sock, args):
        if client_sock not in self.authenticated_users:
            client_sock.sendall(b"BADAUTH\n")
            return

        # Find the room where the player is and process the move
        for room in self.rooms.values():
            if room.has_player(client_sock):
                room.place_marker(client_sock, args)
                return
        client_sock.sendall(b"NOROOM\n")

    def handle_forfeit(self, client_sock):
        if client_sock not in self.authenticated_users:
            client_sock.sendall(b"BADAUTH\n")
            return

        # Find the room where the player is and process the forfeit
        for room in self.rooms.values():
            if room.has_player(client_sock):
                room.forfeit_game(client_sock)
                return
        client_sock.sendall(b"NOROOM\n")

    def is_valid_room_name(self, room_name):
        # Room names may contain alphanumeric characters, dashes, spaces, and underscores, and must be <= 20 characters
        if len(room_name) > 20 or not all(c.isalnum() or c in '-_ ' for c in room_name):
            return False
        return True

# Room class for managing individual game rooms
class Room:
    def __init__(self, name, server):
        self.name = name
        self.server = server
        self.players = {}  # {sock: username}
        self.viewers = []  # list of viewer sockets
        self.board = ['0'] * 9  # 3x3 board initialised as empty
        self.current_turn = None
        self.finished = False
        self.last_move_index = None

    def add_player(self, client_sock, username):
        if len(self.players) < 2:
            self.players[client_sock] = username # Start the game when both players are present

    def start_game(self):
        if self.is_full():
            self.current_turn = list(self.players.keys())[0]
            player1, player2 = self.players.values()
            message = f"BEGIN:{player1}:{player2}\n"
            for sock in self.players.keys():
                sock.sendall(message.encode())
            for viewer in self.viewers:
                viewer.sendall(message.encode())
            #self.broadcast_board_status()



    def broadcast_begin(self):
        player1, player2 = self.players.values()
        message = f"BEGIN:{player1}:{player2}\n"
        for sock in self.players.keys():
            sock.sendall(message.encode())
        for viewer in self.viewers:
            viewer.sendall(message.encode())
       # print(f"Game started between {player1} and {player2}.")


    def add_viewer(self, client_sock):
        self.viewers.append(client_sock)
        # Send current board status to the new viewer
        #self.broadcast_board_status()
    #def send_in_progress(self, client_sock, current_turn_user, opposing_user):
      #  message = f"INPROGRESS:{current_turn_user}:{opposing_user}\n"
       # client_sock.sendall(message.encode())

    def is_full(self):
        return len(self.players) == 2

    def has_player(self, client_sock):
        return client_sock in self.players

    def get_opposing_player(self):
        return [sock for sock in self.players if sock != self.current_turn][0]

    def place_marker(self, client_sock, args):
        if self.finished:
            client_sock.sendall(b"GAMEEND\n")
            return

        if client_sock != self.current_turn:
            self.broadcast_board_status()  # Send the current board status
            return

        x, y = int(args[0]), int(args[1])
        index = y * 3 + x

        marker = '1' if client_sock == list(self.players.keys())[0] else '2'
        self.board[index] = marker

        if self.check_winner(marker):
            winner = self.players[client_sock]
            self.broadcast_game_end(winner)  # Game won by this player
            self.finished = True
        elif '0' not in self.board:
            self.broadcast_game_end(None)  # Draw
            self.finished = True
        else:
            self.broadcast_board_status()
            self.current_turn = self.get_opposing_player()


    def broadcast_board_status(self):
        board_status = ''.join(self.board)
        message = f"BOARDSTATUS:{board_status}\n"

        # Send board status to all players
        for sock in self.players.keys():
            sock.sendall(message.encode())

        # Send board status to all viewers
        for viewer in self.viewers:
            viewer.sendall(message.encode())
        player_sockets = list(self.players.keys())
        current_player = self.players[self.current_turn]
        next_player = self.players[self.get_opposing_player()]





    def broadcast_game_end(self, winner, forfeit=False):
        board_status = ''.join(self.board)

        if forfeit:
            # Game ended due to forfeit
            message = f"GAMEEND:{board_status}:2:{winner}\n"
        elif winner:
            # Game won by a player
            message = f"GAMEEND:{board_status}:0:{winner}\n"
        else:
            # Game ended in a draw
            message = f"GAMEEND:{board_status}:1\n"

        # Send the game end message to all players and viewers
        for sock in self.players.keys():
            sock.sendall(message.encode())
        for viewer in self.viewers:
            viewer.sendall(message.encode())

        self.finished = True  # Mark the game as finished
        self.cleanup_room()



    def cleanup_room(self):
        # Remove this room from the server's rooms dictionary
        if self.name in self.server.rooms:
            del self.server.rooms[self.name]
        # Clear players and viewers
        self.players.clear()
        self.viewers.clear()

    def forfeit_game(self, client_sock):
        if self.finished:
            client_sock.sendall(b"GAMEEND\n")
            return

        winner_sock = self.get_opposing_player()
        winner = self.players[winner_sock]
        self.broadcast_game_end(winner, forfeit=True)  # Indicate the game ended due to a forfeit
        self.finished = True


    def check_winner(self, marker):
        win_positions = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],  # Rows
            [0, 3, 6], [1, 4, 7], [2, 5, 8],  # Columns
            [0, 4, 8], [2, 4, 6]              # Diagonals
        ]
        for positions in win_positions:
            if all(self.board[i] == marker for i in positions):
                return True
        return False


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Error: Expecting 1 argument: <server config path>")
        exit(1)
    config_path = sys.argv[1]
    server = TicTacToeServer(config_path)
    server.start()