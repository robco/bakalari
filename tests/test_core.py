import unittest

from bakalari import (
    BakalariAuthError,
    BakalariClient,
    BakalariConfigError,
    BakalariConnectionError,
    BakalariContractError,
    BakalariError,
    BakalariHTTPError,
    BakalariNotFoundError,
    BakalariPermissionError,
    HttpResponse,
    SessionState,
    normalize_base_url,
    urllib_transport,
)

from .support import (
    BASE_URL,
    FORBIDDEN,
    INVALID_GRANT,
    NOT_TEACHER,
    PASSWORD,
    UNAUTHORIZED,
    USERNAME,
    FakeClock,
    FakeTransport,
    empty_response,
    json_response,
    make_client,
    text_response,
    token_response,
)

PROFILE = json_response(200, {"UserType": "parents"})
REFRESH_FORM = {"client_id": "ANDR", "grant_type": "refresh_token", "refresh_token": "refresh-1"}


class LoginTest(unittest.TestCase):
    def test_login_posts_the_password_grant_form(self):
        client, transport = make_client(token_response())
        info = client.login()
        call = transport.calls[0]
        self.assertEqual((call.method, call.url), ("POST", BASE_URL + "/api/login"))
        self.assertEqual(
            call.form, {"client_id": "ANDR", "grant_type": "password", "username": USERNAME, "password": PASSWORD}
        )
        self.assertEqual(call.headers["Content-Type"], "application/x-www-form-urlencoded")
        self.assertNotIn("Authorization", call.headers)
        self.assertEqual(
            (info.user_id, info.token_type, info.expires_in, info.api_version), ("U1", "Bearer", 3600, "3.52.1")
        )
        self.assertIn("bakalari_api", info.scopes)
        self.assertEqual(info.expires_at, 1_000_000.0 + 3600)
        self.assertTrue(client.is_authenticated)

    def test_rejected_login_raises_auth_error_without_the_password(self):
        client, _ = make_client(INVALID_GRANT)
        with self.assertRaises(BakalariAuthError) as raised:
            client.login()
        error = raised.exception
        self.assertEqual((error.status, error.expected, error.body["error"]), (400, 200, "invalid_grant"))
        self.assertEqual(error.message, "Špatný login nebo heslo")
        self.assertNotIn(PASSWORD, str(error))
        self.assertFalse(client.is_authenticated)

    def test_rejected_login_keeps_the_previous_session(self):
        client, transport = make_client(token_response(), INVALID_GRANT, PROFILE)
        client.login()
        with self.assertRaises(BakalariAuthError):
            client.login("unknown.user", "wrong")
        client.get_json("/api/3/user")
        self.assertEqual(transport.calls[2].headers["Authorization"], "Bearer access-1")

    def test_login_without_credentials_is_a_config_error(self):
        client = BakalariClient(BASE_URL, transport=FakeTransport())
        with self.assertRaises(BakalariConfigError):
            client.login()
        with self.assertRaises(BakalariConfigError):
            client.get_json("/api/3/user")

    def test_token_response_without_tokens_is_rejected(self):
        for payload in ({"token_type": "Bearer", "expires_in": 3600}, ["not", "an", "object"]):
            client, _ = make_client(json_response(200, payload))
            with self.assertRaises(BakalariError):
                client.login()
            self.assertFalse(client.is_authenticated)

    def test_unexpected_success_never_exposes_tokens(self):
        client, _ = make_client(token_response(access="secret-access", refresh="secret-refresh"))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.request("POST", "/api/login", form={"grant_type": "password"}, authorized=False, expected_status=400)
        self.assertIsNone(raised.exception.body)
        self.assertNotIn("secret", str(raised.exception))

    def test_repr_hides_secrets(self):
        client, _ = make_client(token_response(access="secret-access", refresh="secret-refresh"))
        client.login()
        texts = (repr(client), repr(client.token_info), repr(token_response(access="secret-access")),
                 repr(client.export_session()))
        for text in texts:
            self.assertNotIn("secret", text)
            self.assertNotIn(PASSWORD, text)

    def test_logout_and_context_manager_forget_the_tokens(self):
        client, _ = make_client(token_response())
        with client:
            client.login()
            self.assertTrue(client.is_authenticated)
        self.assertFalse(client.is_authenticated)
        self.assertIsNone(client.token_info)
        with self.assertRaises(BakalariError):
            client.export_session()


