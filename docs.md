## Nebula

### Frontend

In order to run Nebula on Rasberry Pis we need to be able to select the option to run Nebula on physical devices. 
For this we need to make the 'Physical devices' button clickable:

```
<input class="form-check-input" type="radio" name="deploymentRadioOptions" id="physical-devices-radio"
    value="physical">
<label class="form-check-label" for="physical-devices-radio">Physical devices</label>
```

Additionally, we need to be able to manually set the IP-Address and the Port of the Rasberry Pis in the frontend. 
In order for the changes to be saved correctly, we added `scenarioStorage.replaceScenario()` to the method below:

``` 
//SAVE CHANGES BUTTON FOR PARTICIPANTS DETAILS MODAL
document.getElementById("participant-modal-save").addEventListener("click", function () {
    const participant = Graph.graphData().nodes[i];
    participant.ip = document.getElementById("participant-" + i + "-ip").value;
    participant.port = document.getElementById("participant-" + i + "-port").value;
    Graph.graphData(Graph.graphData());
    //UPDATE SCENARIO WITH UPDATED NODE IP AND PORT IF NECESSARY
    scenarioStorage.replaceScenario();
});
```

With these two changes, we can now select Nebula to run on physical devices and manually configure the IP and Port of
the devices.

### Backend

When Nebula is started `main` calls `Controller.start` which performs various set up steps, including calling the 
`run_frontend` method which generates and starts the Docker Compose file for the frontend dynamically:

``` 
subprocess.check_call(
                [
                    "docker",
                    "compose",
                    "-f",
                    f"{os.path.join(os.environ['NEBULA_ROOT'], 'nebula', 'frontend', 'docker-compose.yml')}",
                    "up",
                    "--build",
                    "-d",
                ]
            )
```

In the generated docker-compose.yml file:

``` 
services:

    nebula-frontend:
        container_name: nebula-frontend
        image: nebula-frontend
        build:
            context: .
```

``` 
        ports:
            - 6060:80
            - 8080:8080
        networks:
            nebula-net-base:
                ipv4_address: 192.168.10.100


networks:
    nebula-net-base:
        name: nebula-net-base
        driver: bridge
        ipam:
            config:
                - subnet: 192.168.10.0/24
                  gateway: 192.168.10.1
```

This will lead to Docker Compose looking for the Dockerfile in the current directory and when found run the commands of
the Dockerfile to build the image `nebula-frontend`. The container `nebula-frontend` is started which performs the various
set up steps defined. The port 6060 on the host machine is mapped to the port 80 inside the container which makes the 
`nebula-frontend` application accessible through the port 6060 of the host machine. Additionally,
the custom network `nebula-net-base` for the nebula-frontend service is configured, allowing Containers withing the subnet
192.168.10.0/24 (addresses from 192.168.10.1 to 192.168.10.254) to communicate with each other. The gateway (address to 
communicate with other networks) is set to 192.168.10.1. The `nebula-frontend` container is assigned the fix IP address
192.168.10.100 and connected to the `nebula-net-base` network.

Then `start_service.sh` is run which starts Nginx (reverse proxy which routes the incoming request to the application
server Uvicorn which listens on port $NEBULA_SOCK). `uvicorn app:app --uds /tmp/$NEBULA_SOCK ...` starts the Uvicorn server running `app.py`
and listening on the unix domain socket `/temp/nebula.sock`.

``` 
if __name__ == "__main__":
    # Parse args from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000, help="Port to run the frontend on.")
    args = parser.parse_args()
    logging.info(f"Starting frontend on port {args.port}")
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=args.port)
```

The federated learning process starts when a user runs Nebula by clicking run nebula in the frontend. This sends a post
request to the following endpoint:

