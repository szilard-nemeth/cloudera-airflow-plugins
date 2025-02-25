#  Cloudera Airflow Provider
#  (C) Cloudera, Inc. 2021-2022
#  All rights reserved.
#  Applicable Open Source License: Apache License Version 2.0
#
#  NOTE: Cloudera open source products are modular software products
#  made up of hundreds of individual components, each of which was
#  individually copyrighted.  Each Cloudera open source product is a
#  collective work under U.S. Copyright Law. Your license to use the
#  collective work is as provided in your written agreement with
#  Cloudera.  Used apart from the collective work, this file is
#  licensed for your use pursuant to the open source license
#  identified above.
#
#  This code is provided to you pursuant a written agreement with
#  (i) Cloudera, Inc. or (ii) a third-party authorized to distribute
#  this code. If you do not have a written agreement with Cloudera nor
#  with an authorized and properly licensed third party, you do not
#  have any rights to access nor to use this code.
#
#  Absent a written agreement with Cloudera, Inc. (“Cloudera”) to the
#  contrary, A) CLOUDERA PROVIDES THIS CODE TO YOU WITHOUT WARRANTIES OF ANY
#  KIND; (B) CLOUDERA DISCLAIMS ANY AND ALL EXPRESS AND IMPLIED
#  WARRANTIES WITH RESPECT TO THIS CODE, INCLUDING BUT NOT LIMITED TO
#  IMPLIED WARRANTIES OF TITLE, NON-INFRINGEMENT, MERCHANTABILITY AND
#  FITNESS FOR A PARTICULAR PURPOSE; (C) CLOUDERA IS NOT LIABLE TO YOU,
#  AND WILL NOT DEFEND, INDEMNIFY, NOR HOLD YOU HARMLESS FOR ANY CLAIMS
#  ARISING FROM OR RELATED TO THE CODE; AND (D)WITH RESPECT TO YOUR EXERCISE
#  OF ANY RIGHTS GRANTED TO YOU FOR THE CODE, CLOUDERA IS NOT LIABLE FOR ANY
#  DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, PUNITIVE OR
#  CONSEQUENTIAL DAMAGES INCLUDING, BUT NOT LIMITED TO, DAMAGES
#  RELATED TO LOST REVENUE, LOST PROFITS, LOSS OF INCOME, LOSS OF
#  BUSINESS ADVANTAGE OR UNAVAILABILITY, OR LOSS OR CORRUPTION OF
#  DATA.

"""Unit Tests for CdeHook related operations"""

from __future__ import annotations

import os
import logging
import unittest
from concurrent.futures import Future
from json import JSONDecodeError
from unittest import mock

from cloudera.cdp.security.cde_security import CdeApiTokenAuth, CdeTokenAuthResponse
from requests import Session
from requests.exceptions import ConnectionError, HTTPError, Timeout
from retrying import RetryError  # type: ignore

from airflow.exceptions import AirflowException
from airflow.hooks.base_hook import BaseHook
from airflow.models import Connection
from airflow.configuration import conf

from cloudera.airflow.providers.hooks.cde import CdeHook, CdeHookException

from tests.providers.cloudera.utils import _get_call_arguments, _make_response

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.DEBUG)

TEST_HOST = "https://vc1.cde-2.cdp-3.cloudera.site"
TEST_SCHEME = "http"
TEST_PORT = 9090
TEST_JOB_NAME = "testjob"
TEST_JOB_RUN_ID = 10
TEST_JOB_RUN_STATUS = "active"
TEST_VARIABLES = {
    "var1": "someval_{{ ds_nodash }}",
    "ds": "2020-11-25",
    "ds_nodash": "20201125",
    "ts": "2020-11-25T00:00:00+00:00",
    "ts_nodash": "20201125T000000",
    "run_id": "runid",
}
TEST_OVERRIDES = {"spark": {"conf": {"myparam": "val_{{ ds_nodash }}"}}}
TEST_AK = "access_key"
TEST_PK = "private_key_xxxxx_xxxxx_xxxxx_xxxxx"
TEST_CUSTOM_CA_CERTIFICATE = "/ca_cert/letsencrypt-stg-root-x1.pem"
TEST_EXTRA = f'{{"ca_cert_path": "{TEST_CUSTOM_CA_CERTIFICATE}"}}'
GET_CDE_AUTH_TOKEN_METHOD = "cloudera.cdp.security.cde_security.CdeApiTokenAuth.get_cde_authentication_token"
GET_AIRFLOW_CONFIG = "airflow.providers.cloudera.hooks.cde_hook.conf"
INVALID_JSON_STRING = "{'invalid_json"


