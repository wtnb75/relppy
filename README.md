# RELP server

## install

- pip install relppy

## example

### server

```python
import socketserver
from relppy.server import RelpTCPHandler
from relppy.protocol import Message


class MyHandler(RelpTCPHandler):
    def do_syslog(self, msg: Message):
        print(msg.data.decode("ascii"))


if __name__ == "__main__":
    srv = socketserver.TCPServer(("localhost", 10514), MyHandler)
    srv.serve_forever()
```

### client

```python
from relppy.client import RelpTCPClient

with RelpTCPClient(("localhost", 10514)) as cl:
    for m in ["hello", "world"]:
        fut= cl.send_command(b"syslog", m.encode())
        res = fut.result()
        print(f"sent: {m} -> {res}")
```
