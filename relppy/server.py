import socketserver
from .protocol import Message, relp_ua
from logging import getLogger

_log = getLogger(__name__)


class RelpStreamHandler(socketserver.StreamRequestHandler):
    """
    RELP server
    """
    autoack = True

    def finish(self):
        if not self.wfile.closed:
            _log.debug("send server close")
            self.wfile.write(Message(0, b"serverclose").pack())
        super().finish()

    def _ack(self, txn: int, msg: str, add: str | None = None):
        if txn == 0:
            _log.debug("no ack sent: msg=%s", msg)
            return
        if add:
            msg1 = msg + "\n" + add
        else:
            msg1 = msg
        self.wfile.write(Message(txn, b"rsp", msg1.encode("utf-8")).pack())
        _log.debug("ack(%s) sent: %s", msg, txn)

    def do_any(self, msg: Message) -> str | None:
        raise NotImplementedError(f"do_any {msg}")

    def do_close(self, msg: Message) -> None:
        _log.info("close %s", msg)
        self._ack(msg.txnr, "200 OK", "bye")
        raise EOFError("got close")

    def do_syslog(self, msg: Message) -> str | None:
        _log.info("syslog %s", msg)
        raise NotImplementedError(f"do_syslog {msg}")

    def do_open(self, msg: Message) -> str:
        _log.info("open %s", msg)
        self.client_nego: dict[str, list[str]] = {}
        for i in msg.data.splitlines():
            if b"=" in i:
                k, v = i.split(b"=", 1)
                self.client_nego[k.decode()] = v.decode().split(",")
        _log.info("client negotiation: %s", self.client_nego)
        ignore = {"do_any", "do_open", "do_close"}
        command_set = {x.removeprefix("do_") for x in dir(self) if x.startswith("do_") and x not in ignore}
        client_commands = set(self.client_nego.get("commands", []))
        commands = ",".join(command_set & client_commands)
        return f"relp_version=1\nrelp_software={relp_ua}\ncommands={commands}"

    def handle(self):
        while True:
            try:
                msg = self._readmsg()
                self._execmsg(msg)
            except EOFError:
                _log.info("closed?")
                self.finish()
                break

    def _readmsg(self) -> Message:
        l0 = self.rfile.readline()
        if len(l0) == 0:
            raise EOFError("closed")
        l1 = l0.split(b" ", 3)
        txnr = int(l1[0])
        command = l1[1]
        if l1[2] == b"0\n":
            datalen = 0
            data = b""
        else:
            datalen = int(l1[2])
            data = l1[3]
            if len(data) != datalen+1:
                data += self.rfile.read(datalen-len(data)+1)
            if data[-1] != ord(b"\n"):
                _log.warning("invalid message tail: %s", data)
            else:
                data = data[:-1]
        return Message(txnr, command, data)

    def _execmsg(self, msg: Message):
        _log.debug("all recv: %s", msg)
        fname = f"do_{msg.command.decode('ascii')}"
        try:
            if hasattr(self, fname):
                ackadd = getattr(self, fname)(msg)
            else:
                ackadd = self.do_any(msg)
        except EOFError:
            raise
        except Exception as exc:
            _log.exception("caught error: msg=%s", msg)
            if self.autoack:
                self._ack(msg.txnr, f"500 {exc}")
            raise
        else:
            if self.autoack:
                self._ack(msg.txnr, "200 OK", ackadd)
