import io
import unittest
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from http.client import IncompleteRead
from unittest.mock import patch

from bakalari import BakalariConnectionError, HttpResponse, urllib_transport
from bakalari.http import parse_content_disposition


class TruncatedBody:
    """A response body stream that dies mid-read, like a school server cutting the connection."""

    def __init__(self):
        self.closed = False

    def read(self, *args):
        raise IncompleteRead(b"partial", 100)

    def close(self):
        self.closed = True


class TruncatedBodyTest(unittest.TestCase):
    def send(self, *, error_status=None):
        def open_request(handler, request):
            headers = Message()
            if error_status is not None:
                raise urllib.error.HTTPError(request.full_url, error_status, "synthetic", headers, TruncatedBody())
            response = urllib.response.addinfourl(TruncatedBody(), headers, request.full_url, 200)
            response.msg = "synthetic response"
            return response

        with patch("urllib.request.getproxies", return_value={}), \
                patch.object(urllib.request.HTTPSHandler, "https_open", open_request), \
                patch.object(urllib.request.HTTPHandler, "http_open", open_request):
            return urllib_transport()("GET", "https://school.example/api/3/user", {}, None, 5)

    def test_truncated_body_is_a_connection_error(self):
        # No usable response arrived, so the caller may re-send the request under its retries policy.
        with self.assertRaises(BakalariConnectionError):
            self.send()

    def test_error_status_survives_a_truncated_error_body(self):
        response = self.send(error_status=503)
        self.assertEqual((response.status, response.body), (503, b""))


class HttpResponseTest(unittest.TestCase):
    def test_text_and_json(self):
        response = HttpResponse(200, {}, '{"a": "č"}'.encode("utf-8"))
        self.assertEqual(response.json(), {"a": "č"})
        self.assertEqual(response.text, '{"a": "č"}')
        self.assertIsNone(HttpResponse(204, {}, b"").json())
        self.assertEqual(HttpResponse(200, {}, b'\xef\xbb\xbf{"bom": 1}').json(), {"bom": 1})

    def test_headers_are_matched_case_insensitively(self):
        response = HttpResponse(200, {"content-type": "Application/JSON; charset=utf-8"}, b"")
        self.assertEqual(response.header("Content-Type"), "Application/JSON; charset=utf-8")
        self.assertEqual(response.content_type, "application/json")
        self.assertIsNone(response.header("Location"))
        self.assertEqual(HttpResponse(200, {}, b"").content_type, "")

    def test_body_is_not_in_repr(self):
        self.assertNotIn("secret", repr(HttpResponse(200, {}, b'{"access_token": "secret"}', "https://x")))


