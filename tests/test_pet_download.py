import http.client
import io
import json
import socket
import time
import unittest
from unittest.mock import Mock, patch

from mxbridge import pet_download as download


def address(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    target = (ip, 443, 0, 0) if family == socket.AF_INET6 else (ip, 443)
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", target


def response(raw=b"pet bytes", status=200, headers=None):
    stream = io.BytesIO(raw)
    value = Mock(status=status)
    value.getheader.side_effect = lambda name, default=None: (headers or {}).get(name, default)
    value.read1.side_effect = stream.read1
    value.isclosed.return_value = False
    return value


class PetDownloadTests(unittest.TestCase):
    def test_only_https_urls_without_credentials_or_control_characters(self):
        for url in ("file:///tmp/pet.png", "http://example.com/pet.png", "//example.com/pet.png",
                    "https://user:password@example.com/pet.zip", "https://example.com:0/pet",
                    "https://example.com:99999/pet", "https://exa\nmple.com/pet", "https://example.com\\@other/pet",
                    "https://[fe80::1%25en0]/pet", "https://example.com/" + "x" * 4096, None):
            with self.subTest(url=url), self.assertRaises(ValueError):
                download.parse_url(url)
        self.assertEqual(download.parse_url("https://example.com:8443/pet.zip?signature=a%2Bb").port, 8443)

    def test_private_special_and_mixed_dns_addresses_are_rejected(self):
        private = ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "0.0.0.0",
                   "100.64.0.1", "224.0.0.1", "::1", "fe80::1", "fd00::1", "ff02::1",
                   "::ffff:127.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::"]
        for ip in private:
            with self.subTest(ip=ip), patch("socket.getaddrinfo", return_value=[address("1.1.1.1"), address(ip)]):
                with self.assertRaisesRegex(ValueError, "public"):
                    download.public_addresses("host.example", 443)
        with patch("socket.getaddrinfo", return_value=[address("1.1.1.1"), address("2606:4700:4700::1111")]):
            self.assertEqual(len(download.public_addresses("host.example", 443)), 2)

    def test_connection_pins_numeric_destination_and_keeps_tls_hostname(self):
        transport, tls, context = Mock(), Mock(), Mock()
        context.wrap_socket.return_value = tls
        with patch("socket.getaddrinfo", return_value=[address("1.1.1.1")]) as dns, \
                patch("socket.socket", return_value=transport), \
                patch("ssl.create_default_context", return_value=context):
            connection, actual = download.connect(download.parse_url("https://pets.example/a"), time.monotonic() + 30)
        self.assertIs(actual, tls)
        self.assertIs(connection.sock, tls)
        self.assertEqual(dns.call_count, 1)
        transport.connect.assert_called_once_with(("1.1.1.1", 443))
        context.wrap_socket.assert_called_once_with(transport, server_hostname="pets.example")

    def test_redirect_targets_are_revalidated_before_connections(self):
        first, transport = Mock(), Mock()
        first.getresponse.return_value = response(status=302, headers={"Location": "https://127.0.0.1/private"})
        with patch.object(download, "connect", side_effect=[(first, transport), ValueError("public hosts only")]) as connect:
            with self.assertRaisesRegex(ValueError, "public"):
                download.download("https://public.example/pet.zip")
        self.assertEqual(connect.call_args_list[1].args[0].hostname, "127.0.0.1")
        first.close.assert_called_once()
        transport.close.assert_called_once()
        first.getresponse.return_value.close.assert_called_once()
        first.getresponse.return_value.read1.assert_not_called()

    def test_redirect_downgrade_and_loops_are_rejected(self):
        for target, message, count in (("http://other.example/pet.zip", "HTTPS", 1),
                                        ("/same", "redirect", 6)):
            connection, transport = Mock(), Mock()
            connection.getresponse.return_value = response(status=302, headers={"Location": target})
            with self.subTest(target=target), patch.object(download, "connect", return_value=(connection, transport)) as connect:
                with self.assertRaisesRegex(ValueError, message):
                    download.download("https://example.com/pet.zip")
                self.assertEqual(connect.call_count, count)

    def test_download_bounds_length_stream_encoding_status_and_deadline(self):
        cases = [
            (response(b"123456", headers={"Content-Length": "6"}), "size limit"),
            (response(b"123456"), "size limit"),
            (response(b"123", headers={"Content-Length": "4"}), "incomplete"),
            (response(headers={"Content-Encoding": "gzip"}), "encoding"),
            (response(status=403), "HTTP 403"),
        ]
        for reply, message in cases:
            connection, transport = Mock(), Mock()
            connection.getresponse.return_value = reply
            with self.subTest(message=message), patch.object(download, "connect", return_value=(connection, transport)):
                with self.assertRaisesRegex(ValueError, message):
                    download.download("https://example.com/pet", limit=5)
                reply.close.assert_called_once()
        with patch.object(download, "connect") as connect:
            with self.assertRaisesRegex(ValueError, "timed out"):
                download.download("https://example.com/pet", deadline=time.monotonic() - 1)
            connect.assert_not_called()

    def test_redirected_signed_download_preserves_query_and_sends_no_authorization(self):
        first, second, transport = Mock(), Mock(), Mock()
        first.getresponse.return_value = response(status=302, headers={
            "Location": "https://cdn.example/download?signature=a%2Bb&expires=123"})
        second.getresponse.return_value = response(b"image")
        with patch.object(download, "connect", side_effect=[(first, transport), (second, transport)]):
            self.assertEqual(download.download("https://example.com/pet"), b"image")
        self.assertEqual(second.request.call_args.args, ("GET", "/download?signature=a%2Bb&expires=123"))
        headers = second.request.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)

    def test_catalog_page_uses_metadata_and_direct_download_magic_not_file_extension(self):
        metadata = json.dumps({"pet": {"downloadUrl": "/api/pets/banana-cat/download?v=123"}}).encode()
        archive = b"PK\x03\x04fixture"
        with patch.object(download, "download", side_effect=[metadata, archive]) as fetch:
            self.assertEqual(download.fetch_pet("https://codex-pets.net/#/pets/banana-cat"), (archive, "pet.codex-pet.zip"))
        self.assertEqual(fetch.call_args_list[0].args[0], "https://codex-pets.net/api/pets/banana-cat")
        self.assertEqual(fetch.call_args_list[1].args[0], "https://codex-pets.net/api/pets/banana-cat/download?v=123")
        self.assertEqual(fetch.call_args_list[0].kwargs["deadline"], fetch.call_args_list[1].kwargs["deadline"])
        for raw, filename in ((b"\x89PNG\r\n\x1a\nfixture", "pet.png"), (b"RIFF1234WEBPfixture", "pet.webp")):
            with patch.object(download, "download", return_value=raw):
                self.assertEqual(download.fetch_pet("https://assets.example/download?token=a"), (raw, filename))

    def test_missing_catalog_download_and_html_pages_produce_actionable_errors(self):
        with patch.object(download, "download", return_value=b'{"pet":{}}'):
            with self.assertRaisesRegex(ValueError, "no usable download"):
                download.fetch_pet("https://codex-pets.net/#/pets/missing")
        with patch.object(download, "download", return_value=b"<html>page</html>"):
            with self.assertRaisesRegex(ValueError, "direct file URL"):
                download.fetch_pet("https://example.com/not-a-file")
        with patch.object(download, "connect", side_effect=http.client.RemoteDisconnected("secret URL")):
            with self.assertRaisesRegex(ValueError, "check the link") as caught:
                download.download("https://example.com/pet?token=secret")
            self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