class TokenLifecycleTest(unittest.TestCase):
    def test_first_authorized_request_logs_in(self):
        client, transport = make_client(token_response(), PROFILE)
        client.get_json("/api/3/user")
        self.assertEqual([call.path for call in transport.calls], ["/bakaweb/api/login", "/bakaweb/api/3/user"])
        self.assertEqual(transport.calls[1].headers["Authorization"], "Bearer access-1")

    def test_valid_token_is_reused(self):
        clock = FakeClock()
        client, transport = make_client(token_response(), PROFILE, PROFILE, clock=clock)
        client.get_json("/api/3/user")
        clock.now += 3000
        client.get_json("/api/3/user")
        self.assertEqual(len(transport.calls), 3)

    def test_token_is_renewed_shortly_before_it_expires(self):
        clock = FakeClock()
        client, transport = make_client(
            token_response(), PROFILE, token_response("access-2", "refresh-2"), PROFILE, clock=clock
        )
        client.get_json("/api/3/user")
        clock.now += 3600 - 30  # inside the default 60 s renewal margin
        client.get_json("/api/3/user")
        refresh = transport.calls[2]
        self.assertEqual(refresh.form, REFRESH_FORM)
        self.assertEqual(transport.calls[3].headers["Authorization"], "Bearer access-2")
        self.assertEqual(client.token_info.expires_at, clock.now + 3600)

    def test_rejected_refresh_token_falls_back_to_a_new_login(self):
        clock = FakeClock()
        client, transport = make_client(
            token_response(), INVALID_GRANT, token_response("access-3", "refresh-3"), PROFILE, clock=clock
        )
        client.login()
        clock.now += 7200
        client.get_json("/api/3/user")
        grants = [call.form.get("grant_type") for call in transport.calls[:3]]
        self.assertEqual(grants, ["password", "refresh_token", "password"])
        self.assertEqual(transport.calls[3].headers["Authorization"], "Bearer access-3")

    def test_refused_token_is_renewed_and_the_request_retried_once(self):
        client, transport = make_client(
            token_response(), UNAUTHORIZED, token_response("access-2", "refresh-2"), PROFILE
        )
        client.get_json("/api/3/user")
        self.assertEqual(transport.calls[3].headers["Authorization"], "Bearer access-2")

    def test_second_refusal_raises_auth_error(self):
        client, transport = make_client(
            token_response(), UNAUTHORIZED, token_response("access-2", "refresh-2"), UNAUTHORIZED
        )
        with self.assertRaises(BakalariAuthError) as raised:
            client.get_json("/api/3/user")
        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(len(transport.calls), 4)

    def test_refresh_without_login_fails_clearly(self):
        client, _ = make_client()
        with self.assertRaises(BakalariError):
            client.refresh()


class SessionTest(unittest.TestCase):
    def test_client_can_start_from_a_refresh_token_alone(self):
        transport = FakeTransport(token_response("access-2", "refresh-2"), PROFILE)
        client = BakalariClient(BASE_URL, refresh_token="refresh-1", transport=transport, clock=FakeClock())
        client.get_json("/api/3/user")
        self.assertEqual(transport.calls[0].form, REFRESH_FORM)
        self.assertEqual(transport.calls[1].headers["Authorization"], "Bearer access-2")

    def test_rejected_refresh_token_without_password_raises(self):
        transport = FakeTransport(INVALID_GRANT)
        client = BakalariClient(BASE_URL, refresh_token="stale", transport=transport, clock=FakeClock())
        with self.assertRaises(BakalariAuthError):
            client.get_json("/api/3/user")

    def test_export_and_import_resume_the_session(self):
        clock = FakeClock()
        client, _ = make_client(token_response(), clock=clock)
        client.login()
        state = client.export_session()
        self.assertEqual((state.base_url, state.refresh_token, state.access_token, state.user_id),
                         (BASE_URL, "refresh-1", "access-1", "U1"))
        restored_transport = FakeTransport(PROFILE)
        restored = BakalariClient(BASE_URL, transport=restored_transport, clock=clock)
        restored.import_session(SessionState.from_dict(state.to_dict()))
        restored.get_json("/api/3/user")  # the access token is still valid: no login, no refresh
        self.assertEqual(len(restored_transport.calls), 1)
        self.assertEqual(restored_transport.calls[0].headers["Authorization"], "Bearer access-1")

    def test_import_of_an_expired_session_renews_with_the_refresh_token(self):
        clock = FakeClock()
        transport = FakeTransport(token_response("access-2", "refresh-2"), PROFILE)
        client = BakalariClient(BASE_URL, transport=transport, clock=clock)
        client.import_session({"base_url": BASE_URL, "refresh_token": "refresh-1", "access_token": "old",
                               "expires_at": clock.now - 10})
        self.assertFalse(client.is_authenticated)
        client.get_json("/api/3/user")
        self.assertEqual(transport.calls[0].form["grant_type"], "refresh_token")

    def test_import_rejects_a_session_of_another_school(self):
        client = BakalariClient(BASE_URL, transport=FakeTransport())
        with self.assertRaises(BakalariConfigError):
            client.import_session({"base_url": "https://other.example", "refresh_token": "r"})
        with self.assertRaises(BakalariConfigError):
            SessionState.from_dict({"base_url": BASE_URL})

    def test_session_update_callback_sees_every_new_token_pair(self):
        clock = FakeClock()
        seen = []
        client, _ = make_client(token_response(), token_response("access-2", "refresh-2"), clock=clock,
                                on_session_update=seen.append)
        client.login()
        client.refresh()
        self.assertEqual([state.refresh_token for state in seen], ["refresh-1", "refresh-2"])


