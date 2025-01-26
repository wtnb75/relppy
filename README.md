# RELP server/client for python

[![main](https://github.com/wtnb75/relppy/actions/workflows/main.yml/badge.svg)](https://github.com/wtnb75/relppy/actions/workflows/main.yml)

## install

- pip install relppy

## example

### server

```python
import socketserver
from relppy.server import RelpStreamHandler
from relppy.protocol import Message


class MyHandler(RelpStreamHandler):
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
