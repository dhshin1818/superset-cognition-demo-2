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

# pylint: disable=import-outside-toplevel, unused-argument

from datetime import datetime

from flask_caching.backends import NullCache
from pytest_mock import MockerFixture
from werkzeug.wrappers import Response

from superset.app import SupersetApp
from superset.constants import CACHE_DISABLED_TIMEOUT

# ---------------------------------------------------------------------------
# generate_cache_key
# ---------------------------------------------------------------------------


def test_generate_cache_key_returns_hash(app_context: None) -> None:
    """generate_cache_key produces a deterministic hash string."""
    from superset.utils.cache import generate_cache_key

    key = generate_cache_key({"a": 1, "b": 2})
    assert isinstance(key, str)
    assert len(key) > 0


def test_generate_cache_key_deterministic(app_context: None) -> None:
    """Same input dict always yields the same cache key."""
    from superset.utils.cache import generate_cache_key

    key1 = generate_cache_key({"x": 10, "y": 20})
    key2 = generate_cache_key({"x": 10, "y": 20})
    assert key1 == key2


def test_generate_cache_key_different_inputs(app_context: None) -> None:
    """Different input dicts yield different cache keys."""
    from superset.utils.cache import generate_cache_key

    key1 = generate_cache_key({"x": 1})
    key2 = generate_cache_key({"x": 2})
    assert key1 != key2


def test_generate_cache_key_with_prefix(app_context: None) -> None:
    """Key prefix is prepended to the hash."""
    from superset.utils.cache import generate_cache_key

    key_no_prefix = generate_cache_key({"a": 1})
    key_with_prefix = generate_cache_key({"a": 1}, key_prefix="prefix_")
    assert key_with_prefix.startswith("prefix_")
    assert key_with_prefix == f"prefix_{key_no_prefix}"


def test_generate_cache_key_empty_dict(app_context: None) -> None:
    """An empty dict still produces a valid cache key."""
    from superset.utils.cache import generate_cache_key

    key = generate_cache_key({})
    assert isinstance(key, str)
    assert len(key) > 0


# ---------------------------------------------------------------------------
# set_and_log_cache
# ---------------------------------------------------------------------------


def test_set_and_log_cache_null_cache(mocker: MockerFixture, app_context: None) -> None:
    """NullCache backend causes an early return without setting."""
    from superset.utils.cache import set_and_log_cache

    cache_instance = mocker.MagicMock()
    cache_instance.cache = NullCache()

    set_and_log_cache(cache_instance, "key", {"data": 1})
    cache_instance.set.assert_not_called()


def test_set_and_log_cache_disabled_timeout(
    mocker: MockerFixture, app_context: None
) -> None:
    """CACHE_DISABLED_TIMEOUT skips caching."""
    from superset.utils.cache import set_and_log_cache

    cache_instance = mocker.MagicMock()
    cache_instance.cache = mocker.MagicMock()  # not a NullCache

    set_and_log_cache(
        cache_instance, "key", {"data": 1}, cache_timeout=CACHE_DISABLED_TIMEOUT
    )
    cache_instance.set.assert_not_called()


def test_set_and_log_cache_sets_value_with_dttm(
    mocker: MockerFixture, app_context: None
) -> None:
    """Cache value is augmented with a ``dttm`` field and stored."""
    from superset.utils.cache import set_and_log_cache

    cache_instance = mocker.MagicMock()
    cache_instance.cache = mocker.MagicMock()

    stats_logger = mocker.MagicMock()
    mocker.patch(
        "superset.utils.cache.app.config",
        {
            "CACHE_DEFAULT_TIMEOUT": 300,
            "STATS_LOGGER": stats_logger,
            "STORE_CACHE_KEYS_IN_METADATA_DB": False,
        },
    )

    set_and_log_cache(cache_instance, "test_key", {"data": 42}, cache_timeout=60)

    cache_instance.set.assert_called_once()
    call_args = cache_instance.set.call_args
    stored_key = call_args[0][0]
    stored_value = call_args[0][1]
    assert stored_key == "test_key"
    assert stored_value["data"] == 42
    assert "dttm" in stored_value
    assert call_args[1]["timeout"] == 60
    stats_logger.incr.assert_called_once_with("set_cache_key")


