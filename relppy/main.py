import click
import functools
import socket
import socketserver
import ssl
import codecs
from typing import Type
from logging import getLogger
from .server import RelpStreamHandler
from .client import RelpTCPClient, RelpUnixClient, RelpTlsClient
from .protocol import process_io, Message, relp_ua
from .version import VERSION

_log = getLogger(__name__)
relp_offer = f"\nrelp_version=1\nrelp_software={relp_ua}\ncommands=syslog,eventlog"

errors_list = [x.removesuffix("_errors") for x in dir(codecs) if x.endswith("_errors")]


@click.group(invoke_without_command=True)
@click.version_option(VERSION)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


def verbose_option(func):
    @click.option("--verbose/--quiet", default=None)
    @functools.wraps(func)
    def _(verbose: bool | None, **kwargs):
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


def hostport_option(func):
    @click.option("--port", type=int, default=10514, show_default=True)
    @click.option("--host", default="localhost", show_default=True)
    @functools.wraps(func)
    def _(host: str, port: int, **kwargs):
        return func(address=(host, port), **kwargs)
    return _


def encoding_option(func):
    @click.option("--encoding", default="utf-8", show_default=True)
    @click.option("--errors", type=click.Choice(errors_list), default="replace", show_default=True)
    @functools.wraps(func)
    def _(encoding: str, errors: str, **kwargs):
        syslog = getLogger("syslog")

        class MyHandler(RelpStreamHandler):
            def do_syslog(self, msg: Message) -> str:
                syslog.info(msg.data.decode(encoding, errors))
                return ""

        return func(encoding=encoding, errors=errors, handler=MyHandler, **kwargs)
    return _


def tlsserver_option(func):
    @click.option("--cert", type=click.Path(exists=True, file_okay=True, dir_okay=False), required=True)
    @click.option("--key", type=click.Path(exists=True, file_okay=True, dir_okay=False), required=True)
    @functools.wraps(func)
    def _(cert: str, key: str, **kwargs):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(cert, key)
        return func(context=context, **kwargs)
    return _


def tlsclient_option(func):
    @click.option("--verify/--no-verify", default=True, show_default=True)
    @click.option("--cafile", type=click.Path(exists=True, file_okay=True, dir_okay=False))
    @functools.wraps(func)
    def _(verify, cafile, **kwargs):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=cafile)
        if not verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return func(context=context, **kwargs)
    return _


@cli.command()
@verbose_option
@hostport_option
def raw_server(address: tuple[str, int]):
    """RELP server (raw generator style)"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    sock.bind(address)
    sock.listen(1024)
    _log.info("listen on %s", sock.getsockname())
    while True:
        client, addr = sock.accept()
        _log.info("connected: %s", addr)
        for msg in process_io(client, auto_ack=True):
            _log.info("received: %s", msg)
            if msg.command == b"close":
                Message(0, b"serverclose").send(client)
                client.close()
                break


@cli.command()
@verbose_option
@hostport_option
@encoding_option
@click.argument("message")
def raw_client(address: tuple[str, int], message: str, encoding: str, errors: str, **kwargs):
    """RELP client (raw send/recv)"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    sock.connect(address)
    Message(1, b"open", relp_offer.encode(encoding, errors)).send(sock)
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
@hostport_option
@encoding_option
def server(address: tuple[str, int], handler: Type[RelpStreamHandler], **kwargs):
    """RELP server (TCP)"""
    class _T(socketserver.TCPServer, socketserver.ThreadingMixIn):
        allow_reuse_address = True

        def verify_request(self, request, client_address):
            _log.info("connect from: %s", client_address)
            return True

    srv = _T(address, handler)
    srv.serve_forever()


@cli.command()
@verbose_option
@click.option("--sock", type=click.Path(), required=True)
@encoding_option
def server_unix(sock: str, handler: Type[RelpStreamHandler], **kwargs):
    """RELP server (unix socket)"""
    class _T(socketserver.UnixStreamServer, socketserver.ThreadingMixIn):
        allow_reuse_address = True

    srv = _T(sock, handler)
    srv.serve_forever()


@cli.command()
@verbose_option
@hostport_option
@tlsserver_option
@encoding_option
def server_tls(address: tuple[str, int], context: ssl.SSLContext, handler: Type[RelpStreamHandler], **kwargs):
    """RELP server (TLS)"""
    class _T(socketserver.TCPServer, socketserver.ThreadingMixIn):
        allow_reuse_address = True

        def verify_request(self, request, client_address):
            _log.info("connect from: %s", client_address)
            _log.debug("ssl: version=%s, cipher=%s", request.version(), request.cipher())
            return True

    srv = _T(address, handler, bind_and_activate=False)
    srv.socket = context.wrap_socket(srv.socket, server_side=True)
    srv.server_bind()
    srv.server_activate()
    srv.serve_forever()


@cli.command()
@verbose_option
@hostport_option
@encoding_option
@click.argument("message", nargs=-1)
def client(address: tuple[str, int], message: tuple[str], encoding: str, errors: str, **kwargs):
    """RELP client (TCP)"""
    with RelpTCPClient(address=address) as cl:
        for m in message:
            res = cl.send_command(b"syslog", m.encode(encoding, errors)).result()
            _log.info("sent: %s -> %s", m, res)
        _log.debug("finalize %s", cl)
    _log.debug("finished %s", cl)


@cli.command()
@verbose_option
@click.option("--sock", type=click.Path(), required=True)
@encoding_option
@click.argument("message", nargs=-1)
def client_unix(sock: str, message: tuple[str], encoding: str, errors: str, **kwargs):
    """RELP client (unix socket)"""
    with RelpUnixClient(address=sock) as cl:
        for m in message:
            res = cl.send_command(b"syslog", m.encode(encoding, errors)).result()
            _log.info("sent: %s -> %s", m, res)
        _log.debug("finalize %s", cl)
    _log.debug("finished %s", cl)


@cli.command()
@verbose_option
@hostport_option
@tlsclient_option
@encoding_option
@click.argument("message", nargs=-1)
def client_tls(address: tuple[str, int], message: tuple[str], encoding: str, errors: str,
               context: ssl.SSLContext, **kwargs):
    """RELP client (TLS)"""
    with RelpTlsClient(address=address, context=context, server_hostname=address[0]) as cl:
        for m in message:
            res = cl.send_command(b"syslog", m.encode(encoding, errors)).result()
            _log.info("sent: %s -> %s", m, res)
        _log.debug("finalize %s", cl)
    _log.debug("finished %s", cl)


if __name__ == "__main__":
    cli()