``` 
@app.post("/nebula/dashboard/deployment/run")
async def nebula_dashboard_deployment_run(request: Request, background_tasks: BackgroundTasks, session: Dict = Depends(get_session)):
    if "user" not in session.keys() or session["role"] in ["demo", "user"] and get_running_scenario():
        raise HTTPException(status_code=401)

    if request.headers.get("content-type") != "application/json":
        raise HTTPException(status_code=401)

    stop_all_scenarios()
    finish_scenario_event.clear()
    stop_all_scenarios_event.clear()
    data = await request.json()
    global scenarios_finished, scenarios_list_length
    scenarios_finished = 0
    scenarios_list_length = len(data)
    logging.info(f"Running deployment with {len(data)} scenarios")
    background_tasks.add_task(run_scenarios, data, session["role"])
    return RedirectResponse(url="/nebula/dashboard", status_code=303)
    # return Response(content="Success", status_code=200)
```

which in turn runs `run_scenarios`:

``` 
# Deploy the list of scenarios
async def run_scenarios(data, role):
    global scenarios_finished
    for scenario_data in data:
        finish_scenario_event.clear()
        logging.info(f"Running scenario {scenario_data['scenario_title']}")
        scenario_name = await run_scenario(scenario_data, role)
        # Waits till the scenario is completed
        while not finish_scenario_event.is_set() and not stop_all_scenarios_event.is_set():
            await asyncio.sleep(1)
        if stop_all_scenarios_event.is_set():
            stop_all_scenarios_event.clear()
            stop_scenario(scenario_name)
            return
        scenarios_finished = scenarios_finished + 1
        stop_scenario(scenario_name)
        await asyncio.sleep(5)
```

which calls `run_scenario` with the data for the scenario (amt of nodes, configuration of nodes, ...):

```
async def run_scenario(scenario_data, role):
    from nebula.scenarios import ScenarioManagement
    import subprocess

    # Manager for the actual scenario
    scenarioManagement = ScenarioManagement(scenario_data)
    
    #...

    # Run the actual scenario
    try:
        if scenarioManagement.scenario.mobility:
            additional_participants = scenario_data["additional_participants"]
            schema_additional_participants = scenario_data["schema_additional_participants"]
            scenarioManagement.load_configurations_and_start_nodes(additional_participants, schema_additional_participants)
        
    #...
```


this call `load_configuartions_and_start_nodes` which calls `start_nodes_docker` (in case where docker has been selected)

`start_nodes_docker` generates a docker-compose.yml file dynamically to set up and run multiple Docker containers, 
each representing a participant node in a federated learning environment. `nebula-core` defines the internal Docker
bridge network `nebula-net-scenario` with a custom subnet and gateway, which allows containers to communicate with each other using specific IP addresses.
Each container is attached to `nebula-net-scenario` as well as `nebula-net-base`, which has been defined and started by 
the image/container `nebula-frontend`.

``` 
services:

    participant0:
        image: nebula-core
        restart: no
        volumes:
            - /home/nicolas/nebula-venv/nebula:/nebula
            - /var/run/docker.sock:/var/run/docker.sock
        extra_hosts:
            - "host.docker.internal:host-gateway"
        ipc: host
        privileged: true
        command:
            - /bin/bash
            - -c
            - |
                sleep 10 && ifconfig && echo '192.168.50.1 host.docker.internal' >> /etc/hosts && python3.11 /nebula/nebula/node.py /nebula/app/config/nebula_DFL_11_11_2024_14_58_02/participant_0.json
        networks:
            nebula-net-scenario:
                ipv4_address: 192.168.50.2
            nebula-net-base:
            
...

networks:
    nebula-net-scenario:
        name: nebula-net-scenario
        driver: bridge
        ipam:
            config:
                - subnet: 192.168.50.0/24
                  gateway: 192.168.50.1     
    nebula-net-base:
        name: nebula-net-base
        external: tru
```






First we initialize the node with various configurations like number of nodes,
model name, idx, ... trainer (e.g. lightning),