def test_set_and_log_cache_uses_default_timeout(
    mocker: MockerFixture, app_context: None
) -> None:
    """When no cache_timeout is given, the default config value is used."""
    from superset.utils.cache import set_and_log_cache

    cache_instance = mocker.MagicMock()
    cache_instance.cache = mocker.MagicMock()

    stats_logger = mocker.MagicMock()
    mocker.patch(
        "superset.utils.cache.app.config",
        {
            "CACHE_DEFAULT_TIMEOUT": 999,
            "STATS_LOGGER": stats_logger,
            "STORE_CACHE_KEYS_IN_METADATA_DB": False,
        },
    )

    set_and_log_cache(cache_instance, "key", {"v": 1})

    call_args = cache_instance.set.call_args
    assert call_args[1]["timeout"] == 999


def test_set_and_log_cache_stores_metadata(
    mocker: MockerFixture, app_context: None
) -> None:
    """When STORE_CACHE_KEYS_IN_METADATA_DB is True and datasource_uid is given,
    a CacheKey record is added to the session."""
    from superset.utils.cache import set_and_log_cache

    cache_instance = mocker.MagicMock()
    cache_instance.cache = mocker.MagicMock()

    stats_logger = mocker.MagicMock()
    mocker.patch(
        "superset.utils.cache.app.config",
        {
            "CACHE_DEFAULT_TIMEOUT": 300,
            "STATS_LOGGER": stats_logger,
            "STORE_CACHE_KEYS_IN_METADATA_DB": True,
        },
    )
    mock_session = mocker.patch("superset.utils.cache.db.session")

    set_and_log_cache(
        cache_instance, "key", {"v": 1}, cache_timeout=60, datasource_uid="ds_1"
    )

    mock_session.add.assert_called_once()
    cache_key_obj = mock_session.add.call_args[0][0]
    assert cache_key_obj.cache_key == "key"
    assert cache_key_obj.datasource_uid == "ds_1"
    assert cache_key_obj.cache_timeout == 60


def test_set_and_log_cache_no_metadata_without_datasource_uid(
    mocker: MockerFixture, app_context: None
) -> None:
    """No CacheKey record is created when datasource_uid is None."""
    from superset.utils.cache import set_and_log_cache

    cache_instance = mocker.MagicMock()
    cache_instance.cache = mocker.MagicMock()

    stats_logger = mocker.MagicMock()
    mocker.patch(
        "superset.utils.cache.app.config",
        {
            "CACHE_DEFAULT_TIMEOUT": 300,
            "STATS_LOGGER": stats_logger,
            "STORE_CACHE_KEYS_IN_METADATA_DB": True,
        },
    )
    mock_session = mocker.patch("superset.utils.cache.db.session")

    set_and_log_cache(cache_instance, "key", {"v": 1}, cache_timeout=60)

    mock_session.add.assert_not_called()


def test_set_and_log_cache_handles_exception(
    mocker: MockerFixture, app_context: None
) -> None:
    """Exceptions during cache.set are caught and logged."""
    from superset.utils.cache import set_and_log_cache

    cache_instance = mocker.MagicMock()
    cache_instance.cache = mocker.MagicMock()
    cache_instance.set.side_effect = Exception("backend down")

    stats_logger = mocker.MagicMock()
    mocker.patch(
        "superset.utils.cache.app.config",
        {
            "CACHE_DEFAULT_TIMEOUT": 300,
            "STATS_LOGGER": stats_logger,
            "STORE_CACHE_KEYS_IN_METADATA_DB": False,
        },
    )
    mock_logger = mocker.patch("superset.utils.cache.logger")

    set_and_log_cache(cache_instance, "key", {"v": 1}, cache_timeout=60)

    mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# memoized_func
# ---------------------------------------------------------------------------


def test_memoized_func(mocker: MockerFixture) -> None:
    """
    Test the ``memoized_func`` decorator.
    """
    from superset.utils.cache import memoized_func

    cache = mocker.MagicMock()

    decorator = memoized_func("db:{self.id}:schema:{schema}:view_list", cache)
    decorated = decorator(lambda self, schema, cache=False: 42)

    self = mocker.MagicMock()
    self.id = 1

    # skip cache
    result = decorated(self, "public", cache=False)
    assert result == 42
    cache.get.assert_not_called()

    # check cache, no cached value
    cache.get.return_value = None
    result = decorated(self, "public", cache=True)
    assert result == 42
    cache.get.assert_called_with("db:1:schema:public:view_list")

    # check cache, cached value
    cache.get.return_value = 43
    result = decorated(self, "public", cache=True)
    assert result == 43


