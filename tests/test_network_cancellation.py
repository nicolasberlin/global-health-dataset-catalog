"""Cooperative worker cancellation closes sockets before propagating."""

import socket
from unittest.mock import Mock

import pytest

from collector import fetch
from collector.execution import ExecutionStopped


def test_cancellation_after_connect_closes_socket(monkeypatch):
    connection = Mock()
    monkeypatch.setattr(fetch.socket, "getaddrinfo", Mock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
    ]))
    monkeypatch.setattr(fetch.socket, "socket", Mock(return_value=connection))
    monkeypatch.setattr(fetch, "check_request_budget", Mock(side_effect=[
        None, None, None, ExecutionStopped(),
    ]))
    with pytest.raises(ExecutionStopped):
        fetch._connect_public("example.org", 443, 1)
    connection.close.assert_called_once()


def test_cancellation_after_tls_handshake_closes_socket(monkeypatch):
    wrapped = Mock()
    context = Mock(wrap_socket=Mock(return_value=wrapped))
    monkeypatch.setattr(fetch.ssl, "create_default_context", Mock(return_value=context))

    def connect(connection):
        connection.sock = Mock()

    monkeypatch.setattr(fetch._PublicHTTPConnection, "connect", connect)
    monkeypatch.setattr(fetch, "check_request_budget", Mock(side_effect=ExecutionStopped()))
    connection = fetch._PublicHTTPSConnection("example.org", timeout=1)
    with pytest.raises(ExecutionStopped):
        connection.connect()
    wrapped.close.assert_called_once()
