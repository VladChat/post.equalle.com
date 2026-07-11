# ============================================
# File: blog-equalle/tests/test_pinterest_poster.py
# Purpose: Unit tests for Pinterest token resolution
# ============================================

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from social import pinterest_poster  # noqa: E402


def _response(status_code=200, json_body=None, text=""):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


class GetAccessTokenTests(unittest.TestCase):
    def _patch_env(self, env):
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unattended_uses_client_credentials_with_required_scopes(self):
        """Without a refresh token, the scheduled job must use client_credentials."""
        self._patch_env(
            {
                "PINTEREST_CLIENT_ID_EQUALLE": "cid",
                "PINTEREST_CLIENT_SECRET_EQUALLE": "csecret",
            }
        )

        with mock.patch.object(
            pinterest_poster.requests,
            "post",
            return_value=_response(json_body={"access_token": "cc-token"}),
        ) as post:
            token = pinterest_poster._get_access_token()

        self.assertEqual(token, "cc-token")
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], pinterest_poster.PINTEREST_OAUTH_TOKEN_URL)
        self.assertEqual(kwargs["data"]["grant_type"], "client_credentials")
        self.assertEqual(
            kwargs["data"]["scope"],
            "boards:read,boards:write,pins:read,pins:write",
        )

    def test_refresh_flow_preferred_when_refresh_token_configured(self):
        """An explicitly configured refresh token keeps the refresh flow first."""
        self._patch_env(
            {
                "PINTEREST_CLIENT_ID_EQUALLE": "cid",
                "PINTEREST_CLIENT_SECRET_EQUALLE": "csecret",
                "PINTEREST_REFRESH_TOKEN_EQUALLE": "rtoken",
            }
        )

        with mock.patch.object(
            pinterest_poster.requests,
            "post",
            return_value=_response(json_body={"access_token": "refresh-token-result"}),
        ) as post:
            token = pinterest_poster._get_access_token()

        self.assertEqual(token, "refresh-token-result")
        post.assert_called_once()
        _, kwargs = post.call_args
        self.assertEqual(kwargs["data"]["grant_type"], "refresh_token")
        self.assertEqual(kwargs["data"]["refresh_token"], "rtoken")

    def test_static_token_used_when_both_oauth_flows_fail(self):
        """Expired refresh token and failing client_credentials fall back to the static token."""
        self._patch_env(
            {
                "PINTEREST_CLIENT_ID_EQUALLE": "cid",
                "PINTEREST_CLIENT_SECRET_EQUALLE": "csecret",
                "PINTEREST_REFRESH_TOKEN_EQUALLE": "expired-rtoken",
                "PINTEREST_ACCESS_TOKEN": "static-token",
            }
        )

        failure = _response(
            status_code=401,
            text='{"code":28,"message":"Refresh token is expired."}',
        )

        with mock.patch.object(
            pinterest_poster.requests, "post", return_value=failure
        ) as post:
            token = pinterest_poster._get_access_token()

        self.assertEqual(token, "static-token")
        self.assertEqual(post.call_count, 2)
        grant_types = [call.kwargs["data"]["grant_type"] for call in post.call_args_list]
        self.assertEqual(grant_types, ["refresh_token", "client_credentials"])


if __name__ == "__main__":
    unittest.main()