def _get_test_connection(**kwargs):
    kwargs = {**TEST_DEFAULT_CONNECTION_DICT, **kwargs}
    return Connection(**kwargs)


TEST_DEFAULT_CONNECTION_DICT = {
    "conn_id": CdeHook.DEFAULT_CONN_ID,
    "conn_type": "http",
    "host": TEST_HOST,
    "login": TEST_AK,
    "password": TEST_PK,
    "port": TEST_PORT,
    "schema": TEST_SCHEME,
    "extra": TEST_EXTRA,
}

TEST_DEFAULT_CONNECTION = _get_test_connection()

VALID_CDE_TOKEN = "my_cde_token"
VALID_CDE_TOKEN_AUTH_REQUEST_RESPONSE = _make_response(
    200, {"access_token": VALID_CDE_TOKEN, "expires_in": 123}, ""
)
VALID_CDE_TOKEN_AUTH_RESPONSE = CdeTokenAuthResponse.from_response(VALID_CDE_TOKEN_AUTH_REQUEST_RESPONSE)


class CdeHookTest(unittest.TestCase):
    """Unit tests for CdeHook"""

    @mock.patch.object(
        BaseHook, "get_connection", return_value=_get_test_connection(extra='{"insecure": False}')
    )
    def test_wrong_extra_in_connection(self, connection_mock):
        """Test when wrong input is provided in the extra field of the connection"""
        with self.assertRaises(ValueError):
            CdeHook()
        connection_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_ok(self, connection_mock, session_send_mock, cde_mock):
        """Test a successful submission to the API"""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=_get_test_connection(host="abc.svc"))
    def test_submit_job_ok_internal_connection(self, connection_mock, session_send_mock, cde_mock: mock.Mock):
        """Test a successful submission to the API"""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_not_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch.dict(os.environ, {"AIRFLOW__CDE__DEFAULT_API_TIMEOUT": "400"})
    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=_get_test_connection(host="abc.svc"))
    def test_submit_job_ok_internal_connection_set_timeout_by_env(self, connection_mock, session_send_mock, cde_mock: mock.Mock):
        """Test a successful submission to the API"""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_not_called()
        connection_mock.assert_called()
        session_send_mock.assert_called_with(mock.ANY,
                                             allow_redirects=mock.ANY,
                                             cert=mock.ANY,
                                             proxies=mock.ANY,
                                             stream=mock.ANY,
                                             timeout=400,
                                             verify=mock.ANY)

    @mock.patch.dict(os.environ, {"AIRFLOW__CDE__DEFAULT_API_TIMEOUT": "400asdf"})
    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=_get_test_connection(host="abc.svc"))
    def test_submit_job_failed_internal_connection_set_timeout_by_env(
        self, connection_mock, session_send_mock, cde_mock: mock.Mock
    ):
        """Test a wrong api timeout value via the AIRFLOW__CDE__DEFAULT_API_TIMEOUT
        environment variable, the default value should be used in this case."""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_not_called()
        connection_mock.assert_called()
        session_send_mock.assert_called_with(
            mock.ANY,
            allow_redirects=mock.ANY,
            cert=mock.ANY,
            proxies=mock.ANY,
            stream=mock.ANY,
            timeout=CdeHook.DEFAULT_API_TIMEOUT,
            verify=mock.ANY,
        )

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, None, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_empty_response_none_fail(
        self, connection_mock, session_send_mock, cde_mock: mock.Mock
    ):
        """Test a fail on empty response from CDE"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.submit_job(TEST_JOB_NAME)
        # Ensure that there is no previous exceptions in Exception stack
        self.assertFalse(hasattr(err.exception.raised_from, "raised_from"))
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, b"", ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_empty_response_bytes_fail(
        self, connection_mock, session_send_mock, cde_mock: mock.Mock
    ):
        """Test a fail on empty response from CDE"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.submit_job(TEST_JOB_NAME)
        # Ensure that there is no previous exceptions in Exception stack
        self.assertFalse(hasattr(err.exception.raised_from, "raised_from"))
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"wrong": "wrong"}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_invalid_key_fail(self, connection_mock, session_send_mock, cde_mock: mock.Mock):
        """Test a fail on incorrect response from CDE"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.submit_job(TEST_JOB_NAME)
        self.assertIsInstance(err.exception.raised_from, KeyError)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, INVALID_JSON_STRING, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_invalid_json_fail(self, connection_mock, session_send_mock, cde_mock: mock.Mock):
        """Test a fail on invalid JSON response from CDE"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.submit_job(TEST_JOB_NAME)
        self.assertIsInstance(err.exception.raised_from, JSONDecodeError)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch.object(
        CdeApiTokenAuth, "get_cde_authentication_token", return_value=VALID_CDE_TOKEN_AUTH_RESPONSE
    )
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    @mock.patch.object(
        Session,
        "send",
        side_effect=[
            _make_response(429, None, "Too Many Requests"),
            _make_response(429, None, "Too Many Requests"),
            _make_response(201, {"id": TEST_JOB_RUN_ID}, ""),
        ],
    )
    def test_submit_job_retry_after_429_works(self, send_mock, connection_mock, cde_mock):
        """Ensure that 429 errors are handled"""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        self.assertEqual(cde_mock.call_count, 1)
        self.assertEqual(send_mock.call_count, 3)
        connection_mock.assert_called()

    @mock.patch.object(
        CdeApiTokenAuth, "get_cde_authentication_token", return_value=VALID_CDE_TOKEN_AUTH_RESPONSE
    )
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    @mock.patch.object(
        Session,
        "send",
        side_effect=[
            _make_response(503, None, "Internal Server Error"),
            _make_response(500, None, "Internal Server Error"),
            _make_response(201, {"id": TEST_JOB_RUN_ID}, ""),
        ],
    )
    def test_submit_job_retry_after_5xx_works(self, send_mock, connection_mock, cde_mock):
        """Ensure that 5xx errors are retried"""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        self.assertEqual(cde_mock.call_count, 1)
        self.assertEqual(send_mock.call_count, 3)
        connection_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    @mock.patch.object(Session, "send", return_value=_make_response(404, None, "Not Found"))
    def test_submit_job_fails_immediately_for_4xx(self, send_mock, connection_mock, cde_mock):
        """Ensure that 4xx errors are _not_ retried"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(send_mock.call_count, 1)
        self.assertIsInstance(err.exception.raised_from, AirflowException)
        cde_mock.assert_called()
        connection_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    @mock.patch.object(
        Session,
        "send",
        side_effect=[
            _make_response(503, None, "Internal Server Error"),
            _make_response(409, {"id": TEST_JOB_RUN_ID}, ""),
        ],
    )
    def test_submit_job_retries_exit_after_409(self, send_mock, connection_mock, cde_mock):
        """Ensure that after 409 response hook exit the retries"""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        self.assertEqual(cde_mock.call_count, 1)
        self.assertEqual(send_mock.call_count, 2)
        connection_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""))
    @mock.patch.object(
        BaseHook, "get_connection", return_value=_get_test_connection(extra='{"insecure": true}')
    )
    def test_submit_job_insecure(self, connection_mock, session_send_mock, cde_mock):
        """Ensure insecure mode is taken into account"""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()
        called_args = _get_call_arguments(session_send_mock.call_args)
        self.assertEqual(called_args["verify"], False)

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=_get_test_connection(extra="{}"))
    def test_submit_job_no_custom_ca_certificate(self, connection_mock, session_send_mock, cde_mock):
        """Ensure that default TLS security configuration runs fine"""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()
        called_args = _get_call_arguments(session_send_mock.call_args)
        self.assertEqual(called_args["verify"], True)

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_custom_ca_certificate(self, connection_mock, session_send_mock, cde_mock):
        """Ensure custom is taken into account"""
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()
        called_args = _get_call_arguments(session_send_mock.call_args)
        self.assertEqual(called_args["verify"], TEST_CUSTOM_CA_CERTIFICATE)

    @mock.patch.object(
        BaseHook, "get_connection", return_value=_get_test_connection(extra='{"cache_dir": " "}')
    )
    def test_wrong_cache_dir(self, connection_mock):
        """Ensure that CdeHook object creation fails if cache dir value is wrong"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException):
            cde_hook.submit_job(TEST_JOB_NAME)
        connection_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_custom_timeout_success(self, connection_mock, session_send_mock, cde_mock):
        """Ensure custom timeout is taken into account
        and succeeds as expected if the request does not timeout."""

        # Regular test - request completes below timeout
        cde_hook = CdeHook(api_timeout=10)
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch.dict(os.environ, {"AIRFLOW__CDE__DEFAULT_API_TIMEOUT": "10"})
    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_custom_env_timeout_success(self, connection_mock, session_send_mock, cde_mock):
        """Ensure custom timeout from the env var is taken into account
        and succeeds as expected if the request does not timeout."""

        # Regular test - request completes below timeout
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", side_effect=Timeout())
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_custom_timeout_failure(self, connection_mock, session_send_mock: mock.Mock, cde_mock):
        """Ensure custom timeout is taken into account and fails as expected if request keeps timing out."""
        # Request times out
        cde_hook = CdeHook(api_timeout=3, num_retries=0)
        with self.assertRaises(CdeHookException) as err:
            cde_hook.submit_job(TEST_JOB_NAME)

        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

        retry_error: RetryError = err.exception.raised_from
        last_attempt: Future = retry_error.last_attempt
        self.assertIsInstance(last_attempt.exception(), Timeout)

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(
        Session,
        "send",
        return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""),
        side_effect=[
            ConnectionError(),
            ConnectionError(),
            # Returns what is specified in return_value
            mock.DEFAULT,
        ],
    )
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_custom_api_retries_success(self, connection_mock, session_send_mock, cde_mock):
        """Ensure custom api_retries is taken into account and succeeds as expected.

        Set retry number to 4 times but the third call will be successful so it will succeed.
        """
        cde_hook = CdeHook(num_retries=4)
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_called()
        connection_mock.assert_called()
        self.assertEqual(session_send_mock.call_count, 3)

    @mock.patch.dict(os.environ, {"AIRFLOW__CDE__DEFAULT_NUM_RETRIES": "4"})
    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(
        Session,
        "send",
        return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""),
        side_effect=[
            ConnectionError(),
            ConnectionError(),
            # Returns what is specified in return_value
            mock.DEFAULT,
        ],
    )
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_custom_env_api_retries_success(self, connection_mock, session_send_mock, cde_mock):
        """Ensure custom api_retries is taken into account from the env var and succeeds as expected.

        Set retry number to 4 times but the third call will be successful so it will succeed.
        """
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_called()
        connection_mock.assert_called()
        self.assertEqual(session_send_mock.call_count, 3)

    @mock.patch.dict(os.environ, {"AIRFLOW__CDE__DEFAULT_NUM_RETRIES": "4asdf"})
    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(
        Session,
        "send",
        return_value=_make_response(201, {"id": TEST_JOB_RUN_ID}, ""),
        side_effect=[
            ConnectionError(),
            ConnectionError(),
            ConnectionError(),
            ConnectionError(),
            ConnectionError(),
            ConnectionError(),
            ConnectionError(),
            ConnectionError(),
            # Returns what is specified in return_value
            mock.DEFAULT,
        ],
    )
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_custom_env_api_retries_success(self, connection_mock, session_send_mock, cde_mock):
        """The default num retries value should be used if a wrong value is set via the
        AIRFLOW__CDE_DEFAULT_NUM_RETRIES environment variable.
        The call will succeed for the 9th call which is the CdeHook.DEFAULT_NUM_RETRIES value.
        """
        cde_hook = CdeHook()
        run_id = cde_hook.submit_job(TEST_JOB_NAME)
        self.assertEqual(run_id, TEST_JOB_RUN_ID)
        cde_mock.assert_called()
        connection_mock.assert_called()
        self.assertEqual(session_send_mock.call_count, CdeHook.DEFAULT_NUM_RETRIES)

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", side_effect=ConnectionError())
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_custom_api_retries_failure(self, connection_mock, session_send_mock, cde_mock):
        """Ensure custom api_retries is taken into account and fails as expected.

        The request keeps failing so the job sumbission will end up in failure after exhausiting the
        number of retries.
        """
        cde_hook = CdeHook(num_retries=3)
        with self.assertRaises(CdeHookException) as err:
            cde_hook.submit_job(TEST_JOB_NAME)

        cde_mock.assert_called()
        connection_mock.assert_called()
        self.assertEqual(session_send_mock.call_count, 3)

        retry_error: RetryError = err.exception.raised_from
        last_attempt: Future = retry_error.last_attempt
        self.assertIsInstance(last_attempt.exception(), ConnectionError)

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", side_effect=HTTPError())
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_submit_job_non_always_retry_exception(self, connection_mock, session_send_mock, cde_mock):
        """Ensure no retry is attempted if the request exception
        is not part of the ALWAYS_RETRY_EXCEPTIONS list"""

        # Request times out
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.submit_job(TEST_JOB_NAME)

        cde_mock.assert_called()
        connection_mock.assert_called()
        # Only called once because never retried
        (session_send_mock.call_count, 1)

        self.assertIsInstance(err.exception.raised_from, HTTPError)

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, None, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_kill_job_empty_response_none(self, connection_mock, session_send_mock, cde_mock):
        """Test request of job run deletion from CDE API"""
        cde_hook = CdeHook()
        cde_hook.kill_job_run(TEST_JOB_NAME)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, b"", ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_kill_job_empty_response_bytes(self, connection_mock, session_send_mock, cde_mock):
        """Test request of job run deletion from CDE API"""
        cde_hook = CdeHook()
        cde_hook.kill_job_run(TEST_JOB_NAME)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch.dict(os.environ, {"AIRFLOW__CDE__DEFAULT_API_TIMEOUT": "400"})
    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, b"", ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_kill_job_empty_response_bytes_timeout(self, connection_mock, session_send_mock, cde_mock):
        """Test request of job run deletion from CDE API with modified timeout value"""
        cde_hook = CdeHook()
        cde_hook.kill_job_run(TEST_JOB_NAME)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called_with(mock.ANY,
                                             allow_redirects=mock.ANY,
                                             cert=mock.ANY,
                                             proxies=mock.ANY,
                                             stream=mock.ANY,
                                             timeout=400,
                                             verify=mock.ANY)

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, INVALID_JSON_STRING, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_kill_job_invalid_json(self, connection_mock, session_send_mock, cde_mock):
        """Test invalid JSON response on job run deletion from CDE API"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.kill_job_run(TEST_JOB_NAME)
        self.assertIsInstance(err.exception.raised_from, JSONDecodeError)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"status": TEST_JOB_RUN_STATUS}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_check_job_run_status(self, connection_mock, session_send_mock, cde_mock):
        """Test a successful request of job run status from CDE API"""
        cde_hook = CdeHook()
        status = cde_hook.check_job_run_status(TEST_JOB_RUN_ID)
        self.assertEqual(status, TEST_JOB_RUN_STATUS)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"status": TEST_JOB_RUN_STATUS}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_check_job_run_status_timeout(self, connection_mock, session_send_mock, cde_mock):
        """Test a successful request of job run status from CDE API"""
        cde_hook = CdeHook()
        status = cde_hook.check_job_run_status(TEST_JOB_RUN_ID)
        self.assertEqual(status, TEST_JOB_RUN_STATUS)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called_with(mock.ANY,
                                             allow_redirects=True,
                                             cert=None,
                                             proxies=mock.ANY,
                                             stream=False,
                                             timeout=CdeHook.DEFAULT_API_TIMEOUT // 10,
                                             verify='/ca_cert/letsencrypt-stg-root-x1.pem')

    @mock.patch.dict(os.environ, {"AIRFLOW__CDE__DEFAULT_API_TIMEOUT": "450"})
    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"status": TEST_JOB_RUN_STATUS}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_check_job_run_status_timeout(self, connection_mock, session_send_mock, cde_mock):
        """Test the used minimal timeout value for job status call"""
        cde_hook = CdeHook()
        status = cde_hook.check_job_run_status(TEST_JOB_RUN_ID)
        self.assertEqual(status, TEST_JOB_RUN_STATUS)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called_with(mock.ANY,
                                             allow_redirects=mock.ANY,
                                             cert=mock.ANY,
                                             proxies=mock.ANY,
                                             stream=mock.ANY,
                                             timeout=450 // 10,
                                             verify=mock.ANY)

    @mock.patch.dict(os.environ, {"AIRFLOW__CDE__DEFAULT_API_TIMEOUT": "10"})
    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"status": TEST_JOB_RUN_STATUS}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_check_job_run_status_less_default_timeout_env(self, connection_mock, session_send_mock, cde_mock):
        """Test the default minimal timeout value for job status even if a
        lower value was set by the env var."""
        cde_hook = CdeHook()
        status = cde_hook.check_job_run_status(TEST_JOB_RUN_ID)
        self.assertEqual(status, TEST_JOB_RUN_STATUS)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called_with(mock.ANY,
                                             allow_redirects=mock.ANY,
                                             cert=mock.ANY,
                                             proxies=mock.ANY,
                                             stream=mock.ANY,
                                             timeout=CdeHook.DEFAULT_API_TIMEOUT // 10,
                                             verify=mock.ANY)

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"status": TEST_JOB_RUN_STATUS}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_check_job_run_status_less_default_timeout_init(self, connection_mock, session_send_mock, cde_mock):
        """Test the default minimal timeout value for job status even if a
        lower value was set by a parameter."""
        cde_hook = CdeHook(api_timeout=10)
        status = cde_hook.check_job_run_status(TEST_JOB_RUN_ID)
        self.assertEqual(status, TEST_JOB_RUN_STATUS)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called_with(mock.ANY,
                                             allow_redirects=mock.ANY,
                                             cert=mock.ANY,
                                             proxies=mock.ANY,
                                             stream=mock.ANY,
                                             timeout=CdeHook.DEFAULT_API_TIMEOUT // 10,
                                             verify=mock.ANY)

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, None, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_check_job_run_status_empty_response_none(self, connection_mock, session_send_mock, cde_mock):
        """Test a fail on empty None response from CDE API"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.check_job_run_status(TEST_JOB_RUN_ID)
        # Ensure that there is no previous exceptions in Exception stack
        self.assertFalse(hasattr(err.exception.raised_from, "raised_from"))
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, b"", ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_check_job_run_status_empty_response_bytes(self, connection_mock, session_send_mock, cde_mock):
        """Test a fail on empty bytes() response from CDE API"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.check_job_run_status(TEST_JOB_RUN_ID)
        # Ensure that there is no previous exceptions in Exception stack
        self.assertFalse(hasattr(err.exception.raised_from, "raised_from"))
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, {"wrong": "wrong"}, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_check_job_run_status_invalid_key(self, connection_mock, session_send_mock, cde_mock):
        """Test a fail on incorrect response from CDE API"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.check_job_run_status(TEST_JOB_RUN_ID)
        self.assertIsInstance(err.exception.raised_from, KeyError)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()

    @mock.patch(GET_CDE_AUTH_TOKEN_METHOD, return_value=VALID_CDE_TOKEN_AUTH_RESPONSE)
    @mock.patch.object(Session, "send", return_value=_make_response(201, INVALID_JSON_STRING, ""))
    @mock.patch.object(BaseHook, "get_connection", return_value=TEST_DEFAULT_CONNECTION)
    def test_check_job_run_status_invalid_json(self, connection_mock, session_send_mock, cde_mock):
        """Test a fail on response with invalid JSON from CDE API"""
        cde_hook = CdeHook()
        with self.assertRaises(CdeHookException) as err:
            cde_hook.check_job_run_status(TEST_JOB_RUN_ID)
        self.assertIsInstance(err.exception.raised_from, JSONDecodeError)
        cde_mock.assert_called()
        connection_mock.assert_called()
        session_send_mock.assert_called()


if __name__ == "__main__":
    unittest.main()
