import zmq
import json

ZMQ_PORT = 51607

class ZmqClient:
    """ZMQ Client for RigBuilder MCP"""
    def __init__(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        # Timeout for socket if server is offline
        self.socket.setsockopt(zmq.RCVTIMEO, 1000)
        self.socket.connect(f"tcp://127.0.0.1:{ZMQ_PORT}")

    def send_request(self, action: str, **kwargs) -> dict:
        req = {"action": action}
        req.update(kwargs)
        
        try:
            self.socket.send_string(json.dumps(req))
            resp = self.socket.recv_string()
            data = json.loads(resp)
            if data.get("status") == "error":
                raise Exception(f"RigBuilder Error: {data.get('message')}")
            return data.get("data")
            
        except zmq.Again:
            # Recreate socket to clear REQ state machine
            self.socket.close()
            self.socket = self.context.socket(zmq.REQ)
            self.socket.setsockopt(zmq.RCVTIMEO, 1000)
            self.socket.connect(f"tcp://127.0.0.1:{ZMQ_PORT}")
            raise Exception("Rig Builder is offline or not responding. Please ensure Rig Builder is running.")
