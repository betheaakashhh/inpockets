import pytest

from tests.conftest import assert_safe_test_database

pytestmark = pytest.mark.unit


def test_test_database_guard_accepts_dedicated_test_database():
    assert_safe_test_database("inpockets_test", "app_test", "development")


@pytest.mark.parametrize(
    ("database_name", "environment"),
    [
        ("inpockets", "development"),
        ("inpockets_staging", "staging"),
        ("inpockets_prod", "development"),
    ],
)
def test_test_database_guard_rejects_unsafe_targets(database_name, environment):
    with pytest.raises(RuntimeError):
        assert_safe_test_database(database_name, "app_test", environment)
