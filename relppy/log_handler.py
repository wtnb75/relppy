# -*- coding: utf-8 -*-
import time
import socket
import logging
import logging.handlers

from .client import RelpTlsClient
from .client import RelpTCPClient


class RelpHandler(logging.handlers.SysLogHandler):
    def __init__(
        self,
        address,
        facility,
        context=None,
        reconnect_timeout=1,
        logger=None,
        spool_method=None,
        exception_on_emit=False,
        active_log_handlers=[],
        **kwargs,
    ):
        facility_id = "LOG_%s" % facility
        try:
            facility = getattr(logging.handlers.SysLogHandler, facility_id)
        except Exception:
            msg = "Unknown facility: %s" % facility
            raise Exception(msg)

        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(__name__)

        self.address = address
        self.context = context
        self.facility = facility
        self.relp_client = None
        self.spool_method = spool_method
        self.exception_on_emit = exception_on_emit
        self.connection_broken = False
        self.active_log_handlers = active_log_handlers
        self.reconnect_timeout = reconnect_timeout
        self.kwargs = kwargs
        logging.Handler.__init__(self)
        self.active_log_handlers.append(self)

    def createSocket(self):
        try:
            if self.context:
                self.relp_client = RelpTlsClient(
                    address=self.address, context=self.context, server_hostname=self.address[0], **self.kwargs
                )
            else:
                self.relp_client = RelpTCPClient(address=self.address, **self.kwargs)
        except Exception as e:
            self.connection_broken = True
            msg = "Failed to connect to relp log server: %s: %s" % (self.address, e)
            self.logger.warning(msg)
            raise

    def close(self):
        self.acquire()
        try:
            if self.relp_client:
                self.relp_client.close()
                self.relp_client = None
            logging.Handler.close(self)
        finally:
            try:
                self.active_log_handlers.remove(self)
            except ValueError:
                pass
            self.release()

    def _encodemsg(self, record):
        msg = self.format(record)
        if self.ident:
            msg = self.ident + msg
        if self.append_nul:
            msg += "\000"

        # We need to convert record level to lowercase, maybe this will
        # change in the future.
        prio = "<%d>" % self.encodePriority(self.facility, self.mapPriority(record.levelname))
        prio = prio.encode("utf-8")
        # Message is a string. Convert to bytes as required by RFC 5424
        msg = msg.encode("utf-8")
        msg = prio + msg
        return msg

    def _reconnect_send(self, msg):
        reconnect_start = time.time()
        spool_message = True
        while True:
            if (time.time() - reconnect_start) >= self.reconnect_timeout:
                break
            # Try to resend message.
            try:
                self.relp_client.send_command(b"syslog", msg)
            except Exception:
                self.connection_broken = True
                spool_message = True
            else:
                self.connection_broken = False
                spool_message = False
                break
        return spool_message

    def emit(self, record):
        try:
            msg = self._encodemsg(record)
            if not self.relp_client:
                self.createSocket()
            self.relp_client.send_command(b"syslog", msg)
            self.connection_broken = False
        except Exception as e:
            if self.exception_on_emit:
                raise
            spool_message = False
            # On socket error try to resend message.
            if isinstance(e, socket.error):
                if self.connection_broken:
                    spool_message = True
                else:
                    spool_message = self._reconnect_send(msg)
            else:
                spool_message = True
            if spool_message and self.spool_method:
                try:
                    self.spool_method(record)
                except Exception as e:
                    msg = "Failed to spool record: %s" % e
                    self.logger.warning(msg)
            self.handleError(record)