class RedirectTest(unittest.TestCase):
    def send(self, targets, *, url="https://school.example/api/3/user", headers=None, body=None, code=302):
        calls = []

        def open_request(handler, request):
            calls.append(request)
            response_headers = Message()
            status = 200
            if len(calls) <= len(targets):
                response_headers["Location"] = targets[len(calls) - 1]
                status = code
            response = urllib.response.addinfourl(io.BytesIO(b"{}"), response_headers, request.full_url, status)
            response.msg = "synthetic response"
            return response

        # Replace only network I/O: urllib's real opener, redirect handling and error processing still run.
        with patch("urllib.request.getproxies", return_value={}), \
                patch.object(urllib.request.HTTPSHandler, "https_open", open_request), \
                patch.object(urllib.request.HTTPHandler, "http_open", open_request):
            result = urllib_transport()("POST" if body is not None else "GET", url, headers or {}, body, 5)
        return result, calls

    def test_authorized_redirects_cannot_change_host_or_port(self):
        for code in (301, 302, 303, 307, 308):
            for target in ("https://other.example/collect", "https://school.example:444/collect"):
                with self.subTest(code=code, target=target):
                    result, calls = self.send([target], headers={"authorization": "Bearer secret"}, code=code)
                    self.assertEqual(result.status, code)
                    self.assertEqual(len(calls), 1, "the redirect destination must never be contacted")

    def test_authorized_same_origin_redirect_keeps_the_token(self):
        for target in ("/api/3/profile", "https://SCHOOL.EXAMPLE:443/api/3/profile"):
            with self.subTest(target=target):
                result, calls = self.send([target], headers={"Authorization": "Bearer secret"})
                self.assertEqual(result.status, 200)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[1].get_header("Authorization"), "Bearer secret")

    def test_https_downgrades_are_blocked_even_for_public_requests(self):
        for headers in ({}, {"Authorization": "Bearer secret"}):
            with self.subTest(headers=headers):
                result, calls = self.send(["http://school.example/public"], headers=headers)
                self.assertEqual(result.status, 302)
                self.assertEqual(len(calls), 1)

    def test_public_redirects_can_change_host_and_upgrade_to_https(self):
        result, calls = self.send(["https://public.example/timetable"], url="http://school.example/Timetable/Public")
        self.assertEqual(result.status, 200)
        self.assertEqual(result.url, "https://public.example/timetable")
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[1].get_header("Authorization"))

    def test_public_error_page_redirect_is_preserved(self):
        result, calls = self.send(["/Timetable/Public/ErrInfo"])
        self.assertEqual(result.status, 200)
        self.assertTrue(result.url.endswith("/Timetable/Public/ErrInfo"))
        self.assertEqual(len(calls), 2)

    def test_login_body_cannot_redirect_to_another_origin(self):
        result, calls = self.send(["https://other.example/login"], body=b"password=secret")
        self.assertEqual(result.status, 302)
        self.assertEqual(len(calls), 1)

    def test_login_redirect_chain_remains_restricted_after_body_is_dropped(self):
        result, calls = self.send(["/login-result", "https://other.example/collect"], body=b"password=secret")
        self.assertEqual(result.status, 302)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].get_method(), "GET")
        self.assertIsNone(calls[1].data)

    def test_public_redirect_chain_cannot_downgrade_after_https_upgrade(self):
        result, calls = self.send(
            ["https://public.example/timetable", "http://public.example/result"], url="http://school.example/public"
        )
        self.assertEqual(result.status, 302)
        self.assertEqual(len(calls), 2)

    def test_public_redirect_cannot_switch_to_ftp(self):
        result, calls = self.send(["ftp://other.example/file"], url="http://school.example/public")
        self.assertEqual(result.status, 302)
        self.assertEqual(len(calls), 1)


class ContentDispositionTest(unittest.TestCase):
    def test_bakalari_attachment_header(self):
        # Literal header from the community documentation of /api/3/komens/attachment/{id}
        header = ("attachment; name=\"=?utf-8?B?TmV2ZXIgZ29ubmEgZ2l2ZSB5b3UgdXAudHh0?=\"; "
                  "filename*=utf-8''%4E%65%76%65%72%20%67%6F%6E%6E%61%20%67%69%76%65%20%79%6F%75%20%75%70.txt")
        self.assertEqual(parse_content_disposition(header), "Never gonna give you up.txt")

    def test_name_parameter_alone_with_encoded_word_or_ascii(self):
        self.assertEqual(parse_content_disposition('attachment; name="=?utf-8?B?xb5sdcWlb3XEjWvDvS5wZGY=?="'),
                         "žluťoučký.pdf")
        self.assertEqual(parse_content_disposition("attachment; name=report.pdf"), "report.pdf")

    def test_filename_variants(self):
        self.assertEqual(parse_content_disposition('attachment; filename="a \\"quoted\\" name.txt"'),
                         'a "quoted" name.txt')
        self.assertEqual(parse_content_disposition("attachment; filename*=UTF-8''%C3%BAkol%201.docx; filename=x.docx"),
                         "úkol 1.docx")

    def test_unsafe_or_missing_names(self):
        self.assertEqual(parse_content_disposition('attachment; filename="../../etc/passwd"'), "passwd")
        self.assertEqual(parse_content_disposition('attachment; filename="C:\\\\temp\\\\a.txt"'), "a.txt")
        self.assertIsNone(parse_content_disposition('attachment; filename=".."'))
        self.assertIsNone(parse_content_disposition("attachment"))
        self.assertIsNone(parse_content_disposition(None))
        self.assertIsNone(parse_content_disposition(""))

    def test_malformed_extended_filename_uses_fallback(self):
        for extended in ("utf-8'broken", "broken", "utf-8''"):
            with self.subTest(extended=extended):
                self.assertEqual(parse_content_disposition(
                    f"attachment; filename*={extended}; filename=fallback.txt"), "fallback.txt")
        self.assertIsNone(parse_content_disposition("attachment; filename*=utf-8'broken"))


if __name__ == "__main__":
    unittest.main()
