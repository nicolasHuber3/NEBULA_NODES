from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from globals import event

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


def run_scenario(path_config_dir, file_name):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    node_path = os.path.join(current_dir, "../node.py")
    config_path = f'{path_config_dir}/{file_name}'
    command = ["python3", node_path, config_path]
    
    event.set()
    try:
        subprocess.run(command, check=True)
        print("Subprocess started successfully")
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e}")
        

def save_config_file(path, file_name, data):
    try:
        if not os.path.exists(path): 
            os.makedirs(path)
            print(f"Created directory: {path}")
        
        # Write the file
        with open(f'{path}/{file_name}', "w") as config_file:
            json.dump(data, config_file, indent=2)
            print("JSON file written successfully")
    except Exception as e:
        print("Failed to write data to file")
        print(e)
        return JSONResponse(content={"error": "Failed to write data"}, status_code=500)


@app.post("/start") 
async def start_node(request: Request, background_tasks: BackgroundTasks):
    print("RECEIVED DATA")
    data = await request.json()

    #ADJUST THE LOG DIR AND CONFIG DIR TO RELATIVE PATH INSTEAD OF ABSOLUTE
    if data["tracking_args"]["log_dir"][0] == "/":
        data["tracking_args"]["log_dir"] = data["tracking_args"]["log_dir"][1:]

    if data["tracking_args"]["config_dir"][0] == "/":
        data["tracking_args"]["config_dir"] = data["tracking_args"]["config_dir"][1:]

    
    path = f'{data["tracking_args"]["config_dir"]}'
    file_name = f'participant_{data["device_args"]["idx"]}.json'
    
    save_config_file(path, file_name, data)
    
    background_tasks.add_task(run_scenario, path, file_name)
    return


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
    config = uvicorn.Config("start:app", host="0.0.0.0")
    server = Server(config=config)

    with server.run_in_thread():
        event.wait()

    print("Server has been stopped.")        




if __name__ == "__main__":
    main()
