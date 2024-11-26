from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import contextlib
import time
import uvicorn
import threading
import subprocess
import json
import os
import signal
import asyncio


app = FastAPI()
received_start_event = threading.Event() 

@app.post("/start") 
async def start_node(request: Request):

    data = await request.json()
    file_name = "config.json"


    #ADJUST THE LOG DIR AND CONFIG DIR TO RELATIVE PATH INSTEAD OF ABSOLUTE -> CURRENTLY I AM ASSUMING THAT WE START IN THE ROOT
    #DIRECTORY WHERE NEBULA IS LOCATED -> ATM THIS IS THE DIRECTORY '/Desktop/NEBULA'

    if data["tracking_args"]["log_dir"][0] == "/":
        data["tracking_args"]["log_dir"] = data["tracking_args"]["log_dir"][1:]

    if data["tracking_args"]["config_dir"][0] == "/":
        data["tracking_args"]["config_dir"] = data["tracking_args"]["config_dir"][1:]


    current_directory = os.path.dirname(os.path.abspath(__file__))
    file_name = "config.json"
    file_path = f"{current_directory}/{file_name}"

    try:
        # Write the file
        with open(file_path, "w") as config_file:
            json.dump(data, config_file, indent=2)
            print("JSON file written successfully")
    except Exception as e:
        print("Failed to write data to file")
        print(e)
        return JSONResponse(content={"error": "Failed to write data"}, status_code=500)
    return


def run_subprocess(directory_path, file_name):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    node_path = os.path.join(current_dir, "../node.py")
    config_path = f'{directory_path}/{file_name}'
    print(current_dir)
    print(node_path)
    print(config_path)

    command = ["python3", node_path, config_path]
    try:
        print("EXECUTING SUBPROCESS")
        subprocess.run(command, check=True)
        print("Subprocess started successfully")
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e}")


class Server(uvicorn.Server):
    def install_signal_handler(self):
        pass

    @contextlib.contextmanager
    def run_in_thread(self):
        thread = threading.Thread(target=self.run)
        thread.start()
        try:
            while not self.started:
                time.sleep(1e-3)
            yield
        finally:
            self.should_exit = True
            thread.join()



def main():
    #directory of this file
    current_directory = os.path.dirname(os.path.abspath(__file__))
    file_name = "config.json"
    file_path = f"{current_directory}/{file_name}"
    
    if os.path.exists(file_path):
        os.remove(file_path)
        print("file has been removed")

    
    config = uvicorn.Config("start:app", host="0.0.0.0")
    server = Server(config=config)

    with server.run_in_thread():
        print("Server is running...")

        while not os.path.exists(file_path):
            time.sleep(1)
    
    print("Server has been stopped.")        
    
    config_data = None
            
    with open(file_path, "r") as config_file:
        config_data = json.load(config_file)
        
    #WRITE CONFIG FILE INTO LOCATION SO THAT IT MATCHES THE 'DEFAULT' CONFIGURATION (when it runs with docker)

    directory_path = f'{config_data["tracking_args"]["config_dir"]}'
    file_name = f'participant_{config_data["device_args"]["idx"]}.json'

    try:
        if not os.path.exists(directory_path): 
            os.makedirs(directory_path)
            print(f"Created directory: {directory_path}")
        
        # Write the file
        with open(f'{directory_path}/{file_name}', "w") as config_file:
            print(f"Writing to file: {directory_path}/{file_name}")
            json.dump(config_data, config_file, indent=2)
            print("JSON file written successfully")
    except Exception as e:
        print("Failed to write data to file")
        print(e)
        return JSONResponse(content={"error": "Failed to write data"}, status_code=500)
    
    run_subprocess(directory_path, file_name)



if __name__ == "__main__":
    main()
