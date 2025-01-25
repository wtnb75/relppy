import socket
from logging import getLogger
from dataclasses import dataclass
from .version import VERSION

_log = getLogger(__name__)
BUFSIZE = 4096

relp_version = 0
relp_ua = f"relppy,{VERSION},https://github.com/wtnb75/relppy"


@dataclass
class Message:
    txnr: int = 0
    command: bytes = b""
    data: bytes = b""

    def pack(self) -> bytes:
        if len(self.data) == 0:
            return b" ".join([
                str(self.txnr).encode("ascii"),
                self.command, b"0\n"])

        return b" ".join([
            str(self.txnr).encode("ascii"),
            self.command,
            str(len(self.data)).encode("ascii"),
            self.data
        ])+b"\n"

    def unpack(self, bin: bytes) -> int:
        data = bin.split(b" ", 3)
        if len(data) <= 2:
            _log.warning("data length = 2: %s", data)
            return 0
        elif len(data) == 3 or data[2].startswith(b"0\n"):
            self.txnr = int(data[0])
            self.command = data[1]
            self.data = b""
            return len(bin)-len(data[2])+2
        elif len(data) == 4:
            self.txnr = int(data[0])
            self.command = data[1]
            datalen = int(data[2])
            self.data = data[3][:datalen]
            if len(self.data) != datalen:
                raise ValueError(f"message length mismatch: {bin}")
            if data[3][datalen] != ord(b"\n"):
                raise ValueError(f"invalid message tail: {datalen} of {data[3]}")
            return len(bin)-len(data[3])+datalen+1

    def send(self, sock: socket.socket):
        _log.debug("send %s", self)
        sock.sendall(self.pack())

    def sendAck(self, sock: socket.socket):
        _log.debug("send ack %s", self.txnr)
        Message(self.txnr, b"rsp", b"200 OK").send(sock)

    def recv(self, sock: socket.socket):
        buf0 = sock.recv(BUFSIZE)
        if len(buf0) == 0:
            _log.info("closed")
            self.txnr = 0
            self.command = b""
            self.data = b""
            return b""
        sz = self.unpack(buf0)
        if sz != len(buf0):
            _log.warning("message size mismatch: parsed=%s, recv=%s", sz, len(buf0))
        return buf0[sz:]

    def __str__(self):
        cmd = self.command.decode("utf-8", errors="backslashreplace")
        dat = self.data.decode("utf-8", errors="backslashreplace")
        return f"txnr={self.txnr} command={repr(cmd)} data={repr(dat)}"


def process_io(ifp: socket.socket, auto_ack: bool):
    buf = b""
    while True:
        buf0 = ifp.recv(BUFSIZE)
        if len(buf0) == 0:
            # closed?
            _log.debug("closed: rest=%s, read=%s", len(buf), len(buf0))
            ifp.close()
            return buf
        buf += buf0
        # message
        while buf:
            l0 = buf.split(b" ", 2)
            if len(l0) != 3:
                _log.debug("short: %s", buf)
                break
            txnr = int(l0[0])
            command = l0[1]
            if l0[2].startswith(b"0\n"):
                # no data
                msg = Message(txnr, command, b"")
                _log.debug("got: %s", msg)
                yield msg
                if auto_ack:
                    _log.debug("send ack: %s", msg.txnr)
                    msg.sendAck(ifp)
                buf = l0[2][2:]
            else:
                l1 = l0[2].split(b" ", 1)
                if len(l1) != 2:
                    break
                datalen = int(l1[0])
                if len(l1[1]) < datalen:
                    _log.debug("short data: %s", buf)
                    break
                data = l1[1][:datalen]
                _log.debug("data: %s", data)
                assert l1[1][datalen] == ord(b"\n")
                msg = Message(txnr, command, data)
                _log.debug("got: %s", msg)
                yield msg
                if auto_ack:
                    _log.debug("send ack: %s", msg.txnr)
                    msg.sendAck(ifp)
                buf = l1[1][datalen+1:]
            _log.debug("rest: len=%s", len(buf))