```
async def main(config): 
    n_nodes = config.participant["scenario_args"]["n_nodes"] 
    model_name = config.participant["model_args"]["model"]
    idx = config.participant["device_args"]["idx"]
```
Then we initialize node_cls:

``` 
    if config.participant["device_args"]["malicious"]:
        node_cls = MaliciousNode
    else:
        if config.participant["device_args"]["role"] == Role.AGGREGATOR:
            node_cls = AggregatorNode
        elif config.participant["device_args"]["role"] == Role.TRAINER:
            node_cls = TrainerNode
        elif config.participant["device_args"]["role"] == Role.SERVER:
            node_cls = ServerNode
        elif config.participant["device_args"]["role"] == Role.IDLE:
            node_cls = IdleNode
        else:
            raise ValueError(f"Role {config.participant['device_args']['role']} not supported")
```

where MaliciousNode, AggregatorNode, ... are child classes of Engine.

after configuring the config_keys we initialize node_cls, start the communication and deploy the federation:

```
logging.info(f"Starting node {idx} with model {model_name}, trainer {trainer.__name__}, and as {node_cls.__name__}")

    node = node_cls(model=model, dataset=dataset, config=config, trainer=trainer, security=False, model_poisoning=model_poisoning, poisoned_ratio=poisoned_ratio, noise_type=noise_type)
    await node.start_communications()
    await node.deploy_federation()
```

in ``start_communication`` start the communication manager (`communications.py`) and connect with the initial neighbors:

```
await self.cm.start()
initial_neighbors = self.config.participant["network_args"]["neighbors"].split()
for i in initial_neighbors:
    addr = f"{i.split(':')[0]}:{i.split(':')[1]}"
    await self.cm.connect(addr, direct=True)
    await asyncio.sleep(1)
```

in ``CommunicationsManager.start()``  we deploy the network engine:

```
async def start(self):
    logging.info(f"🌐  Starting Communications Manager...")
    await self.deploy_network_engine()

#set up a network server to manage incoming connections
async def deploy_network_engine(self):
    logging.info(f"🌐  Deploying Network engine...")
    #returns a server object that manages connections on this IP and port
    #network_engine listens on the network interface of self.host and listens for incoming connections on self.port
    self.network_engine = await asyncio.start_server(self.handle_connection_wrapper, self.host, self.port) #host is reader (recieves data from client) and port is writter (send data to client)
    self.network_task = asyncio.create_task(self.network_engine.serve_forever(), name="Network Engine")
    logging.info(f"🌐  Network engine deployed at host {self.host} and port {self.port}")

#wrapper function to handle incoming requests -> new task for each incoming request
#reader: A StreamReader instance, representing the data stream from the client
#writer: A StreamWriter instance, representing the data stream to the client
async def handle_connection_wrapper(self, reader, writer):
    asyncio.create_task(self.handle_connection(reader, writer))
```

the created network engine will on the address (host and port) for incoming connections/requests. Whenever a request
arrives ``handle_connection_wrapper`` will be triggered which will trigger ``handle_connection`` where if necessary 
a new ``Connection`` is established and added to ``self.connections`` with key ``connection_addr``:

