# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Security utility functions with comprehensive logging.

Centralises security-critical helper logic that is used across the Superset
backend.  Every function includes structured logging so that access checks,
ownership validations, and input-sanitisation decisions leave an auditable
trail in the application log.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

from flask import request

logger = logging.getLogger(__name__)

# Default set of dictionary keys whose values are masked before logging.
_DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "access_token",
        "refresh_token",
        "private_key",
        "credentials",
    }
)


def check_csrf_token() -> bool:
    """Validate the CSRF token on the current Flask request.

    Reads the token from the ``X-CSRFToken`` header (or ``X-CSRF-Token``) and
    compares it against the value stored in the session.  The check is skipped
    for requests that do not mutate state (``GET``, ``HEAD``, ``OPTIONS``).

    :return: ``True`` when the token is valid or the method is safe,
             ``False`` otherwise.
    """
    safe_methods = {"GET", "HEAD", "OPTIONS"}
    if request.method in safe_methods:
        logger.debug("CSRF check skipped for safe method %s", request.method)
        return True

    session_token: Optional[str] = None
    try:
        # Flask-WTF stores the CSRF token under ``csrf_token`` in the session.
        from flask import session  # pylint: disable=import-outside-toplevel

        session_token = session.get("csrf_token")
    except RuntimeError:
        logger.warning("CSRF check failed: no active session context")
        return False

    request_token = request.headers.get("X-CSRFToken") or request.headers.get(
        "X-CSRF-Token"
    )

    if not session_token or not request_token:
        logger.warning(
            "CSRF token missing — session_present=%s, header_present=%s, "
            "method=%s, path=%s",
            session_token is not None,
            request_token is not None,
            request.method,
            request.path,
        )
        return False

    from hmac import compare_digest  # pylint: disable=import-outside-toplevel

    valid = compare_digest(session_token, request_token)
    if not valid:
        logger.warning(
            "CSRF token mismatch for method=%s path=%s",
            request.method,
            request.path,
        )
    else:
        logger.debug(
            "CSRF token validated for method=%s path=%s",
            request.method,
            request.path,
        )
    return valid


def validate_user_perms(permission_name: str, view_name: str) -> bool:
    """Check whether the current user holds a FAB permission, with logging.

    Delegates to ``security_manager.can_access`` and logs the outcome so that
    permission checks appear in the audit trail.

    :param permission_name: The FAB permission name (e.g. ``datasource_access``)
    :param view_name: The FAB view-menu name
    :return: ``True`` if the user has the permission, ``False`` otherwise
    """
    from superset import (  # pylint: disable=import-outside-toplevel
        security_manager,
    )
    from superset.utils.core import (  # pylint: disable=import-outside-toplevel
        get_user_id,
        get_username,
    )

    user_id = get_user_id()
    username = get_username()
    has_perm = security_manager.can_access(permission_name, view_name)

    if has_perm:
        logger.debug(
            "Permission granted: user=%s (id=%s) permission=%s view=%s",
            username,
            user_id,
            permission_name,
            view_name,
        )
    else:
        logger.info(
            "Permission denied: user=%s (id=%s) permission=%s view=%s",
            username,
            user_id,
            permission_name,
            view_name,
        )
    return has_perm


def check_ownership(resource: Any) -> bool:
    """Check whether the current user owns the given resource, with logging.

    Delegates to ``security_manager.is_owner`` and logs the outcome.  Admin
    users are treated as owners of every resource.

    :param resource: A SQLAlchemy model instance with an ``owners`` attribute
    :return: ``True`` if the current user owns the resource
    """
    from superset import (  # pylint: disable=import-outside-toplevel
        security_manager,
    )
    from superset.utils.core import (  # pylint: disable=import-outside-toplevel
        get_user_id,
        get_username,
    )

    user_id = get_user_id()
    username = get_username()
    resource_type = type(resource).__name__
    resource_id = getattr(resource, "id", None)

    is_owner = security_manager.is_owner(resource)

    if is_owner:
        logger.debug(
            "Ownership confirmed: user=%s (id=%s) resource=%s (id=%s)",
            username,
            user_id,
            resource_type,
            resource_id,
        )
    else:
        logger.info(
            "Ownership denied: user=%s (id=%s) resource=%s (id=%s)",
            username,
            user_id,
            resource_type,
            resource_id,
        )
    return is_owner