def test_memoized_func_force_refresh(mocker: MockerFixture) -> None:
    """force=True bypasses the cached value and recomputes."""
    from superset.utils.cache import memoized_func

    cache = mocker.MagicMock()
    decorator = memoized_func("{a}+{b}", cache)
    decorated = decorator(lambda a, b: a + b)

    cache.get.return_value = 999  # stale cached value
    result = decorated(1, 2, cache=True, force=True)
    assert result == 3
    cache.set.assert_called()


def test_memoized_func_disabled_timeout_skips_set(mocker: MockerFixture) -> None:
    """CACHE_DISABLED_TIMEOUT prevents cache.set from being called."""
    from superset.utils.cache import memoized_func

    cache = mocker.MagicMock()
    cache.get.return_value = None

    decorator = memoized_func("{a}", cache)
    decorated = decorator(lambda a: a * 2)

    result = decorated(5, cache=True, cache_timeout=CACHE_DISABLED_TIMEOUT)
    assert result == 10
    cache.set.assert_not_called()


def test_memoized_func_sets_with_custom_timeout(mocker: MockerFixture) -> None:
    """A custom cache_timeout is forwarded to cache.set."""
    from superset.utils.cache import memoized_func

    cache = mocker.MagicMock()
    cache.get.return_value = None

    decorator = memoized_func("{a}", cache)
    decorated = decorator(lambda a: a * 3)

    result = decorated(4, cache=True, cache_timeout=120)
    assert result == 12
    cache.set.assert_called_once_with("4", 12, timeout=120)


# ---------------------------------------------------------------------------
# etag_cache
# ---------------------------------------------------------------------------


def test_etag_cache_post_request_bypasses_cache(
    mocker: MockerFixture, app: SupersetApp
) -> None:
    """POST requests are not cached."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()
    cache._memoize_make_cache_key = mocker.MagicMock(return_value=lambda *a, **k: "k")

    response = Response("post_data", status=200)

    @etag_cache(cache=cache)
    def my_view() -> Response:
        return response

    with app.test_request_context("/", method="POST"):
        result = my_view()
        assert result is response
        cache.get.assert_not_called()


def test_etag_cache_skip_callback(mocker: MockerFixture, app: SupersetApp) -> None:
    """When skip returns True the cache is bypassed."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()
    cache._memoize_make_cache_key = mocker.MagicMock(return_value=lambda *a, **k: "k")

    response = Response("skip", status=200)

    @etag_cache(cache=cache, skip=lambda: True)
    def my_view() -> Response:
        return response

    with app.test_request_context("/", method="GET"):
        result = my_view()
        assert result is response
        cache.get.assert_not_called()


def test_etag_cache_raise_for_access_failure(
    mocker: MockerFixture, app: SupersetApp
) -> None:
    """If raise_for_access raises, the function is called without caching."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()
    cache._memoize_make_cache_key = mocker.MagicMock(return_value=lambda *a, **k: "k")

    response = Response("denied", status=403)

    def deny() -> None:
        raise PermissionError("no access")

    @etag_cache(cache=cache, raise_for_access=deny)
    def my_view() -> Response:
        return response

    with app.test_request_context("/", method="GET"):
        result = my_view()
        assert result is response
        cache.get.assert_not_called()


def test_etag_cache_returns_cached_response(
    mocker: MockerFixture, app: SupersetApp
) -> None:
    """A cached response is returned and made conditional."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()

    cached_response = Response("cached", status=200)
    cached_response.last_modified = datetime.utcnow()
    cached_response.add_etag()
    cache.get.return_value = cached_response
    cache._memoize_make_cache_key = mocker.MagicMock(
        return_value=lambda *a, **k: "cache_key"
    )

    call_count = 0

    @etag_cache(cache=cache)
    def my_view() -> Response:
        nonlocal call_count
        call_count += 1
        return Response("fresh", status=200)

    with app.test_request_context("/", method="GET"):
        my_view()
        assert call_count == 0  # wrapped fn was never called


