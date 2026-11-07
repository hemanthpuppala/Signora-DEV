"""Configuration tests (backbone LLD §6.5)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from signora.kernel import config
from signora.kernel.config import ConfigError, env_var_names, load_settings, repo_root

REPO_ROOT = Path(__file__).resolve().parents[4]

BASELINE = {
    "PUBLIC_BASE_URL": "https://signora.example",
    "SECRET_KEY": "k" * 48,
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "55432",
    "POSTGRES_USER": "signora",
    "POSTGRES_PASSWORD": "pw",
    "POSTGRES_DB": "signora",
    "GOTENBERG_HOST": "127.0.0.1",
    "GOTENBERG_PORT": "53000",
}

PRODUCTION_EXTRAS = {
    "APP_ENV": "production",
    "AI_API_KEY": "sk-test",
    "SMTP_USERNAME": "sender@example.com",
    "SMTP_PASSWORD": "app-password",
    "EMAIL_FROM_ADDRESS": "sender@example.com",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from configuration variables set in the developer's shell."""
    for name in (*env_var_names(), config.ROOT_ENV_VAR):
        monkeypatch.delenv(name, raising=False)


def make_root(tmp_path: Path, values: dict[str, str]) -> Path:
    (tmp_path / config.ROOT_MARKER).write_text("# marker\n", encoding="utf-8")
    lines = [f"{key}={value}" for key, value in values.items()]
    (tmp_path / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("password", ["p@ss", "a/b", "x#y", "100%", "c:o?l&on=", "spa ce"])
def test_database_url_survives_special_characters_in_the_password(
    tmp_path: Path, password: str
) -> None:
    from sqlalchemy.engine import make_url

    from signora.kernel.migrations import alembic_config

    settings = load_settings(make_root(tmp_path, {**BASELINE, "POSTGRES_PASSWORD": password}))

    for url in (
        settings.db.url,
        alembic_config(settings.db).get_main_option("sqlalchemy.url"),  # what migrations use
    ):
        assert url is not None
        parsed = make_url(url)
        assert parsed.password == password
        assert (parsed.host, parsed.port, parsed.database) == ("127.0.0.1", 55432, "signora")


def test_loads_groups_and_resolves_relative_paths_against_root(tmp_path: Path) -> None:
    root = make_root(tmp_path, {**BASELINE, "BLOB_STORE_DIR": "./data/blobs"})

    settings = load_settings(root)

    assert settings.app.root == root
    assert settings.blob_store.dir == (root / "data" / "blobs").resolve()
    assert settings.db.url == "postgresql+psycopg://signora:pw@127.0.0.1:55432/signora"
    assert settings.gotenberg.base_url == "http://127.0.0.1:53000"
    assert settings.worker.concurrency == 8
    assert settings.api.threads == 20


def test_environment_variable_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_root(tmp_path, BASELINE)
    monkeypatch.setenv("POSTGRES_PORT", "6000")

    assert load_settings(root).db.port == 6000


def test_reports_every_problem_at_once(tmp_path: Path) -> None:
    values = {**BASELINE, "SECRET_KEY": "short", "POSTGRES_PORT": "70000", "APP_ENV": "staging"}
    values.pop("POSTGRES_PASSWORD")
    root = make_root(tmp_path, values)

    with pytest.raises(ConfigError) as excinfo:
        load_settings(root)

    problems = " ".join(excinfo.value.problems)
    for variable in ("SECRET_KEY", "POSTGRES_PORT", "APP_ENV", "POSTGRES_PASSWORD"):
        assert variable in problems
    assert len(excinfo.value.problems) == 4


def test_development_allows_unconfigured_integrations(tmp_path: Path) -> None:
    settings = load_settings(make_root(tmp_path, {**BASELINE, "AI_API_KEY": ""}))

    assert settings.ai.configured is False
    assert settings.email.configured is False
    assert settings.stripe.configured is False


def test_production_requires_ai_and_email_and_https(tmp_path: Path) -> None:
    values = {**BASELINE, "APP_ENV": "production", "PUBLIC_BASE_URL": "http://insecure.example"}

    with pytest.raises(ConfigError) as excinfo:
        load_settings(make_root(tmp_path, values))

    problems = " ".join(excinfo.value.problems)
    for variable in (
        "PUBLIC_BASE_URL",
        "AI_API_KEY",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "EMAIL_FROM_ADDRESS",
    ):
        assert variable in problems


def test_production_does_not_require_stripe(tmp_path: Path) -> None:
    settings = load_settings(make_root(tmp_path, {**BASELINE, **PRODUCTION_EXTRAS}))

    assert settings.app.is_production
    assert settings.ai.configured and settings.email.configured
    assert settings.stripe.configured is False


def test_secrets_never_appear_in_repr_or_str(tmp_path: Path) -> None:
    settings = load_settings(make_root(tmp_path, {**BASELINE, **PRODUCTION_EXTRAS}))

    rendered = repr(settings) + str(settings)
    for secret in (BASELINE["SECRET_KEY"], "sk-test", "app-password"):
        assert secret not in rendered


def test_signora_root_overrides_derivation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_root(tmp_path, BASELINE)
    monkeypatch.setenv(config.ROOT_ENV_VAR, str(root))

    assert repo_root() == root.resolve()


def test_root_without_marker_fails_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config.ROOT_ENV_VAR, str(tmp_path))

    with pytest.raises(ConfigError, match=re.escape(config.ROOT_MARKER)):
        repo_root()


def test_derived_root_is_the_repository() -> None:
    assert repo_root() == REPO_ROOT


@pytest.mark.parametrize("cwd", [REPO_ROOT, REPO_ROOT / "apps" / "api", None])
def test_root_and_paths_do_not_depend_on_working_directory(
    cwd: Path | None, tmp_path: Path
) -> None:
    """API and worker may start from any folder; they must agree on root, .env and blob dir."""
    script = (
        "from signora.kernel.config import repo_root, get_settings\n"
        "s = get_settings()\n"
        "print(repo_root()); print(s.blob_store.dir)\n"
    )
    env = {k: v for k, v in os.environ.items() if k != config.ROOT_ENV_VAR}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd or tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    root_line, blob_line = result.stdout.splitlines()
    assert Path(root_line) == REPO_ROOT
    assert Path(blob_line).is_relative_to(REPO_ROOT)


def _documented_variables(env_example: Path) -> set[str]:
    pattern = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=")
    names: set[str] = set()
    for line in env_example.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            names.add(match.group(1))
    return names


def test_env_example_documents_exactly_the_settings() -> None:
    documented = _documented_variables(REPO_ROOT / ".env.example")
    # SIGNORA_ROOT is read before settings load (it locates .env), so it is not a settings field.
    expected = env_var_names() | {config.ROOT_ENV_VAR}

    assert documented - expected == set(), "variables in .env.example with no setting"
    assert expected - documented == set(), "settings missing from .env.example"
