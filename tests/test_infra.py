"""Stage 10 guards for infra/: the Ansible env template must not drift from the documented env
file, and the only secrets file that may be committed is an encrypted one."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ANSIBLE = ROOT / "infra" / "ansible"
ENV_EXAMPLE = ROOT / "deploy" / "jifunze.env.example"
ENV_TEMPLATE = ANSIBLE / "roles" / "jifunze_app" / "templates" / "jifunze.env.j2"
KEY = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.M)


def test_env_template_has_exactly_the_keys_of_the_documented_env_file():
    documented = set(KEY.findall(ENV_EXAMPLE.read_text()))
    templated = set(KEY.findall(ENV_TEMPLATE.read_text()))
    assert templated == documented


def test_env_template_has_no_literal_secrets():
    text = ENV_TEMPLATE.read_text()
    for name in ("SESSION_SECRET", "SMTP_PASSWORD"):
        assert re.search(rf"^{name}=\{{\{{ \w+ \}}\}}$", text, re.M), (
            f"{name} must come from a variable"
        )


def secret_files():
    return [
        p
        for p in (ROOT / "infra").rglob("*")
        if p.is_file() and re.search(r"secrets?[^/]*\.(ya?ml|json)$", p.name)
    ]


def test_secret_files_exist_to_check():
    assert any(p.name == "secrets.example.yaml" for p in secret_files())


@pytest.mark.parametrize("path", secret_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_only_encrypted_or_example_secrets_files_are_committed(path):
    text = path.read_text()
    if path.name.endswith(".example.yaml"):
        assert "CHANGE-ME" in text
    else:
        assert path.name.endswith(".sops.yaml")
        assert "ENC[AES256_GCM" in text and "\nsops:" in text, "not sops-encrypted"


def test_sops_rule_has_a_placeholder_not_a_private_key():
    text = (ANSIBLE / ".sops.yaml").read_text()
    assert "AGE-SECRET-KEY" not in text
    assert re.search(r"age:\s*(REPLACE-WITH|age1[a-z0-9]{50,})", text)


def test_no_age_private_key_anywhere_in_infra_or_docs():
    for base in (ROOT / "infra", ROOT / "docs", ROOT / "deploy"):
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in {".yml", ".yaml", ".md", ".j2", ".tf", ".txt"}:
                assert "AGE-SECRET-KEY-" not in p.read_text(), p