```
    async def handle_connection(self, reader, writer):

        async def process_connection(reader, writer):
            try:
                addr = writer.get_extra_info("peername")
                connected_node_id = await reader.readline()
                connected_node_id = connected_node_id.decode("utf-8").strip()
                connected_node_port = addr[1]
                if ":" in connected_node_id:
                    connected_node_id, connected_node_port = connected_node_id.split(":")
                connection_addr = f"{addr[0]}:{connected_node_port}"
                direct = await reader.readline()
                direct = direct.decode("utf-8").strip()
                direct = True if direct == "True" else False
                logging.info(f"🔗  [incoming] Connection from {addr} - {connection_addr} [id {connected_node_id} | port {connected_node_port} | direct {direct}] (incoming)")

                if self.id == connected_node_id:
                    logging.info("🔗  [incoming] Connection with yourself is not allowed")
                    writer.write("CONNECTION//CLOSE\n".encode("utf-8"))
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return

                async with self.connections_manager_lock:
                    if len(self.connections) >= self.max_connections:
                        logging.info("🔗  [incoming] Maximum number of connections reached")
                        logging.info(f"🔗  [incoming] Sending CONNECTION//CLOSE to {addr}")
                        writer.write("CONNECTION//CLOSE\n".encode("utf-8"))
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                        return

                    logging.info(f"🔗  [incoming] Connections: {self.connections}")
                    if connection_addr in self.connections:
                        logging.info(f"🔗  [incoming] Already connected with {self.connections[connection_addr]}")
                        logging.info(f"🔗  [incoming] Sending CONNECTION//EXISTS to {addr}")
                        writer.write("CONNECTION//EXISTS\n".encode("utf-8"))
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                        return

                    if connection_addr in self.pending_connections:
                        logging.info(f"🔗  [incoming] Connection with {connection_addr} is already pending")
                        if int(self.host.split(".")[3]) < int(addr[0].split(".")[3]):
                            logging.info(f"🔗  [incoming] Closing incoming connection since self.host < host  (from {connection_addr})")
                            writer.write("CONNECTION//CLOSE\n".encode("utf-8"))
                            await writer.drain()
                            writer.close()
                            await writer.wait_closed()
                            return
                        else:
                            logging.info(f"🔗  [incoming] Closing outgoing connection since self.host >= host (from {connection_addr})")
                            if connection_addr in self.outgoing_connections:
                                out_reader, out_writer = self.outgoing_connections.pop(connection_addr)
                                out_writer.write("CONNECTION//CLOSE\n".encode("utf-8"))
                                await out_writer.drain()
                                out_writer.close()
                                await out_writer.wait_closed()

                    logging.info(f"🔗  [incoming] Including {connection_addr} in pending connections")
                    self.pending_connections.add(connection_addr)
                    self.incoming_connections[connection_addr] = (reader, writer)

                logging.info(f"🔗  [incoming] Creating new connection with {addr} (id {connected_node_id})")
                await writer.drain()
                connection = Connection(
                    self,
                    reader,
                    writer,
                    connected_node_id,
                    addr[0],
                    connected_node_port,
                    direct=direct,
                    config=self.config,
                )
                async with self.connections_manager_lock:
                    logging.info(f"🔗  [incoming] Including {connection_addr} in connections")
                    self.connections[connection_addr] = connection
                    logging.info(f"🔗  [incoming] Sending CONNECTION//NEW to {addr}")
                    writer.write("CONNECTION//NEW\n".encode("utf-8"))
                    await writer.drain()
                    writer.write(f"{self.id}\n".encode("utf-8"))
                    await writer.drain()
                    await connection.start()

            except Exception as e:
                logging.error(f"❗️  [incoming] Error while handling connection with {addr}: {e}")
            finally:
                if connection_addr in self.pending_connections:
                    logging.info(f"🔗  [incoming] Removing {connection_addr} from pending connections: {self.pending_connections}")
                    self.pending_connections.remove(connection_addr)
                if connection_addr in self.incoming_connections:
                    logging.info(f"🔗  [incoming] Removing {connection_addr} from incoming connections: {self.incoming_connections.keys()}")
                    self.incoming_connections.pop(connection_addr)

        await process_connection(reader, writer)
```

`connection.start()` causes the node to listen to incoming messages and to start processing the message queue
in the Connection class (connection.py):

```
    async def start(self):
        self.read_task = asyncio.create_task(self.handle_incoming_message(), name=f"Connection {self.addr} reader")
        self.process_task = asyncio.create_task(self.process_message_queue(), name=f"Connection {self.addr} processor")
```