def test_etag_cache_computes_fresh_response(
    mocker: MockerFixture, app: SupersetApp
) -> None:
    """When no cached response exists, the function is called and the result
    is stored in the cache with correct headers."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()
    cache.get.return_value = None
    cache._memoize_make_cache_key = mocker.MagicMock(
        return_value=lambda *a, **k: "cache_key"
    )

    @etag_cache(cache=cache, max_age=600)
    def my_view() -> Response:
        return Response("fresh", status=200)

    with app.test_request_context("/", method="GET"):
        result = my_view()
        cache.set.assert_called_once()
        assert result.status_code == 200


def test_etag_cache_stale_last_modified(
    mocker: MockerFixture, app: SupersetApp
) -> None:
    """Stale cached responses (older than last-modified) are recomputed."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()

    old_time = datetime(2020, 1, 1)
    new_time = datetime(2025, 1, 1)

    cached_response = Response("old", status=200)
    cached_response.last_modified = old_time
    cache.get.return_value = cached_response
    cache._memoize_make_cache_key = mocker.MagicMock(
        return_value=lambda *a, **k: "cache_key"
    )

    @etag_cache(cache=cache, get_last_modified=lambda: new_time)
    def my_view() -> Response:
        return Response("new", status=200)

    with app.test_request_context("/", method="GET"):
        my_view()
        cache.set.assert_called_once()


def test_etag_cache_sets_public_cache_control(
    mocker: MockerFixture, app: SupersetApp
) -> None:
    """Without get_last_modified or raise_for_access, Cache-Control is public."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()
    cache.get.return_value = None
    cache._memoize_make_cache_key = mocker.MagicMock(
        return_value=lambda *a, **k: "cache_key"
    )

    @etag_cache(cache=cache, max_age=300)
    def my_view() -> Response:
        return Response("data", status=200)

    with app.test_request_context("/", method="GET"):
        result = my_view()
        assert result.cache_control.public


def test_etag_cache_sets_no_cache_with_last_modified(
    mocker: MockerFixture, app: SupersetApp
) -> None:
    """With get_last_modified, Cache-Control is no-cache for revalidation."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()
    cache.get.return_value = None
    cache._memoize_make_cache_key = mocker.MagicMock(
        return_value=lambda *a, **k: "cache_key"
    )

    @etag_cache(
        cache=cache,
        max_age=300,
        get_last_modified=lambda: datetime.utcnow(),
    )
    def my_view() -> Response:
        return Response("data", status=200)

    with app.test_request_context("/", method="GET"):
        result = my_view()
        assert result.cache_control.no_cache


def test_etag_cache_wrapper_attributes(
    mocker: MockerFixture, app_context: None
) -> None:
    """The wrapper exposes ``uncached``, ``cache_timeout``, and ``make_cache_key``."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()
    cache._memoize_make_cache_key = mocker.MagicMock(return_value=lambda *a, **k: "k")

    def my_view() -> Response:
        return Response("ok")

    wrapped = etag_cache(cache=cache, max_age=123)(my_view)

    assert wrapped.uncached is my_view
    assert wrapped.cache_timeout == 123
    assert callable(wrapped.make_cache_key)


def test_etag_cache_exception_during_cache_get(
    mocker: MockerFixture, app: SupersetApp
) -> None:
    """Exceptions during cache.get are swallowed in non-debug mode."""
    from superset.utils.cache import etag_cache

    cache = mocker.MagicMock()
    cache.get.side_effect = Exception("redis down")
    cache._memoize_make_cache_key = mocker.MagicMock(
        return_value=lambda *a, **k: "cache_key"
    )

    app.debug = False

    @etag_cache(cache=cache)
    def my_view() -> Response:
        return Response("fallback", status=200)

    with app.test_request_context("/", method="GET"):
        result = my_view()
        assert result.status_code == 200


# ---------------------------------------------------------------------------
# ONE_YEAR constant
# ---------------------------------------------------------------------------


def test_one_year_constant() -> None:
    """ONE_YEAR equals 365 days in seconds."""
    from superset.utils.cache import ONE_YEAR

    assert ONE_YEAR == 365 * 24 * 60 * 60
