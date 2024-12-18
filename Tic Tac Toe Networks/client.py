import sys
import threading
import socket

username = None
game_ended = False
client_exit = False
is_viewer = False
game_end_received = threading.Event()

def connect_to_server(server_address, port):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((server_address, port))
    except ConnectionRefusedError:
        print(f"Error: cannot connect to server at {server_address}:{port}.")
        sys.exit(1)
    print("Connected to server")
    return client

def receive_messages(client):
    global game_ended, client_exit
    while not client_exit:
        try:
            response = client.recv(8192).decode()
            if not response:
                print("Server closed the connection.")
                break
            handle_response(response, client)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            print("Connection to the server has been lost.")
            break
    client_exit = True
    game_end_received.set()

def handle_response(response, client):
    global username, game_ended
    if response.startswith("LOGIN:ACKSTATUS:"):
        status_code = response.split(":")[2]
        if status_code == "0":
            print("Login successful.")
        elif status_code == "1":
            print("Error: Username not found.")
        elif status_code == "2":
            print("Error: Incorrect password.")
        elif status_code == "3":
            print("Error: Missing username or password.")
    elif response.startswith("REGISTER:ACKSTATUS:"):
        status_code = response.split(":")[2]
        if status_code == "0":
            print("Registration successful.")
        elif status_code == "1":
            print("Error: Username already exists.")
        elif status_code == "2":
            print("Error: Missing username or password.")
        elif status_code == "3":
            print("Error: Password is too short (minimum 6 characters).")
        elif status_code == "4":
            print("Error: Username and password must be alphanumeric.")
    # Handle ROOMLIST response
    elif response.startswith("ROOMLIST:ACKSTATUS:"):
        parts = response.split(":")
        status_code = parts[2]
        if status_code == "0":
            room_list = parts[3].split(",") if len(parts) > 3 else []
            print("Available rooms:")
            for room in room_list:
                print(room)
        elif status_code == "1":
            print("Error: Invalid mode for room list.")
    # Handle CREATE response
    elif response.startswith("CREATE:ACKSTATUS:"):
        status_code = response.split(":")[2]
        if status_code == "0":
            print("Room created successfully.")
        elif status_code == "1":
            print("Error: Invalid room name.")
        elif status_code == "2":
            print("Error: Room name already exists.")
        elif status_code == "3":
            print("Error: Maximum number of rooms reached.")
    # Handle JOIN response
    elif response.startswith("JOIN:ACKSTATUS:"):
        status_code = response.split(":")[2]
        if status_code == "0":
            print("Joined room successfully.")
        elif status_code == "1":
            print("Error: Room does not exist.")
        elif status_code == "2":
            print("Error: Room is full.")
        elif status_code == "3":
            print("Error: Invalid mode.")
        elif status_code == "4":
            print("Error: You are already in the room.")
    # Handle BOARDSTATUS response
    elif response.startswith("BOARDSTATUS:"):
        board_status = response.split(":")[1]
        print("Current board status:")
        for i in range(0, 9, 3):
            row = board_status[i:i+3]
            formatted_row = ' | '.join(cell if cell != '0' else ' ' for cell in row)
            print(f" {formatted_row} ")
            if i < 6:
                print("-----------")
        if not is_viewer:
            print("\nIt is your turn." if len(board_status.replace('0', '')) % 2 == 0 else "\nIt is the opposing player's turn.")
    elif response.startswith("GAMEEND:"):
        parts = response.split(":")
        board_status = parts[1]
        status_code = int(parts[2])
        if status_code == 0:
            winner = parts[3]
            print(f"Game ended. {winner} won!")
        elif status_code == 1:
            print("Game ended in a draw.")
        elif status_code == 2:
            winner = parts[3]
            print(f"Game ended. {winner} won due to the opposing player forfeiting.")
        print("Game has ended. You can start a new game or quit.")
        game_ended = True
        game_end_received.set()
    elif response == "BADAUTH":
        print("Error: You must be logged in to perform this action.")
    elif response == "NOROOM":
        print("Error: You are not currently in a room.")
    else:
        print(f"Received: {response}")

def main():
    global username, game_ended, client_exit, is_viewer
    if len(sys.argv) != 3:
        print("Error: Expecting 2 arguments: <server address> <port>")
        sys.exit(1)
    server_address = sys.argv[1]
    port = int(sys.argv[2])
    client = connect_to_server(server_address, port)

    receive_thread = threading.Thread(target=receive_messages, args=(client,), daemon=True)
    receive_thread.start()

    try:
        while not client_exit:
            command = input("Enter command: ").strip().upper()
            if command == "QUIT":
                if is_viewer and not game_ended:
                    print("Waiting for the game to end before quitting...")
                    game_end_received.wait()
                break
            elif command == "LOGIN":
                username = input("Enter username: ").strip()
                password = input("Enter password: ").strip()
                client.send(f"LOGIN:{username}:{password}".encode())
            elif command == "REGISTER":
                username = input("Enter username: ").strip()
                password = input("Enter password: ").strip()
                client.send(f"REGISTER:{username}:{password}".encode())
            elif command == "ROOMLIST":
                mode = input("Do you want to have a room list as player or viewer? (Player/Viewer): ").strip().upper()
                if mode in ["PLAYER", "VIEWER"]:
                    client.send(f"ROOMLIST:{mode}".encode())
                else:
                    print("Error: Please input a valid mode.")
            elif command == "CREATE":
                room_name = input("Enter room name you want to create: ").strip()
                client.send(f"CREATE:{room_name}".encode())
            elif command == "JOIN":
                room_name = input("Enter room name you want to join: ").strip()
                mode = input("You wish to join the room as: (Player/Viewer): ").strip().upper()
                if mode in ["PLAYER", "VIEWER"]:
                    client.send(f"JOIN:{room_name}:{mode}".encode())
                else:
                    print("Error: Please input a valid mode.")
            elif command == "PLACE":
                if game_ended:
                    print("The game has ended. Please start a new game.")
                elif is_viewer:
                    print("Error: Viewers cannot make moves.")
                else:
                    try:
                        x = int(input("Enter column (0-2): ").strip())
                        y = int(input("Enter row (0-2): ").strip())
                        if x in range(3) and y in range(3):
                            client.send(f"PLACE:{x}:{y}".encode())
                        else:
                            print("Error: Column/Row values must be between 0 and 2.")
                    except ValueError:
                        print("Error: Column/Row values must be integers.")
            elif command == "FORFEIT":
                if game_ended:
                    print("The game has already ended.")
                elif is_viewer:
                    print("Error: Viewers cannot forfeit.")
                else:
                    client.send("FORFEIT".encode())
            else:
                print(f"Unknown command: {command}")
    except EOFError:
        print("Input stream closed.")
        if is_viewer and not game_ended:
            print("Waiting for the game to end before quitting...")
            game_end_received.wait()
    finally:
        print("Disconnecting from the server...")
        client_exit = True
        client.close()

    receive_thread.join(timeout=2)  # Wait for receive thread to finish, but with a timeout

if __name__ == "__main__":
    main()