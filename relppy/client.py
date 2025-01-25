import socket
from concurrent.futures import ThreadPoolExecutor, Future
import threading
from .protocol import Message, relp_ua
from logging import getLogger

_log = getLogger(__name__)


class RelpTCPClient:
    def __init__(self, address: tuple[str, int | None], **kwargs):
        self.address = address
        self.kwargs = kwargs
        self.resendbuf: dict[int, tuple[Message, Future]] = {}
        self.resend_bufsize = kwargs.get("resend_size", 1024)
        self.rbufsize = kwargs.get("rbufsize", 1024*1024)
        self.wbufsize = kwargs.get("wbufsize", 1024*1024)
        self.cur_txnr = 1
        self.sock = socket.create_connection(address, **kwargs)
        self.wfile = self.sock.makefile("wb", self.wbufsize)
        self.rfile = self.sock.makefile("rb", self.rbufsize)
        _log.debug("connected: %s", self)
        self.executor = ThreadPoolExecutor(1, "acker")
        self.executor.submit(self.acker)
        offer = f"\nrelp_version=1\nrelp_software={relp_ua}\ncommands=syslog"
        res: bytes = self.send_command(b"open", offer.encode("ascii")).result()
        self.negodata: dict[str, list[str]] = {}
        for i in res.splitlines()[1:]:
            ll = i.split(b"=", 1)
            if len(ll) == 1:
                self.negodata[ll[0].decode()] = []
            else:
                self.negodata[ll[0].decode()] = ll[1].decode().split(",")
        _log.debug("negotiated: %s", self.negodata)
        self.lock = threading.Lock()

    def close(self):
        if hasattr(self, "sock"):
            _log.debug("closing %s", self)
            resendbuf = self.resendbuf
            self.resendbuf = {}
            _log.debug("resendbuf: %s", len(resendbuf))
            for msgft in resendbuf.values():
                _log.info("cancel msg: %s", msgft[0])
                msgft[1].cancel()
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
        self.executor.shutdown(wait=True)

    def resend(self, txnr: int | None = None):
        if txnr:
            msg, ft = self.resendbuf[txnr]
            assert not ft.done()
            _log.info("resend %s", msg)
            self.wfile.write(msg.pack())
            self.wfile.flush()
        else:
            for msg, ft in self.resendbuf.values():
                if not ft.done():
                    _log.info("resend %s", msg)
                    self.wfile.write(msg.pack())
                    self.wfile.flush()
                else:
                    _log.info("skip resend %s", msg)

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
            _, f = self.resendbuf.pop(txnr)
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
                    data += self.rfile.read(datalen-len(data)+1)
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
        _log.warning("connection closed")

    def send_command(self, command: bytes, data: bytes) -> Future:
        _log.debug("send %s msglen=%s (%s)", command, len(data), data)
        if len(self.resendbuf) > self.resend_bufsize:
            _log.info("buffer full: bufsize=%s", len(self.resendbuf))
        msg = Message(self.cur_txnr, command, data)
        self.cur_txnr += 1
        f = Future()
        self.resendbuf[msg.txnr] = [msg, f]
        self.wfile.write(msg.pack())
        self.wfile.flush()
        _log.debug("message sent: %s", msg.txnr)
        return f