Afterward the CommunicationsManager will establish a connection with the initial neighbor nodes in ``CommunicationsManager.connect(addr, direct=True)`` 
where a new connection will be established if it does not already exist:

```
    async def connect(self, addr, direct=True):
    
        #checking for duplicate connections
        ...
        
        else:
            if direct:
                return await self.establish_connection(addr, direct=True, reconnect=False)
            else:
                return await self.establish_connection(addr, direct=False, reconnect=False)
```

Afterwards in `node.py` in we will deploy the federation with `node.deploy_federation()` (in `engine.py`):
If the node is not the start node it will send a federation message `FEDERATION_READY` to its neighbors signaling
that the node is ready for the federation process.

If the node is a start node it will check if all the neighbors are ready. If so, it will send a `Federation_Start`
message to all its neighbors. If not, it will wait with sending the `FEDERATION_START` until all of the neighbors are ready.

```
    async def deploy_federation(self):
        await self.federation_ready_lock.acquire_async()
        if self.config.participant["device_args"]["start"]:
            logging.info(f"💤  Waiting for {self.config.participant['misc_args']['grace_time_start_federation']} seconds to start the federation")
            await asyncio.sleep(self.config.participant["misc_args"]["grace_time_start_federation"])
            if self.round is None:
                while not await self.cm.check_federation_ready():
                    await asyncio.sleep(1)
                logging.info(f"Sending FEDERATION_START to neighbors...")
                message = self.cm.mm.generate_federation_message(nebula_pb2.FederationMessage.Action.FEDERATION_START)
                await self.cm.send_message_to_neighbors(message)
                await self.get_federation_ready_lock().release_async()
                await self.create_trainer_module()
            else:
                logging.info(f"Federation already started")

        else:
            logging.info(f"Sending FEDERATION_READY to neighbors...")
            message = self.cm.mm.generate_federation_message(nebula_pb2.FederationMessage.Action.FEDERATION_READY)
            await self.cm.send_message_to_neighbors(message)
            logging.info(f"💤  Waiting until receiving the start signal from the start node")
```

the `FEDERATION_START` message triggers `_start_federation_callback` in the receiving nodes which in turn will
call `create_trainer model` which will call `_start_learning`:

```
@event_handler(nebula_pb2.FederationMessage, nebula_pb2.FederationMessage.Action.FEDERATION_START)
async def _start_federation_callback(self, source, message):
    logging.info(f"📝  handle_federation_message | Trigger | Received start federation message from {source}")
    await self.create_trainer_module()
```

in `deploy_federation` we also call `create_trainer_module`:

```
async def create_trainer_module(self):
    asyncio.create_task(self._start_learning())
    logging.info(f"Started trainer module...")
```

**Initial Round**

`create_trainer_module` calls `_start_learning`:

```
    async def _start_learning(self):
        await self.learning_cycle_lock.acquire_async()
        try:
            if self.round is None:
                self.total_rounds = self.config.participant["scenario_args"]["rounds"]
                epochs = self.config.participant["training_args"]["epochs"]
                await self.get_round_lock().acquire_async()
                self.round = 0
                await self.get_round_lock().release_async()
                await self.learning_cycle_lock.release_async()
                print_msg_box(msg=f"Starting Federated Learning process...", indent=2, title="Start of the experiment")
                direct_connections = await self.cm.get_addrs_current_connections(only_direct=True)
                undirected_connections = await self.cm.get_addrs_current_connections(only_undirected=True)
                logging.info(f"Initial DIRECT connections: {direct_connections} | Initial UNDIRECT participants: {undirected_connections}")
                logging.info(f"💤  Waiting initialization of the federation...")
                # Lock to wait for the federation to be ready (only affects the first round, when the learning starts)
                # Only applies to non-start nodes --> start node does not wait for the federation to be ready
                await self.get_federation_ready_lock().acquire_async()
                if self.config.participant["device_args"]["start"]:
                    logging.info(f"Propagate initial model updates.")
                    await self.cm.propagator.propagate("initialization")
                    await self.get_federation_ready_lock().release_async()

                self.trainer.set_epochs(epochs)
                self.trainer.create_trainer()

                await self._learning_cycle()
            else:
                if await self.learning_cycle_lock.locked_async():
                    await self.learning_cycle_lock.release_async()
        finally:
            if await self.learning_cycle_lock.locked_async():
                await self.learning_cycle_lock.release_async()
```

