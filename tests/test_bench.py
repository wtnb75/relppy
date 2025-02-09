import pytest
import socketserver
import threading
import tempfile
import ssl
from pathlib import Path
from logging import getLogger
from relppy.protocol import Message
from relppy.server import RelpStreamHandler
from relppy.client import RelpTCPClient, RelpUnixClient, RelpTlsClient

_log = getLogger(__name__)


class MyHandler(RelpStreamHandler):
    def do_syslog(self, msg: Message) -> str:
        return ""


@pytest.fixture()
def unix_server():
    class _T(socketserver.UnixStreamServer, socketserver.ThreadingMixIn):
        allow_reuse_address = True
    with tempfile.TemporaryDirectory() as td:
        address = str(Path(td) / "relp.sock")
        srv = _T(address, MyHandler)
        th = threading.Thread(target=srv.serve_forever)
        th.start()
        yield srv
        srv.shutdown()
        th.join()


@pytest.fixture()
def tcp_server():
    class _T(socketserver.TCPServer, socketserver.ThreadingMixIn):
        allow_reuse_address = True

        def verify_request(self, request, client_address):
            _log.info("connect from: %s", client_address)
            return True
    address = ("127.0.0.1", 0)
    srv = _T(address, MyHandler)
    th = threading.Thread(target=srv.serve_forever)
    th.start()
    yield srv
    srv.shutdown()
    th.join()


@pytest.fixture()
def tls_server():
    import ssl
    from OpenSSL import crypto

    class _T(socketserver.TCPServer, socketserver.ThreadingMixIn):
        allow_reuse_address = True

        def verify_request(self, request, client_address):
            _log.info("connect from: %s", client_address)
            _log.info("ssl: version=%s, cipher=%s", request.version(), request.cipher())
            return True

    srvctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    k = crypto.PKey()
    k.generate_key(crypto.TYPE_RSA, 4096)
    cert = crypto.X509()
    cert.get_subject().CN = "localhost"
    cert.set_serial_number(0)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(10*365*24*60*60)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(k)
    cert.sign(k, 'sha512')

    with tempfile.TemporaryDirectory() as td:
        certfile = Path(td) / "cert.pem"
        keyfile = Path(td) / "key.pem"
        certfile.write_bytes(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
        keyfile.write_bytes(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))

        srvctx.load_cert_chain(certfile, keyfile)
        address = ("127.0.0.1", 0)
        srv = _T(address, MyHandler, bind_and_activate=False)
        srv.socket = srvctx.wrap_socket(srv.socket, server_side=True)
        srv.server_bind()
        srv.server_activate()
        th = threading.Thread(target=srv.serve_forever)
        th.start()
        yield srv
        srv.shutdown()
        th.join()


def test_tcp(benchmark, tcp_server):
    with RelpTCPClient(tcp_server.server_address) as cl:
        benchmark(lambda: cl.send_command(b"syslog", b"").result())


def test_tcp_long(benchmark, tcp_server):
    msg = b"0123456789" * 1024
    with RelpTCPClient(tcp_server.server_address) as cl:
        benchmark(lambda: cl.send_command(b"syslog", msg).result())


def test_unix(benchmark, unix_server):
    with RelpUnixClient(unix_server.server_address) as cl:
        benchmark(lambda: cl.send_command(b"syslog", b"").result())


def test_unix_long(benchmark, unix_server):
    msg = b"0123456789" * 1024
    with RelpUnixClient(unix_server.server_address) as cl:
        benchmark(lambda: cl.send_command(b"syslog", msg).result())


def test_tls(benchmark, tls_server):
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with RelpTlsClient(tls_server.server_address, context=ctx, server_hostname="localhost") as cl:
        benchmark(lambda: cl.send_command(b"syslog", b"").result())


def test_tls_long(benchmark, tls_server):
    msg = b"0123456789" * 1024
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with RelpTlsClient(tls_server.server_address, context=ctx, server_hostname="localhost") as cl:
        benchmark(lambda: cl.send_command(b"syslog", msg).result())
