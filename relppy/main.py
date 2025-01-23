import click
import functools
import socket
import socketserver
from logging import getLogger
from .server import RelpTCPHandler
from .protocol import process_io, Message, nogotiation_msg
from .version import VERSION

_log = getLogger(__name__)


@click.group(invoke_without_command=True)
@click.version_option(VERSION)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


def verbose_option(func):
    @click.option("--verbose/--quiet", default=None)
    @functools.wraps(func)
    def _(verbose, **kwargs):
        from logging import basicConfig
        fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
        if verbose is None:
            basicConfig(level="INFO", format=fmt)
        elif verbose is False:
            basicConfig(level="WARNING", format=fmt)
        else:
            basicConfig(level="DEBUG", format=fmt)
        return func(**kwargs)
    return _


@cli.command()
@verbose_option
@click.option("--port", type=int, default=10514)
@click.option("--host", default="localhost")
def raw_server(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    sock.bind((host, port))
    sock.listen(1024)
    _log.info("listen on %s", sock.getsockname())
    while True:
        client, addr = sock.accept()
        _log.info("connected: %s", addr)
        for msg in process_io(client, auto_ack=True):
            _log.info("received: %s", msg)


@cli.command()
@verbose_option
@click.option("--port", type=int, default=10514)
@click.option("--host", default="localhost")
@click.option("--encoding", default="utf-8")
@click.option("--errors", default="replace")
@click.argument("message")
def raw_client(host, port, message, encoding, errors):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    sock.connect((host, port))
    Message(1, b"open", nogotiation_msg).send(sock)
    recv = Message()
    recv.recv(sock)
    _log.info("receive: %s", recv)
    Message(2, b"syslog", message.encode(encoding, errors)).send(sock)
    recv.recv(sock)
    _log.info("receive %s", recv)
    Message(3, b"close").send(sock)
    rest = recv.recv(sock)
    _log.info("receive %s, rest=%s", recv, rest)
    rest = recv.recv(sock)
    _log.info("receive %s, rest=%s", recv, rest)
    sock.close()


@cli.command()
@verbose_option
@click.option("--port", type=int, default=10514)
@click.option("--host", default="localhost")
def server(host, port):
    class MyHandler(RelpTCPHandler):
        def do_syslog(self, msg: Message) -> str:
            _log.warning("msg=%s", msg.data.decode("utf-8"))
            return ""

    class _T(socketserver.TCPServer, socketserver.ThreadingMixIn):
        allow_reuse_address = True

    srv = _T((host, port), MyHandler)
    srv.serve_forever()


@cli.command()
@verbose_option
@click.option("--port", type=int, default=10514)
@click.option("--host", default="localhost")
@click.option("--encoding", default="utf-8")
@click.option("--errors", default="replace")
@click.argument("message", nargs=-1)
def logger(host, port, message, encoding, errors):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    sock.connect((host, port))
    Message(1, b"open", nogotiation_msg).send(sock)
    recv = Message()
    recv.recv(sock)
    _log.info("receive: %s", recv)
    Message(2, b"syslog", message.encode(encoding, errors)).send(sock)
    recv.recv(sock)
    _log.info("receive %s", recv)
    Message(3, b"close").send(sock)
    rest = recv.recv(sock)
    _log.info("receive %s, rest=%s", recv, rest)
    rest = recv.recv(sock)
    _log.info("receive %s, rest=%s", recv, rest)
    sock.close()


if __name__ == "__main__":
    cli()
