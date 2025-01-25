import unittest
from relppy.protocol import Message


class TestProtocol(unittest.TestCase):
    def test_pack0(self):
        self.assertEqual(Message(123, b"hello").pack(),
                         b"123 hello 0\n")

    def test_pack(self):
        self.assertEqual(Message(1234, b"hello", b"world").pack(),
                         b"1234 hello 5 world\n")

    def test_str(self):
        self.assertEqual("txnr=1234 command='hello' data='world'",
                         str(Message(1234, b"hello", b"world")))

    def test_unpack0(self):
        msg = Message()
        d = b"123 hello 0\n"
        self.assertEqual(len(d), msg.unpack(d))
        self.assertEqual(msg,
                         Message(123, b"hello"))

    def test_unpack0_rest(self):
        msg = Message()
        d = b"123 hello 0\nworld"
        self.assertEqual(12, msg.unpack(d))
        self.assertEqual(b"world", d[12:])
        self.assertEqual(msg,
                         Message(123, b"hello"))

    def test_unpack_short(self):
        msg = Message()
        d = b"123 hell"
        self.assertEqual(0, msg.unpack(d))

    def test_unpack(self):
        msg = Message()
        d = b"1234 hello 5 world\n"
        self.assertEqual(len(d), msg.unpack(d))
        self.assertEqual(msg,
                         Message(1234, b"hello", b"world"))

    def test_unpack_nl(self):
        msg = Message()
        d = b"1234 hello 11 wor d\nworld\n"
        self.assertEqual(len(d), msg.unpack(d))
        self.assertEqual(msg,
                         Message(1234, b"hello", b"wor d\nworld"))

    def test_unpack_invalid(self):
        msg = Message()
        d = b"1234 hello 10 word\n"
        with self.assertRaises(ValueError) as ve:
            msg.unpack(d)
        self.assertIn("length", ve.exception.args[0])

    def test_unpack_nonl(self):
        msg = Message()
        d = b"1234 hello 5 world "
        with self.assertRaises(ValueError) as ve:
            msg.unpack(d)
        self.assertIn("tail", ve.exception.args[0])

    def test_unpack_rest(self):
        msg = Message()
        d = b"1234 hello 5 world\nworld"
        self.assertEqual(19, msg.unpack(d))
        self.assertEqual(b"world", d[19:])
        self.assertEqual(msg,
                         Message(1234, b"hello", b"world"))