class RequestTest(unittest.TestCase):
    def test_unauthorized_request_carries_no_token(self):
        client, transport = make_client(UNAUTHORIZED)
        response = client.request("GET", "/api/3/timetable/actual", authorized=False, expected_status=401)
        self.assertEqual(response.json()["Message"], "Authorization has been denied for this request.")
        self.assertNotIn("Authorization", transport.calls[0].headers)

    def test_explicit_access_token_skips_login_and_retry(self):
        client, transport = make_client(UNAUTHORIZED)
        client.request("GET", "/api/3/timetable/actual", access_token="forged", expected_status=401)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0].headers["Authorization"], "Bearer forged")

    def test_unexpected_status_raises_http_error_with_the_error_body(self):
        invalid_date = json_response(400, {"Message": "The request is invalid.", "ModelState": {"date": ["bad"]}})
        client, transport = make_client(token_response(), invalid_date)
        with self.assertRaises(BakalariHTTPError) as raised:
            client.get_json("/api/3/timetable/actual", {"date": "not-a-date"})
        self.assertNotIsInstance(raised.exception, BakalariAuthError)
        self.assertIn("date", raised.exception.body["ModelState"])
        self.assertEqual(raised.exception.message, "The request is invalid.")
        self.assertEqual(transport.calls[1].query, {"date": "not-a-date"})

    def test_forbidden_and_not_found_have_their_own_errors(self):
        page = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1250"/>'
                "<title>404 - Soubor nebo adresář nebyl nalezen.</title></head></html>")
        html_404 = HttpResponse(404, {"Content-Type": "text/html"}, page.encode("cp1250"))
        client, _ = make_client(token_response(), NOT_TEACHER, FORBIDDEN, html_404)
        with self.assertRaises(BakalariPermissionError) as raised:
            client.get_json("/api/3/classbook/lessonTags")
        self.assertEqual(raised.exception.message, "Some privilege is missing (IsTeacher).")
        with self.assertRaises(BakalariPermissionError):
            client.get_json("/api/3/payments/classfund")
        with self.assertRaises(BakalariNotFoundError) as raised:
            client.get_json("/api/3/komens/message-types/reply")
        self.assertEqual(raised.exception.body, "404 - Soubor nebo adresář nebyl nalezen.")

    def test_expected_status_accepts_a_collection_or_none(self):
        client, _ = make_client(token_response(), empty_response(204), json_response(503, {"Message": "down"}))
        self.assertEqual(client.request("PUT", "/api/3/x", expected_status=(200, 204)).status, 204)
        self.assertEqual(client.request("GET", "/api/3", authorized=False, expected_status=None).status, 503)

    def test_error_message_names_every_expected_status(self):
        client, _ = make_client(token_response(), json_response(500, {"Message": "An error has occurred."}))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.request("PUT", "/api/3/x", expected_status=(204, 200))
        self.assertIn("HTTP 500 instead of 200 or 204", str(raised.exception))

    def test_json_body_put_and_delete(self):
        client, transport = make_client(
            token_response(), json_response(200, {"Message": ""}), empty_response(), empty_response()
        )
        sent = client.post_json("/api/3/komens/message", json_body={"Title": "Ahoj", "Text": "č"})
        self.assertEqual(sent, {"Message": ""})
        client.request("PUT", "/api/3/komens/message/1/mark-as-read", expected_status=204)
        client.request("DELETE", "/api/3/x/1", expected_status=204)
        post, put, delete = transport.calls[1:]
        self.assertEqual(post.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(post.json, {"Title": "Ahoj", "Text": "č"})
        self.assertEqual((put.method, put.body, delete.method), ("PUT", None, "DELETE"))

    def test_invalid_request_arguments(self):
        client, _ = make_client()
        with self.assertRaises(ValueError):
            client.request("TRACE", "/api/3", authorized=False)
        with self.assertRaises(ValueError):
            client.request("POST", "/api/3", authorized=False, form={"a": 1}, json_body={"a": 1})
        with self.assertRaises(ValueError):
            client.request("POST", "/api/3", authorized=False, json_body={"a": 1}, data=b"x")

    def test_raw_body_with_its_content_type(self):
        client, transport = make_client(json_response(200, "attachment-id"))
        response = client.request("POST", "/api/3/komens/attachment", authorized=False, data=b"--b\r\n...",
                                  headers={"Content-Type": "multipart/form-data; boundary=b"})
        self.assertEqual(response.json(), "attachment-id")
        self.assertEqual(transport.calls[0].body, b"--b\r\n...")
        self.assertEqual(transport.calls[0].headers["Content-Type"], "multipart/form-data; boundary=b")

    def test_relative_path_query_merging_and_none_parameters(self):
        client, transport = make_client(json_response(200, {}))
        client.request("GET", "api/3?x=1", params={"from": "2026-10-01", "to": None}, authorized=False)
        self.assertEqual(transport.calls[0].url, BASE_URL + "/api/3?x=1&from=2026-10-01")

    def test_non_json_body_is_a_contract_error(self):
        client, _ = make_client(text_response(200, "<html>login page</html>"))
        with self.assertRaises(BakalariContractError) as raised:
            client.get_json("/api/3", authorized=False)
        self.assertIn("text/html instead of JSON", str(raised.exception))

    def test_headers_identify_the_client_and_can_be_overridden(self):
        client, transport = make_client(text_response(200, "<html></html>"))
        client.request("GET", "/Timetable/Public", authorized=False, headers={"Accept": "text/html"})
        headers = transport.calls[0].headers
        self.assertEqual(headers["Accept"], "text/html")
        self.assertEqual(headers["Accept-Language"], "cs")
        self.assertTrue(headers["User-Agent"].startswith("bakalari-api-python/"))

    def test_connection_failure_raises_connection_error_without_the_query(self):
        send = urllib_transport()
        with self.assertRaises(BakalariConnectionError) as raised:
            send("POST", "http://127.0.0.1:9/api/3/register-notification?token=push-secret", {}, b"null", 2.0)
        self.assertIn("http://127.0.0.1:9/api/3/register-notification", str(raised.exception))
        self.assertNotIn("push-secret", str(raised.exception))


class DiagnosticPrivacyTest(unittest.TestCase):
    path = "/api/3/register-notification?token=query-secret#fragment-secret"

    def assert_private(self, text):
        self.assertIn("/api/3/register-notification", text)
        self.assertNotIn("query-secret", text)
        self.assertNotIn("fragment-secret", text)

    def test_http_error_path_and_message_omit_query_and_fragment(self):
        client, transport = make_client(json_response(400, {"Message": "bad request"}))
        with self.assertLogs("bakalari.client", level="DEBUG") as logs:
            with self.assertRaises(BakalariHTTPError) as raised:
                client.request("POST", self.path, authorized=False)
        self.assert_private(str(raised.exception))
        self.assertEqual(raised.exception.path, "/api/3/register-notification")
        self.assert_private("\n".join(logs.output))
        self.assertEqual(transport.calls[0].url, BASE_URL + self.path)

    def test_directly_constructed_http_error_is_private(self):
        self.assert_private(str(BakalariHTTPError("POST", self.path, 400, 200)))

    def test_json_contract_error_omits_query_and_fragment(self):
        client, _ = make_client(text_response(200, "not JSON"))
        with self.assertRaises(BakalariContractError) as raised:
            client.get_json(self.path, authorized=False)
        self.assert_private(str(raised.exception))

    def test_retry_and_success_logs_omit_query_and_fragment(self):
        client, transport = make_client(
            BakalariConnectionError("reset"), json_response(503, {}), json_response(200, {}), retries=2
        )
        with self.assertLogs("bakalari.client", level="DEBUG") as logs:
            client.request("GET", self.path, authorized=False)
        self.assert_private("\n".join(logs.output))
        self.assertTrue(any("failed" in line for line in logs.output))
        self.assertTrue(any("answered HTTP 503" in line for line in logs.output))
        self.assertTrue(any("HTTP 200" in line for line in logs.output))
        self.assertEqual([call.url for call in transport.calls], [BASE_URL + self.path] * 3)


class RetryTest(unittest.TestCase):
    def setUp(self):
        self.sleeps = []

    def client(self, *responses, retries=2):
        return make_client(*responses, retries=retries, retry_backoff=0.5, sleep=self.sleeps.append)

    def test_get_is_retried_after_connection_errors_and_gateway_statuses(self):
        client, transport = self.client(
            BakalariConnectionError("reset"), json_response(503, {}), json_response(200, [1])
        )
        self.assertEqual(client.get_json("/api", authorized=False), [1])
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(self.sleeps, [0.5, 1.0])

    def test_retries_are_bounded(self):
        client, transport = self.client(json_response(502, {}), json_response(502, {}), json_response(502, {}))
        with self.assertRaises(BakalariHTTPError) as raised:
            client.get_json("/api", authorized=False)
        self.assertEqual((raised.exception.status, len(transport.calls)), (502, 3))
        client, _ = self.client(*(BakalariConnectionError(reason) for reason in "abc"))
        with self.assertRaises(BakalariConnectionError):
            client.get_json("/api", authorized=False)

    def test_post_and_the_default_client_are_not_retried(self):
        client, transport = self.client(json_response(503, {}))
        with self.assertRaises(BakalariHTTPError):
            client.request("POST", "/api/3/komens/message", authorized=False, json_body={})
        self.assertEqual(len(transport.calls), 1)
        client, transport = make_client(json_response(503, {}))
        with self.assertRaises(BakalariHTTPError):
            client.get_json("/api", authorized=False)
        self.assertEqual(len(transport.calls), 1)


class PublicEndpointTest(unittest.TestCase):
    def test_api_version_needs_no_login(self):
        version = {"ApiVersion": "3.52.1", "ApplicationVersion": "2.2.1009.7", "BaseUrl": "api/3"}
        client, transport = make_client(json_response(200, version), json_response(200, [version]))
        self.assertEqual(client.api_version()["ApiVersion"], "3.52.1")
        self.assertEqual(client.available_api_versions()[0]["BaseUrl"], "api/3")
        self.assertEqual([call.path for call in transport.calls], ["/bakaweb/api/3", "/bakaweb/api"])
        self.assertFalse(client.is_authenticated)

    def test_unexpected_version_payloads(self):
        client, _ = make_client(json_response(200, []), json_response(200, {}))
        with self.assertRaises(BakalariContractError):
            client.api_version()
        with self.assertRaises(BakalariContractError):
            client.available_api_versions()


class ConfigurationTest(unittest.TestCase):
    def test_from_env_reads_address_and_login(self):
        env = {"BAKALARI_USERNAME": USERNAME, "BAKALARI_PASSWORD": PASSWORD, "BAKALARI_URL": BASE_URL}
        client = BakalariClient.from_env(environ=env, transport=FakeTransport())
        self.assertIsInstance(client, BakalariClient)
        self.assertEqual(client.base_url, BASE_URL)
        other = BakalariClient.from_env(environ={"U": "u", "P": "p"}, username_env="U", password_env="P",
                                        base_url="https://other.example/")
        self.assertEqual(other.base_url, "https://other.example")

    def test_missing_variables_are_named(self):
        with self.assertRaises(BakalariConfigError) as raised:
            BakalariClient.from_env(environ={"BAKALARI_USERNAME": USERNAME})
        message = str(raised.exception)
        self.assertIn("BAKALARI_URL, BAKALARI_PASSWORD", message)
        self.assertNotIn("BAKALARI_USERNAME", message)

    def test_base_url_is_required_and_normalized(self):
        with self.assertRaises(BakalariConfigError):
            BakalariClient("")
        cases = {
            "skola.bakalari.cz": "https://skola.bakalari.cz",
            "https://skola.bakalari.cz/": "https://skola.bakalari.cz",
            "https://skola.bakalari.cz/bakaweb/login": "https://skola.bakalari.cz/bakaweb",
            "https://skola.bakalari.cz/bakaweb/Login?ReturnUrl=x": "https://skola.bakalari.cz/bakaweb",
            "https://skola.bakalari.cz/next/dash.aspx": "https://skola.bakalari.cz",
            "https://skola.bakalari.cz/Timetable/Public/Actual/Room/G0": "https://skola.bakalari.cz",
            "HTTPS://www.example.com:444/bakalari/dashboard": "https://www.example.com:444/bakalari",
            "https://skola.bakalari.cz/api/3": "https://skola.bakalari.cz",
        }
        for given, expected in cases.items():
            self.assertEqual(normalize_base_url(given), expected, given)


if __name__ == "__main__":
    unittest.main()
