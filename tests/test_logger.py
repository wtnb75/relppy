import unittest
import socketserver
import threading
from relppy.protocol import Message
from relppy.server import RelpStreamHandler
import logging
from relppy.log_handler import RelpHandler


class MyHandler(RelpStreamHandler):
    def do_syslog(self, msg: Message):
        self.server.msgs.append(msg.data.decode())
        return "OK"


class MyServer(socketserver.TCPServer, socketserver.ThreadingMixIn):
    allow_reuse_address = True
    msgs: list[str]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.msgs = []


class TestLogger(unittest.TestCase):
    def setUp(self):
        self.srv = MyServer(("localhost", 0), MyHandler)
        self.th = threading.Thread(target=self.srv.serve_forever)
        self.th.start()
        self.log_handler = RelpHandler(address=self.srv.server_address, facility="LOCAL7")

        self.formatter = logging.Formatter("%(name)s: [%(levelname)s] %(message)s")
        self.log_handler.setFormatter(self.formatter)
        self.logger = logging.getLogger("my_logger")
        self.logger.addHandler(self.log_handler)

    def tearDown(self):
        self.log_handler.close()
        del self.log_handler
        del self.formatter
        del self.logger
        self.srv.shutdown()
        del self.srv
        self.th.join()
        del self.th

    def test_log_normal(self):
        self.logger.error("hello error")
        self.logger.warning("hello warning")
        self.logger.info("hello info")
        self.logger.debug("hello debug")
        self.log_handler.close()  # flush
        self.assertEqual(4, len(self.srv.msgs))
        self.assertEqual(
            [
                "<187>my_logger: [ERROR] hello error\x00",
                "<188>my_logger: [WARNING] hello warning\x00",
                "<190>my_logger: [INFO] hello info\x00",
                "<191>my_logger: [DEBUG] hello debug\x00",
            ],
            self.srv.msgs,
        )
