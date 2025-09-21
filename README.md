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

## log handler

relppy comes with a logging handler that can be used with [python logging](https://docs.python.org/3/library/logging.html).
The handler has four special arguments.

### spool_method=\<function>
You can specify a spool method. This method is called with the log record instance as argument if the record could not be
sent (e.g. relp log server down) to spool it for later resend. Writing the spool/resend methods is up to the developer.

### exception_on_emit=\<bool>
If exception_on_emit is True, the emit() method of the log handler raises an exception if the log message could
not be sent. This results in an exception (e.g. Connection refused) when calling the logger (e.g. logger.info). This
behavior is intended to be used in the resend method (see spool_method above) to ensure all spooled
messages are delivered to the relp log server.

### logger=\<logging.Logger>
The logger instance that is used to log connection failures.

### active_log_handlers=\<List>
A list that the log handler is added to on __init__ and removed from on close().
This is useful in multiprocessing programs/daemons to close all open
loggers on exit.

### Examples

```python
import logging
from relppy.log_handler import RelpHandler

log_handler = RelpHandler(address="server:port", facility="LOCAL7")

formatter = logging.Formatter('%(name)s: [%(levelname)s] %(message)s')
log_handler.setFormatter(formatter)
logger = logging.getLogger("my_logger")
logger.addHandler(log_handler)
```

Passing a SSL context enables TLS.

```python
import ssl
import logging
from relppy.log_handler import RelpHandler

context = ssl.create_default_context(
    purpose=ssl.Purpose.SERVER_AUTH,
    cafile="/path/to/ca.cert",
)
context.load_cert_chain(certfile="/path/to/client-cert.pem",
                        keyfile="/path/to/client-key.pem")

log_handler = RelpHandler(address="server:port",
                        facility="LOCAL7",
                        context=context)

formatter = logging.Formatter('%(name)s: [%(levelname)s] %(message)s')
log_handler.setFormatter(formatter)

logger = logging.getLogger("my_logger")
logger.addHandler(log_handler)
```

## CLI command

relppy comes with a CLI command to send messages to a relp server [rsyslog example](https://github.com/the2nd/relppy/blob/main/rsyslog/rsyslog-ssl.conf).

```bash
relppy logger --logger-name audit-log --host servername --port port --log-level INFO --priority info --facility LOCAL7 "Test message"
```

```bash
relppy logger-tls --logger-name audit-log --host servername --port port --cafile /path/to/syslog-ca.pem --certfile /path/to/syslog-cert.pem --keyfile /path/to/syslog-key.pem --log-level INFO --priority info --facility LOCAL7 "Test message via TLS"
```