If the node is the start node it will call `self.cm.propagator.propagate("initialization")` where it sends the model parameters
to all eligible neighbors:

```
round_number = -1 if strategy_id == "initialization" else self.get_round()

        for neighbor_addr in eligible_neighbors:
            asyncio.create_task(
                self.cm.send_model(neighbor_addr, round_number, serialized_model, weight)
            )
```

The communications manager calls the `MessageManager` to `generate_model_message` and then sends the model 
to the node with the given address:

```
async def send_model(self, dest_addr, round, serialized_model, weight=1):
    #...
    
    logging.info(f"Sending model to {dest_addr} with round {round}: weight={weight} | size={sys.getsizeof(serialized_model) / (1024 ** 2) if serialized_model is not None else 0} MB")
    message = self.mm.generate_model_message(round, serialized_model, weight)
    await conn.send(data=message, is_compressed=True)
    
    #...
```

When the node receives the message `handle_incoming_message` will be triggered (in connection.py) which will add 
the message to the pending_messages_queue:

```
if is_last_chunk:
    await self._process_complete_message(message_id)
```

```
 async def _process_complete_message(self, message_id: bytes) -> None:
        
        #rest of implementation...

        await self.pending_messages_queue.put((data_type_prefix, memoryview(message_content)))
```

`process_message_queue` which is always running in the background will process the newly added message, trigger 
`_handle_message` which in turn will trigger `handle_incoming_message` in the CommunicationsManager:

```
 async def process_message_queue(self) -> None:
        while True:
            try:
                if self.pending_messages_queue is None:
                    logging.error("Pending messages queue is not initialized")
                    return
                data_type_prefix, message = await self.pending_messages_queue.get()
                await self._handle_message(data_type_prefix, message)
                self.pending_messages_queue.task_done()
            except Exception as e:
                logging.error(f"Error processing message queue: {e}")
            finally:
                await asyncio.sleep(0)
```

```
async def _handle_message(self, data_type_prefix: bytes, message: bytes) -> None:
    if data_type_prefix == self.DATA_TYPE_PREFIXES["pb"]:
        # logging.debug("Received a protobuf message")
        asyncio.create_task(self.cm.handle_incoming_message(message, self.addr), name=f"Connection {self.addr} message handler")
        
    #remaining implementation...
```

The `CommunicationsManager` of the receiving nodes will forward the received parameters by calling 
`self.forwarder.forward(data, addr_from=addr_from)` since currently it's the initialization round (indicated by -1).
Later only proxy nodes will forward parameters. 

Afterwards the node calls  `self.handle_model_message(source, message_wrapper.model_message)`:

```
async def handle_incoming_message(self, data, addr_from):
elif message_wrapper.HasField("model_message"):
if await self.include_received_message_hash(hashlib.md5(data).hexdigest()):
    if self.config.participant["device_args"]["proxy"] or message_wrapper.model_message.round == -1:
        await self.forwarder.forward(data, addr_from=addr_from)
    await self.handle_model_message(source, message_wrapper.model_message)
```

In `handle_model_message`: since `current_round` is 0 and `message.round` is -1 the parameters get deserialized and 
and the learning cycle is enabled by releasing the `get_federation_ready_lock` which has been in `_start_learning`:

