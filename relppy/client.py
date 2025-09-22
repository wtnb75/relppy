import socket
from concurrent.futures import ThreadPoolExecutor, Future, wait as futures_wait
import threading
import time
import queue
import ssl
from .protocol import Message, relp_ua
from logging import getLogger

_log = getLogger(__name__)


class RelpTCPClient:
    MAX_TXNR = 999999999

    def __init__(
        self,
        address: tuple[str, int | None],
        resend_size: int = 1024,
        resend_wait: float = 1.0,
        resend_interval: int = 5,
        rbufsize: int = 1024 * 1024,
        wbufsize: int = 1024 * 1024,
        **kwargs,
    ):
        self.lock = threading.Lock()
        self.address = address
        self.kwargs = kwargs
        self.connected = False

        self.cur_txnr = 1
        self.resend_bufsize = resend_size
        self.resend_wait = resend_wait
        self.resend_interval = resend_interval
        self.last_resend = 0
        self.rbufsize = rbufsize
        self.wbufsize = wbufsize
        self.resendbuf: dict[int, tuple[float, Message, Future]] = {}

        self.sock = self.create_connection(address, **kwargs)
        self.wfile = self.sock.makefile("wb", self.wbufsize)
        self.rfile = self.sock.makefile("rb", self.rbufsize)
        _log.debug("connected: %s", self)

        self.send_q = queue.Queue()
        self.recv_q = queue.Queue()

        self.ack_executor = ThreadPoolExecutor(1, "acker")
        self.ack_executor.submit(self.acker)
        self.send_executor = ThreadPoolExecutor(1, "sender")
        self.send_executor.submit(self.sender)
        try:
            self.relp_nego()
        except Exception as e:
            _log.warning("Failed to negotiate connection: %s" % e)
            self.close()
            raise

    def relp_nego(self):
        offer = f"\nrelp_version=1\nrelp_software={relp_ua}\ncommands=syslog"
        res: bytes = self.send_command(b"open", offer.encode("ascii"), skip_buffer=True).result()
        self.negodata: dict[str, list[str]] = {}
        for i in res.splitlines()[1:]:
            ll = i.split(b"=", 1)
            if len(ll) == 1:
                self.negodata[ll[0].decode()] = []
            else:
                self.negodata[ll[0].decode()] = ll[1].decode().split(",")
        _log.debug("negotiated: %s", self.negodata)

    def create_connection(self, address, **kwargs):
        sock = socket.create_connection(address, **kwargs)
        self.connected = True
        return sock

    def close(self, timeout=1):
        if hasattr(self, "sock"):
            _log.debug("closing %s", self)
            if timeout > 0:
                _log.debug("waiting for timeout %s", timeout)
                futures_wait([x[2] for x in self.resendbuf.values()], timeout)
            resendbuf = self.resendbuf
            self.resendbuf = {}
            _log.debug("resendbuf: %s", len(resendbuf))
            for stmsgft in resendbuf.values():
                _log.info("cancel msg: %s", stmsgft[1])
                stmsgft[2].cancel()
            if self.connected:
                _log.debug("sending close: %s", self)
                res = self.send_command(b"close", b"").result()
                _log.debug("close result: %s", res)
        with self.lock:
            if hasattr(self, "sock"):
                self.rfile.close()
                self.wfile.close()
                self.sock.close()
                del self.sock
                _log.debug("socket closed")
        self.send_q.put("close")
        self.ack_executor.shutdown(wait=True)
        self.send_executor.shutdown(wait=True)

    def resend(self, txnr: int | None = None, new_conn: bool = False):
        if txnr:
            sent_time, msg, ft = self.resendbuf[txnr]
            assert not ft.done()
            _log.info("resend %s", msg)
            self.wfile.write(msg.pack())
            self.wfile.flush()
        else:
            cnt = 0
            for sent_time, msg, ft in self.resendbuf.values():
                if (time.time() - sent_time) < self.resend_interval:
                    continue
                if not ft.done():
                    if new_conn:
                        msg.txnr = self.cur_txnr
                        self.cur_txnr += 1
                    _log.info("resend %s", msg)
                    self.wfile.write(msg.pack())
                    cnt += 1
                else:
                    _log.info("skip resend %s", msg)
            if cnt != 0:
                _log.info("resend %d messages", cnt)
                self.wfile.flush()
        self.last_resend = time.time()

    def __enter__(self):
        return self

    def __exit__(self, ex_type, ex_value, trace):
        self.close()

    def __str__(self):
        if hasattr(self, "sock"):
            return "%s(%s <- %s)" % (self.__class__.__name__, self.sock.getpeername(), self.sock.getsockname())
        return "%s(not connected)" % (self.__class__.__name__)

    def _gotack(self, txnr: int, data: bytes):
        try:
            f = self.resendbuf.pop(txnr)[2]
            _log.debug("setting result %s <- %s", txnr, data)
            f.set_result(data)
        except KeyError:
            _log.warning("txnr does not found: %s", txnr)

    def acker(self):
        _log.debug("acker started: %s", self)
        for bin in self.rfile:
            _log.debug("got line: %s", bin)
            token = bin.split(b" ", 3)
            if len(token) < 3:
                _log.warning("invalid message: %s", bin)
                continue
            _log.debug("token: %s", token)
            if len(token) == 3 and token[2] == b"0\n":
                txnr = int(token[0])
                command = token[1]
                datalen = 0
                data = b""
                _log.debug("zero length message: %s", command)
            else:
                txnr = int(token[0])
                command = token[1]
                datalen = int(token[2])
                data = token[3]
                if datalen > len(data):
                    data += self.rfile.read(datalen - len(data) + 1)
                _log.debug("message: %s msglen=%s", command, len(data))
            data = data.removesuffix(b"\n")
            _log.debug("got txnr=%s, command=%s, datalen=%s/%s", txnr, command, datalen, len(data))
            if command == b"rsp":
                _log.debug("ack %d", txnr)
                self._gotack(txnr, data)
            elif command == b"serverclose":
                _log.info("server close: %s", bin)
                if txnr != 0:
                    _log.warning("txnr is not 0: %s", bin)
                with self.lock:
                    if hasattr(self, "sock"):
                        self.rfile.close()
                        self.wfile.close()
                        self.sock.close()
                        del self.sock
                break
            else:
                _log.warning("got not ack: %s (%s)", command, bin)
        self.connected = False
        _log.warning("connection closed")

    def sender(self):
        while True:
            if not self.connected:
                break
            try:
                send_data = self.send_q.get(timeout=1)
            except queue.Empty:
                command = None
            else:
                if send_data == "close":
                    break
                try:
                    command = send_data["command"]
                    data = send_data["data"]
                    skip_buffer = send_data["skip_buffer"]
                    new_conn = send_data["new_conn"]
                except Exception:
                    _log.warning("received wrong send data: %s", send_data)
                    continue
            if not skip_buffer:
                self.try_resend(new_conn)
            self.sender_send(command, data)

    def try_resend(self, new_conn):
        try_resend = False
        if len(self.resendbuf) > self.resend_bufsize:
            _log.warning("buffer full: bufsize=%s", len(self.resendbuf))
            try_resend = True
        if (time.time() - self.last_resend) >= self.resend_interval:
            if len(self.resendbuf) > 0:
                _log.warning("buffer resend interval reached: resend_interval=%s", self.resend_interval)
                try_resend = True
        if try_resend:
            self.resend(new_conn=new_conn)
            _log.info("sleep %f second", self.resend_wait)
            time.sleep(self.resend_wait)

    def sender_send(self, command, data):
        if command:
            _log.debug("send %s msglen=%s (%s)", command, len(data), data)
            try:
                msg = Message(self.cur_txnr, command, data)
                self.cur_txnr += 1
                if self.cur_txnr > self.MAX_TXNR:
                    self.cur_txnr = 1
                f = Future()
                self.resendbuf[msg.txnr] = (time.time(), msg, f)
                self.wfile.write(msg.pack())
                self.wfile.flush()
                _log.debug("message sent: %s", msg.txnr)
                send_status = {"status": True, "future": f}
            except Exception as e:
                send_status = {"status": False, "exception": e}
            self.recv_q.put(send_status)

    def send_command(self, command: bytes, data: bytes, skip_buffer: bool = False) -> Future:
        _log.debug("send %s msglen=%s (%s)", command, len(data), data)
        # Check if we are connected.
        new_conn = False
        if not self.connected:
            self.ack_executor.shutdown(wait=True)
            self.send_executor.shutdown(wait=True)
            with self.lock:
                if hasattr(self, "sock"):
                    self.rfile.close()
                    self.wfile.close()
                    self.sock.close()
                    del self.sock
            self.cur_txnr = 1
            self.sock = self.create_connection(self.address, **self.kwargs)

            self.wfile = self.sock.makefile("wb", self.wbufsize)
            self.rfile = self.sock.makefile("rb", self.rbufsize)

            self.ack_executor = ThreadPoolExecutor(1, "acker")
            self.ack_executor.submit(self.acker)

            self.send_executor = ThreadPoolExecutor(1, "sender")
            self.send_executor.submit(self.sender)

            try:
                self.relp_nego()
            except Exception as e:
                _log.warning("Failed to negotiate connection: %s" % e)
                raise
            new_conn = True
        send_data = {
            "command": command,
            "data": data,
            "new_conn": new_conn,
            "skip_buffer": skip_buffer,
        }
        self.send_q.put(send_data)
        status_data = self.recv_q.get()
        send_status = status_data["status"]
        if send_status is not True:
            exception = status_data["exception"]
            raise exception
        future = status_data["future"]
        return future


class RelpUnixClient(RelpTCPClient):
    def create_connection(self, address, **kwargs):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(address)
        self.connected = True
        return sock


class RelpTlsClient(RelpTCPClient):
    def create_connection(self, address, context: ssl.SSLContext, server_hostname=None, **kwargs):
        sock = socket.create_connection(address, **kwargs)
        sock = context.wrap_socket(sock, server_hostname=server_hostname)
        _log.debug("ssl: version=%s, cipher=%s", sock.version(), sock.cipher())
        self.connected = True
        return sock