def get_safe_redirect_url(
    url: str,
    allowed_hosts: set[str] | None = None,
) -> str:
    """Validate a redirect URL and return it only if it is safe.

    A URL is considered safe when it is a relative path or its host is in
    ``allowed_hosts``.  Dangerous schemes (``javascript:``, ``data:``, etc.)
    are always blocked.  If the URL fails validation an empty string is
    returned and a warning is logged.

    :param url: The candidate redirect URL
    :param allowed_hosts: Optional set of trusted host names.  When *None*,
        the ``SERVER_NAME`` from the current Flask app config is used.
    :return: The original URL if safe, otherwise ``""``
    """
    if not url or not url.strip():
        logger.debug("Empty redirect URL provided")
        return ""

    url = url.strip()

    # Relative URLs are safe.
    if url.startswith("/") and not url.startswith("//"):
        logger.debug("Redirect URL accepted (relative): %s", url)
        return url

    try:
        parsed = urlparse(url)
    except ValueError:
        logger.warning("Malformed redirect URL blocked: %s", url)
        return ""

    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        logger.warning(
            "Redirect URL blocked (dangerous scheme=%s): %s",
            parsed.scheme,
            url,
        )
        return ""

    if allowed_hosts is None:
        from flask import (  # pylint: disable=import-outside-toplevel
            current_app,
        )

        server_name = current_app.config.get("SERVER_NAME")
        allowed_hosts = {server_name} if server_name else set()

    if parsed.netloc and parsed.netloc not in allowed_hosts:
        logger.warning(
            "Redirect URL blocked (host=%s not in allowed_hosts): %s",
            parsed.netloc,
            url,
        )
        return ""

    logger.debug("Redirect URL accepted: %s", url)
    return url


def log_failed_access(
    resource_type: str,
    resource_id: Any,
    action: str,
) -> None:
    """Log a failed access attempt with contextual user information.

    Intended to be called from access-check call sites that want a
    standardised audit record without raising an exception.

    :param resource_type: Human-readable resource kind (e.g. ``"dashboard"``)
    :param resource_id: Identifier of the resource
    :param action: The action that was denied (e.g. ``"read"``, ``"write"``)
    """
    from superset.utils.core import (  # pylint: disable=import-outside-toplevel
        get_user_id,
        get_username,
    )

    user_id = get_user_id()
    username = get_username()

    logger.warning(
        "Access denied: user=%s (id=%s) action=%s resource_type=%s resource_id=%s",
        username,
        user_id,
        action,
        resource_type,
        resource_id,
    )


def mask_sensitive_data(
    data: dict[str, Any],
    sensitive_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Return a shallow copy of *data* with sensitive values replaced by ``"***"``.

    Keys are matched case-insensitively.  The default set of sensitive keys
    covers common credential field names; callers may supply their own.

    :param data: The dictionary to sanitise
    :param sensitive_keys: Optional override for the set of keys to mask
    :return: A new dictionary safe for logging
    """
    if sensitive_keys is None:
        keys_to_mask: frozenset[str] | set[str] = _DEFAULT_SENSITIVE_KEYS
    else:
        keys_to_mask = {k.lower() for k in sensitive_keys}

    masked: dict[str, Any] = {}
    masked_count = 0
    for key, value in data.items():
        if key.lower() in keys_to_mask:
            masked[key] = "***"
            masked_count += 1
        else:
            masked[key] = value

    if masked_count:
        logger.debug(
            "Masked %d sensitive field(s) before logging: %s",
            masked_count,
            ", ".join(k for k in data if k.lower() in keys_to_mask),
        )
    return masked