```
try:
    model = self.engine.trainer.deserialize_model(message.parameters)
    self.engine.trainer.set_model_parameters(model, initialize=True)
    logging.info(f"🤖  handle_model_message | Model Parameters Initialized")
    self.engine.set_initialization_status(True)
    await self.engine.get_federation_ready_lock().release_async()  # Enable learning cycle once the initialization is done
    try:
        await self.engine.get_federation_ready_lock().release_async()  # Release the lock acquired at the beginning of the engine
    except RuntimeError:
        pass
except RuntimeError:
    pass
```

E.g. if the trainer is lightning:

```
def deserialize_model(self, data):
    # From https://pytorch.org/docs/stable/notes/serialization.html
    try:
        buffer = io.BytesIO(data)
        with gzip.GzipFile(fileobj=buffer, mode="rb") as f:
            params_dict = torch.load(f)
        buffer.close()
        del buffer
        return OrderedDict(params_dict)
    except Exception as e:
        raise ParameterDeserializeError("Error decoding parameters") from e
```

Afterwards `_learning_cycle is called` and round 0 of the federated learning process starts.

**Round 0**

`learning_cycle` calls `update_federation_nodes` the pending models to aggregate
and to acquire the `_aggregation_done_lock`. Then `_extended_learning_cycle` is called 


Depending on the node being a malicious node, an aggregator node, a server node, trainer node or an idle node 
the `_extended_learning_cycle` method differs.


```
class AggregatorNode(Engine):
    def __init__(self, model, dataset, config=Config, trainer=Lightning, security=False, model_poisoning=False, poisoned_ratio=0, noise_type="gaussian"):
        super().__init__(model, dataset, config, trainer, security, model_poisoning, poisoned_ratio, noise_type)

    async def _extended_learning_cycle(self):
        # Define the functionality of the aggregator node
        await self.trainer.test()
        await self.trainer.train()

        await self.aggregator.include_model_in_buffer(self.trainer.get_model_parameters(), self.trainer.get_model_weight(), source=self.addr, round=self.round)

        await self.cm.propagator.propagate("stable")
        await self._waiting_model_updates()
```

An Aggregator Node first tests and then trains the initial model through the pytorch lightning trainer asynchronously.
Simultaneously, the node listens for messages. If the node receives a model from another node `handle_model_message`
will be called where it deserializes the model and then calls `include_model_in_buffer`:

``` 
async def handle_model_message(self, source, message):
    #...
        try:
            # get_federation_ready_lock() is locked when the model is being initialized (first round)
            # non-starting nodes receive the initialized model from the starting node
            if not self.engine.get_federation_ready_lock().locked() or self.engine.get_initialization_status():
                decoded_model = self.engine.trainer.deserialize_model(message.parameters)
                #...
                await self.engine.aggregator.include_model_in_buffer(
                    decoded_model,
                    message.weight,
                    source=source,
                    round=message.round,
                )

```

Afterwards, it calls `self.aggregator.include_model_in_buffer` where the received model is added to the pending models 
to aggregate. 

``` 
#source is the source address
async def include_model_in_buffer(self, model, weight, source=None, round=None, local=False):
    await self._add_model_lock.acquire_async()
    #...
    await self._add_pending_model(model, weight, source)
    
     if len(self.get_nodes_pending_models_to_aggregate()) >= len(self._federation_nodes):
            logging.info(f"🔄  include_model_in_buffer | Broadcasting MODELS_INCLUDED for round {self.engine.get_round()}")
            message = self.cm.mm.generate_federation_message(nebula_pb2.FederationMessage.Action.FEDERATION_MODELS_INCLUDED, [self.engine.get_round()])
            await self.cm.send_message_to_neighbors(message)

     return
```

```    
async def _add_pending_model(self, model, weight, source):
        #...
        elif source not in self.get_nodes_pending_models_to_aggregate():
            logging.info(f"🔄  _add_pending_model | Node is not in the aggregation buffer --> Include model in the aggregation buffer.")
            self._pending_models_to_aggregate.update({source: (model, weight)})
        
        #...
        
        if len(self.get_nodes_pending_models_to_aggregate()) >= len(self._federation_nodes):
            logging.info(f"🔄  _add_pending_model | All models were added in the aggregation buffer. Run aggregation...")
            await self._aggregation_done_lock.release_async()
        await self._add_model_lock.release_async()
        return self.get_nodes_pending_models_to_aggregate()```
