from __future__ import annotations

import json
import sysconfig
from importlib import import_module, resources
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

_MIGRATION_RESOURCES = (
    "db/migrations_sqlite/models/0_20211117110249_init.py",
    "db/migrations_sqlite/models/1_20211130051128_update.py",
    "db/migrations_sqlite/models/2_20220306045951_update.py",
    "db/migrations_sqlite/models/3_20220415025716_update.py",
    "db/migrations_sqlite/models/4_20240425020849_display_entry_tags.py",
    "db/migrations_pgsql/models/0_20211117110249_init.py",
    "db/migrations_pgsql/models/1_20211130051128_update.py",
    "db/migrations_pgsql/models/2_20220306045951_update.py",
    "db/migrations_pgsql/models/3_20220415030554_update.py",
    "db/migrations_pgsql/models/4_20240425020849_display_entry_tags.py",
)


def _assert_executable_resources(package_name: str) -> None:
    package_files = resources.files(package_name)

    opml = BeautifulSoup(
        package_files.joinpath("opml_template.opml").read_text(encoding="utf-8"),
        "lxml-xml",
    )
    assert opml.find("opml") is not None
    assert opml.find("body") is not None

    english = json.loads(
        package_files.joinpath("i18n/en.json").read_text(encoding="utf-8")
    )
    assert english["l10n_info"]["lang_code"] == "en"
    assert english["l10n_info"]["language_name"] == "English"

    for relative_path in _MIGRATION_RESOURCES:
        migration = package_files.joinpath(relative_path)
        source = migration.read_text(encoding="utf-8")
        compile(source, str(migration), "exec")


@pytest.mark.unit
def test_source_package_resources_are_parseable_and_executable() -> None:
    _assert_executable_resources("src")


def main() -> None:
    installed_package = import_module("rsstt")
    package_path = Path(installed_package.__file__).resolve()
    purelib_path = Path(sysconfig.get_path("purelib")).resolve()
    assert package_path.is_relative_to(purelib_path), (package_path, purelib_path)

    checkout_shadow = Path.cwd() / "rsstt"
    assert not checkout_shadow.is_dir()
    assert not checkout_shadow.is_symlink()

    _assert_executable_resources("rsstt")


if __name__ == "__main__":
    main()
