import unittest
import socketserver
import threading
from relppy.protocol import Message
from relppy.client import RelpTCPClient
from relppy.server import RelpStreamHandler


class MyHandler(RelpStreamHandler):
    def do_syslog(self, msg: Message):
        return msg.data.decode()


class MyServer(socketserver.TCPServer, socketserver.ThreadingMixIn):
    allow_reuse_address = True


class TestClSrv(unittest.TestCase):
    def setUp(self):
        self.srv = MyServer(("localhost", 0), MyHandler)
        self.th = threading.Thread(target=self.srv.serve_forever)
        self.th.start()

    def tearDown(self):
        self.srv.shutdown()
        del self.srv
        self.th.join()
        del self.th

    def test_syslog_send(self):
        res = []
        expected = [f"200 OK\nhello {x}".encode() for x in range(10)]
        with RelpTCPClient(self.srv.server_address) as cl:
            for i in range(10):
                res.append(cl.send_command(b"syslog", f"hello {i}".encode()))

            self.assertEqual([x.result() for x in res], expected)

    def test_syslog_latch(self):
        res = []
        expected = [f"200 OK\nhello {x}".encode() for x in range(10)]
        with RelpTCPClient(self.srv.server_address) as cl:
            cl.cur_txnr = cl.MAX_TXNR-5
            for i in range(10):
                res.append(cl.send_command(b"syslog", f"hello {i}".encode()))

            self.assertEqual([x.result() for x in res], expected)
