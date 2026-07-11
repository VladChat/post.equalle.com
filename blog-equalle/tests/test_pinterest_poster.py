# ============================================
# File: blog-equalle/tests/test_pinterest_poster.py
# Purpose: Unit tests for Pinterest publishing authentication
# ============================================

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from social import pinterest_poster  # noqa: E402


def _response(status_code=200, json_body=None, text="", ok=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.ok = ok if ok is not None else (200 <= status_code < 300)
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


class PinterestAuthTests(unittest.TestCase):
    def _patch_env(self, env):
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_refresh_token_is_used_for_create_pin(self):
        """Create Pin must use the OAuth access token from the refresh flow."""
        self._patch_env(
            {
                "PINTEREST_CLIENT_ID_EQUALLE": "cid",
                "PINTEREST_CLIENT_SECRET_EQUALLE": "csecret",
                "PINTEREST_REFRESH_TOKEN_EQUALLE": "rtoken",
            }
        )

        token_resp = _response(json_body={"access_token": "oauth-access"})
        pin_resp = _response(json_body={"id": "pin-123"})

        with mock.patch.object(
            pinterest_poster.requests, "post", side_effect=[token_resp, pin_resp]
        ) as post:
            pin_id = pinterest_poster.publish_pinterest_pin(
                {"title": "t", "description": "d"}, board_id="board-1"
            )

        self.assertEqual(pin_id, "pin-123")
        self.assertEqual(post.call_count, 2)

        token_call, pin_call = post.call_args_list
        self.assertEqual(token_call.args[0], pinterest_poster.PINTEREST_OAUTH_TOKEN_URL)
        self.assertEqual(token_call.kwargs["data"]["grant_type"], "refresh_token")
        self.assertEqual(token_call.kwargs["data"]["refresh_token"], "rtoken")
        self.assertEqual(
            pin_call.kwargs["headers"]["Authorization"], "Bearer oauth-access"
        )
        self.assertEqual(pin_call.kwargs["json"]["board_id"], "board-1")

    def test_rotated_refresh_token_is_handed_off_safely(self):
        """A rotated refresh token must reach the handoff file and never stdout."""
        handoff = os.path.join(tempfile.mkdtemp(), "rotated")
        self._patch_env(
            {
                "PINTEREST_CLIENT_ID_EQUALLE": "cid",
                "PINTEREST_CLIENT_SECRET_EQUALLE": "csecret",
                "PINTEREST_REFRESH_TOKEN_EQUALLE": "old-rtoken",
                "PINTEREST_ROTATED_REFRESH_TOKEN_FILE": handoff,
            }
        )

        token_resp = _response(
            json_body={"access_token": "oauth-access", "refresh_token": "new-rtoken"}
        )

        captured = io.StringIO()
        with mock.patch.object(
            pinterest_poster.requests, "post", return_value=token_resp
        ):
            with contextlib.redirect_stdout(captured):
                token = pinterest_poster._refresh_access_token()

        self.assertEqual(token, "oauth-access")
        with open(handoff, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "new-rtoken")
        self.assertNotIn("new-rtoken", captured.getvalue())
        self.assertNotIn("old-rtoken", captured.getvalue())

    def test_auth_failure_does_not_leak_credentials(self):
        """Failed refresh must raise without exposing any configured secret."""
        self._patch_env(
            {
                "PINTEREST_CLIENT_ID_EQUALLE": "cid-value",
                "PINTEREST_CLIENT_SECRET_EQUALLE": "csecret-value",
                "PINTEREST_REFRESH_TOKEN_EQUALLE": "rtoken-value",
            }
        )

        failure = _response(
            status_code=401,
            text='{"code":28,"message":"Refresh token is expired."}',
        )

        with mock.patch.object(pinterest_poster.requests, "post", return_value=failure):
            with self.assertRaises(pinterest_poster.PinterestConfigError) as ctx:
                pinterest_poster._get_access_token()

        message = str(ctx.exception)
        for secret in ("cid-value", "csecret-value", "rtoken-value"):
            self.assertNotIn(secret, message)
        self.assertIn("401", message)

    def test_static_dashboard_token_is_not_a_publishing_credential(self):
        """Read-only dashboard tokens must be rejected, not silently used."""
        self._patch_env({"PINTEREST_ACCESS_TOKEN": "static-read-only-token"})

        with mock.patch.object(pinterest_poster.requests, "post") as post:
            with self.assertRaises(pinterest_poster.PinterestConfigError) as ctx:
                pinterest_poster._get_access_token()

        post.assert_not_called()
        self.assertNotIn("static-read-only-token", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