``` 

At some point in time the training of the local model will be finished and the node will also include the newly trained
model in the buffer:

    async def _extended_learning_cycle(self):
        await self.trainer.test()
        await self.trainer.train()

        await self.aggregator.include_model_in_buffer(self.trainer.get_model_parameters(), self.trainer.get_model_weight(), source=self.addr, round=self.round)
        
        await self.cm.propagator.propagate("stable")
        await self._waiting_model_updates()


If all the models, the node was waiting for, were added to the aggregation buffer the `_aggregation_done_lock` and 
`_add_model_lock` is released and the node then sends a `FEDERATION_MODELS_INCLUDED` message
to all its neighbors (Broadcasting MODELS_INCLUDED for round 0). 


Then the node propagates the locally trained model with strategy `stable` to all eligible_neighbors with 
`self.cm.propagator.propagate("stable")`. 

Finally, the node calls `_waiting_model_updates` where the models in the buffer get aggregated by an aggregation like
`fedavg`. After the aggregation is done the node is updated with the resulting parameters:

``` 
async def _waiting_model_updates(self):
    params = await self.aggregator.get_aggregation()
    if params is not None:
        self.trainer.set_model_parameters(params)
    #...
```

The `get_aggregation` method calls `run_aggregation` for the defined aggregation algorithm e.g. FEDAVG:

``` 
async def get_aggregation(self):
    #...
       
    aggregated_result = self.run_aggregation(self._pending_models_to_aggregate)
    self._pending_models_to_aggregate.clear()
    return aggregated_result
```

```
class FedAvg(Aggregator):
    #...
    
    def run_aggregation(self, models):
        super().run_aggregation(models)

        models = list(models.values())

        total_samples = float(sum(weight for _, weight in models))

        if total_samples == 0:
            raise ValueError("Total number of samples must be greater than zero.")

        last_model_params = models[-1][0]
        accum = {layer: torch.zeros_like(param, dtype=torch.float32) for layer, param in last_model_params.items()}
        
        with torch.no_grad():
            for model_parameters, weight in models:
                normalized_weight = weight / total_samples
                for layer in accum:
                    accum[layer].add_(model_parameters[layer].to(accum[layer].dtype), alpha=normalized_weight)
                    
        del models
        gc.collect()

        # self.print_model_size(accum)
        return accum
```


To conclude round 0, the initialization round, `on_round_end` in e.g. lightning.py is called to clean up the trainer
and data and to increase the round:


``` 
await self.get_round_lock().acquire_async()
print_msg_box(msg=f"Round {self.round} of {self.total_rounds} finished.", indent=2, title="Round information")
await self.aggregator.reset()
self.trainer.on_round_end()
self.round = self.round + 1
self.config.participant["federation_args"]["round"] = self.round  # Set current round in config (send to the controller)
await self.get_round_lock().release_async()
```


``` 
def on_round_end(self):
    self._logger.global_step = self._logger.global_step + self._logger.local_step
    self._logger.local_step = 0
    self.round += 1
    self.model.on_round_end()
    logging.info("Flushing memory cache at the end of round...")
    self.cleanup()
```

``` 
def cleanup(self):
    if self._trainer is not None:
        self._trainer._teardown()
        del self._trainer
    if self.data is not None:
        self.data.teardown()
    gc.collect()
    torch.cuda.empty_cache()
```

With this the initialization round is finished and the federation process can continue into the next round. Meaning the 
while loop in `learning_cycle` will continue with its next iteration.

The next round will be similar to round 0, but instead of training the initial model, the node will now train the aggregated
model.