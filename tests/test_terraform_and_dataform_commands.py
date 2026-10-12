import json
from pathlib import Path

import pytest

from scripts import dataform, terraform
from scripts.config import ConfigError, Settings, Stack

SETTINGS = Settings(project_id="demo-project-1")
STACK = Stack(
    project_id="demo-project-1",
    location="US",
    bucket="demo-bucket",
    raw_dataset="raw_ds",
    warehouse_dataset="wh_ds",
    assertions_dataset="assert_ds",
    ai_connection="demo-project-1.US.conn",
)


def which_with(**found):
    return lambda name: found.get(name)


def test_variable_args_add_bucket_only_when_set():
    assert terraform.variable_args(SETTINGS) == [
        "-var=project_id=demo-project-1",
        "-var=location=US",
    ]
    withbucket = Settings(project_id="demo-project-1", bucket="b")
    assert "-var=bucket_name=b" in terraform.variable_args(withbucket)


def test_adc_path_by_platform():
    assert terraform.adc_path({"GOOGLE_APPLICATION_CREDENTIALS": "/x/y.json"}) == Path("/x/y.json")
    win = terraform.adc_path({"APPDATA": "C:/Users/me/AppData/Roaming"}, platform="win32")
    assert win.parts[-2:] == ("gcloud", "application_default_credentials.json")
    nix = terraform.adc_path({"HOME": "/home/me"}, platform="linux")
    assert nix == Path("/home/me/.config/gcloud/application_default_credentials.json")


def test_configured_binary_wins_over_path():
    s = Settings(project_id="demo-project-1", terraform_bin="/opt/tf")
    argv = terraform.command(
        ["plan"], s, environ={}, which=which_with(terraform="/usr/bin/terraform")
    )
    assert argv == ["/opt/tf", "plan"]


def test_binary_on_path_is_used_when_not_configured():
    argv = terraform.command(
        ["plan"], SETTINGS, environ={}, which=which_with(terraform="/usr/bin/terraform")
    )
    assert argv == ["/usr/bin/terraform", "plan"]


def test_docker_fallback_mounts_adc_read_only(tmp_path):
    adc = tmp_path / "adc.json"
    adc.write_text("{}", encoding="utf-8")
    argv = terraform.command(
        ["apply", "-auto-approve"],
        SETTINGS,
        environ={"GOOGLE_APPLICATION_CREDENTIALS": str(adc)},
        which=which_with(docker="/usr/bin/docker"),
        tf_dir=tmp_path / "tf",
    )
    assert argv[:3] == ["docker", "run", "--rm"]
    assert f"{adc}:/run/adc.json:ro" in argv
    assert "GOOGLE_CLOUD_QUOTA_PROJECT=demo-project-1" in argv
    image = argv.index("hashicorp/terraform:1.16.5")
    assert argv[image + 1 :] == ["apply", "-auto-approve"]


def test_no_terraform_and_no_docker_is_a_clear_error():
    with pytest.raises(ConfigError, match="docker"):
        terraform.command(["plan"], SETTINGS, environ={}, which=which_with())


def test_docker_without_credentials_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="application default credentials"):
        terraform.command(
            ["plan"],
            SETTINGS,
            environ={"GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "nope.json")},
            which=which_with(docker="/usr/bin/docker"),
        )


def test_dataform_vars_carry_the_stack_names():
    assert dataform.project_vars(STACK) == {
        "raw_dataset": "raw_ds",
        "raw_bucket": "demo-bucket",
        "schools_object": "schools/wi_schools.parquet",
    }


def test_dataform_compile_command(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npx")
    argv = dataform.command("compile", STACK)
    assert argv[1:4] == ["--yes", "@dataform/cli@3.0.71", "compile"]
    assert argv[argv.index("--default-database") + 1] == "demo-project-1"
    assert argv[argv.index("--assertion-schema") + 1] == "assert_ds"
    assert argv[argv.index("--default-schema") + 1] == "wh_ds"
    vars_arg = next(a for a in argv if a.startswith("--vars="))
    assert "raw_bucket=demo-bucket" in vars_arg
    assert "--credentials" not in argv


def test_dataform_run_writes_credentials_without_a_key(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npx")
    monkeypatch.setattr(dataform, "STATE_DIR", tmp_path)
    argv = dataform.command("run", STACK, extra=["--actions", "wi_counties"])
    creds = Path(argv[argv.index("--credentials") + 1])
    assert json.loads(creds.read_text(encoding="utf-8")) == {
        "projectId": "demo-project-1",
        "location": "US",
    }
    assert argv[-2:] == ["--actions", "wi_counties"]


def test_dataform_rejects_other_actions_and_missing_npx(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npx")
    with pytest.raises(ValueError):
        dataform.command("init", STACK)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ConfigError, match="npx"):
        dataform.command("compile", STACK)
