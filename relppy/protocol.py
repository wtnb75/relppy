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
                _log.warning("message length mismatch: %s", bin)
            if data[3][datalen] != ord(b"\n"):
                _log.warning("invalid message tail? %s", str(data[3][datalen]))
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
            i0 = buf.find(b" ")
            if i0 == -1:
                _log.debug("short txnr: %s", buf)
                break
            txnr = int(buf[:i0])
            i1 = buf.find(b" ", i0+1)
            if i1 == -1:
                _log.debug("short command: %s", buf)
                break
            command = buf[i0+1:i1]
            if buf[i1+1] == b"0":
                # no data
                if len(buf) < i1 + 1 + 1:
                    _log.debug("short nf: %s", buf)
                    break
                assert buf[i1+2] == b"\n"
                msg = Message(txnr, command, b"")
                _log.debug("got: %s", msg)
                yield msg
                if auto_ack:
                    _log.debug("send ack: %s", msg.txnr)
                    msg.sendAck(ifp)
                buf = buf[i1+1+1:]
            else:
                i2 = buf.find(b" ", i1+1)
                if i2 == -1:
                    _log.debug("short datalen: %s", buf)
                    break
                datalen = int(buf[i1+1:i2])
                if len(buf) < i2 + 1 + datalen + 1:
                    _log.debug("short data+nf: %s", buf)
                    break
                data = buf[i2+1:i2+1+datalen]
                _log.debug("data: %s", data)
                assert buf[i2+1+datalen] == ord(b"\n")
                msg = Message(txnr, command, data)
                _log.debug("got: %s", msg)
                yield msg
                if auto_ack:
                    _log.debug("send ack: %s", msg.txnr)
                    msg.sendAck(ifp)
                buf = buf[i2+1+datalen+1+1:]
            _log.debug("rest: len=%s", len(buf))
