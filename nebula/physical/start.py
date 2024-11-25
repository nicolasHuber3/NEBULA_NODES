from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

import subprocess
import json
import os


app = FastAPI()

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

    
    #WRITE CONFIG FILE INTO LOCATION SO THAT IT MATCHES THE 'DEFAULT' CONFIGURATION (when it runs with docker)

    directory_path = f'{data["tracking_args"]["config_dir"]}'
    file_name = f'participant_{data["device_args"]["idx"]}.json'

    try:
        if not os.path.exists(directory_path): 
            os.makedirs(directory_path)
            print(f"Created directory: {directory_path}")
        
        # Write the file
        with open(f'{directory_path}/{file_name}', "w") as config_file:
            print(f"Writing to file: {directory_path}/{file_name}")
            json.dump(data, config_file, indent=2)
            print("JSON file written successfully")
    except Exception as e:
        print("Failed to write data to file")
        print(e)
        return

    current_dir = os.path.dirname(os.path.abspath(__file__))
    node_path = os.path.join(current_dir, "../node.py")
    config_path = f'{directory_path}/{file_name}'

    command = ["python3", node_path, config_path]
    
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
        print(result.stdout) 
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e}")



