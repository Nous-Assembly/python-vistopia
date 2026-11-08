import sys
from pathlib import Path
import click.testing

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR.parent / "vistopia"))
from vistopia.main import main


def test_cli_list_show_content(
    cli_runner: click.testing.CliRunner
):
    result: click.testing.Result = cli_runner.invoke(main, [
        "show-content", "--id", "18"
    ])

    assert result.exit_code == 0


def test_cli_search(
    cli_runner: click.testing.CliRunner
):
    result: click.testing.Result = cli_runner.invoke(main, [
        "search", "-k", "八分"
    ])

    assert result.exit_code == 0
    assert len(result.stdout_bytes) > 0


def test_cli_version(
    cli_runner: click.testing.CliRunner
):
    result: click.testing.Result = cli_runner.invoke(main, [
        "--version"
    ])

    assert result.exit_code == 0
    assert len(result.stdout.strip().split(".")) == 3


def test_token_is_redacted_from_logs():
    import logging

    from vistopia.main import _TokenRedactionFilter

    record = logging.LogRecord(
        "urllib3.connectionpool",
        logging.DEBUG,
        __file__,
        1,
        "GET /probe?api_token=SECRET&x=1 HTTP/1.1",
        (),
        None,
    )

    assert _TokenRedactionFilter().filter(record) is True
    assert "SECRET" not in record.getMessage()
    assert "api_token=***" in record.getMessage()


def test_cli_redacts_token_from_debug_logs(cli_runner, caplog):
    import logging

    caplog.set_level(logging.DEBUG)

    cli_runner.invoke(main, ["-t", "SECRET-TOKEN", "-v", "DEBUG", "search"])
    logging.getLogger("urllib3.connectionpool").debug(
        "GET /probe?api_token=SECRET-TOKEN&x=1 HTTP/1.1"
    )

    assert "SECRET-TOKEN" not in caplog.text
    assert "api_token=***" in caplog.text
