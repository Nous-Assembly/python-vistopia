import pytest
import sys
from pathlib import Path
import os

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR.parent))
from vistopia.visitor import Visitor


@pytest.fixture
def visitor():
    return Visitor(token="")


def test_get_catalog(visitor):
    catalog = visitor.get_catalog(id=11)
    assert catalog
    assert catalog.author == "梁文道"
    assert catalog.title == "八分"

    assert isinstance(catalog.catalog, list)


def test_get_content_show(visitor):
    content_show = visitor.get_content_show(id=11)
    assert content_show.author == "梁文道"
    assert content_show.title == "八分"


def test_save_show(visitor, tmpdir):

    cwd = os.getcwd()
    os.chdir(tmpdir)
    visitor.save_show(id=11, episodes={1})
    os.chdir(cwd)

    expected_file = (
        Path(tmpdir) /
        "八分" /
        "【推荐语】窦文涛：我保证《八分》会给咱们“十分”的收获.mp3"
    )

    assert expected_file.exists()
    assert os.path.getsize(expected_file) > 0


def test_save_transcript(visitor, tmpdir):

    cwd = os.getcwd()
    os.chdir(tmpdir)
    visitor.save_transcript(id=11, episodes={1})
    os.chdir(cwd)

    expected_file = (
        Path(tmpdir) /
        "八分" /
        "【推荐语】窦文涛：我保证《八分》会给咱们“十分”的收获.html"
    )

    assert expected_file.exists()
    assert os.path.getsize(expected_file) > 0

    with open(expected_file, "r", encoding="utf8") as fp:
        line = fp.readline()
        assert line.strip() == "<!DOCTYPE html>"


@pytest.mark.parametrize("keyword, expected", [
    ("八分", (11, "梁文道", "八分", "知识只求八分饱", "content")),
    ("李如一", (19, "李如一", "20世纪十大唱片里程碑", "作为乐器的录音室", "content")),
])
def test_search(visitor: Visitor, keyword: str, expected: tuple):

    data = visitor.search(keyword)
    assert isinstance(data, list)
    for k in ("id", "author", "title", "share_desc", "data_type"):
        assert all([hasattr(item, k) for item in data])
    assert any([
        (
            int(item.id),
            item.author,
            item.title,
            item.share_desc,
            item.data_type,
        ) == expected for item in data
    ])


def _article(
    title="第一集",
    number="1",
    url="https://api.vistopia.com.cn/api/v1/web/article-content/abc",
):
    from vistopia.models import Article

    return Article(
        article_id="abc",
        sort_number=number,
        title=title,
        duration_str="10:00",
        content_url=url,
    )


def _catalog(title="测试节目", article=None):
    from vistopia.models import Catalog, CatalogPart

    return Catalog(
        author="作者",
        title=title,
        type="charge",
        catalog=[CatalogPart(part=[article or _article()])],
    )


def _article_url(visitor):
    return visitor.authorized_url(
        "https://api.vistopia.com.cn/api/v1/web/article-content/abc"
    )


def test_authorized_url_attaches_token():
    visitor = Visitor(token="token-123")

    assert _article_url(visitor) == (
        "https://api.vistopia.com.cn/api/v1/web/article-content/abc"
        "?api_token=token-123"
    )


def test_authorized_url_round_trips_reserved_characters():
    from urllib.parse import parse_qs, urlsplit

    token = "a&b=c d/中"
    query = parse_qs(urlsplit(_article_url(Visitor(token=token))).query)

    assert query["api_token"] == [token]


@pytest.mark.parametrize("token", [None, ""])
def test_authorized_url_without_token_is_unchanged(token):
    url = "https://api.vistopia.com.cn/api/v1/web/article-content/abc"

    assert Visitor(token=token).authorized_url(url) == url
    assert Visitor(token=token).authorized_url(None) is None


def test_authorized_url_replaces_existing_token():
    from urllib.parse import parse_qs, urlsplit

    url = "https://api.vistopia.com.cn/a?api_token=old&x=1"
    authorized = Visitor("new").authorized_url(url)
    assert authorized is not None
    query = parse_qs(urlsplit(authorized).query)

    assert query["api_token"] == ["new"]
    assert query["x"] == ["1"]


def test_authorized_url_keeps_fragment_out_of_the_token():
    from urllib.parse import urlsplit

    parts = urlsplit(_article_url(Visitor("token-123")) + "#part")

    assert parts.fragment == "part"
    assert "token-123" in parts.query


def test_authorized_url_rejects_untrusted_host_without_leaking_token():
    with pytest.raises(ValueError) as error:
        Visitor("token-123").authorized_url("https://evil.example/article")

    assert "token-123" not in str(error.value)


def test_authorized_url_rejects_plain_http():
    with pytest.raises(ValueError):
        Visitor("token-123").authorized_url(
            "http://api.vistopia.com.cn/article"
        )


def test_save_transcript_sends_token(monkeypatch, tmpdir):
    import vistopia.visitor as visitor_module

    visitor = Visitor(token="secret")
    calls = []

    def fake_retrieve(url, path):
        calls.append(url)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('<html>is_cut_str = "0"; body</html>')

    monkeypatch.setattr(visitor, "get_catalog", lambda _id: _catalog())
    monkeypatch.setattr(visitor_module, "urlretrieve", fake_retrieve)

    cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        visitor.save_transcript(1)
    finally:
        os.chdir(cwd)

    assert calls and "api_token=secret" in calls[0]
    assert (Path(tmpdir) / "测试节目" / "第一集.html").exists()


def test_save_transcript_rejects_cut_article(monkeypatch, tmpdir):
    import vistopia.visitor as visitor_module

    visitor = Visitor(token="secret")

    def fake_retrieve(url, path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('<html>is_cut_str = "1"; preview</html>')

    monkeypatch.setattr(visitor, "get_catalog", lambda _id: _catalog())
    monkeypatch.setattr(visitor_module, "urlretrieve", fake_retrieve)

    cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        with pytest.raises(RuntimeError):
            visitor.save_transcript(1)
    finally:
        os.chdir(cwd)

    show_dir = Path(tmpdir) / "测试节目"
    assert not (show_dir / "第一集.html").exists()
    assert not list(show_dir.glob("*.part"))


def test_save_transcript_refetches_existing_cut_file(monkeypatch, tmpdir):
    import vistopia.visitor as visitor_module

    visitor = Visitor(token="secret")
    show_dir = Path(tmpdir) / "测试节目"
    show_dir.mkdir()
    (show_dir / "第一集.html").write_text(
        '<html>is_cut_str = "1"; preview</html>', encoding="utf-8"
    )
    calls = []

    def fake_retrieve(url, path):
        calls.append(url)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('<html>is_cut_str = "0"; body</html>')

    monkeypatch.setattr(visitor, "get_catalog", lambda _id: _catalog())
    monkeypatch.setattr(visitor_module, "urlretrieve", fake_retrieve)

    cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        visitor.save_transcript(1)
    finally:
        os.chdir(cwd)

    content = (show_dir / "第一集.html").read_text(encoding="utf-8")
    assert calls
    assert 'is_cut_str = "0"' in content


def test_save_transcript_skips_complete_file(monkeypatch, tmpdir):
    import vistopia.visitor as visitor_module

    visitor = Visitor(token="secret")
    show_dir = Path(tmpdir) / "测试节目"
    show_dir.mkdir()
    (show_dir / "第一集.html").write_text(
        '<html>is_cut_str = "0"; body</html>', encoding="utf-8"
    )

    def fake_retrieve(url, path):
        raise AssertionError("should not download again")

    monkeypatch.setattr(visitor, "get_catalog", lambda _id: _catalog())
    monkeypatch.setattr(visitor_module, "urlretrieve", fake_retrieve)

    cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        visitor.save_transcript(1)
    finally:
        os.chdir(cwd)


def test_save_transcript_reports_missing_url(monkeypatch, tmpdir):
    visitor = Visitor(token=None)
    monkeypatch.setattr(
        visitor, "get_catalog", lambda _id: _catalog(article=_article(url=None))
    )

    cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        with pytest.raises(RuntimeError):
            visitor.save_transcript(1)
    finally:
        os.chdir(cwd)


def test_authorized_url_rejects_non_default_port():
    with pytest.raises(ValueError):
        Visitor("token-123").authorized_url(
            "https://api.vistopia.com.cn:8443/article"
        )


@pytest.mark.parametrize("token", [None, ""])
def test_authorized_url_validates_without_token(token):
    with pytest.raises(ValueError):
        Visitor(token=token).authorized_url("file:///etc/hosts")
    with pytest.raises(ValueError):
        Visitor(token=token).authorized_url(
            "https://api.vistopia.com.cn:8443/article"
        )


def _save_with(monkeypatch, tmpdir, body, existing=None, token="secret"):
    import vistopia.visitor as visitor_module

    visitor = Visitor(token=token)
    show_dir = Path(tmpdir) / "测试节目"
    show_dir.mkdir(exist_ok=True)
    if existing is not None:
        (show_dir / "第一集.html").write_text(existing, encoding="utf-8")

    def fake_retrieve(url, path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)

    monkeypatch.setattr(visitor, "get_catalog", lambda _id: _catalog())
    monkeypatch.setattr(visitor_module, "urlretrieve", fake_retrieve)

    cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        visitor.save_transcript(1)
    finally:
        os.chdir(cwd)
    return show_dir / "第一集.html"


def test_save_transcript_rejects_unmarked_response(monkeypatch, tmpdir):
    with pytest.raises(RuntimeError):
        _save_with(monkeypatch, tmpdir, "<html>Please log in</html>")

    assert not (Path(tmpdir) / "测试节目" / "第一集.html").exists()


def test_save_transcript_rejects_empty_response(monkeypatch, tmpdir):
    with pytest.raises(RuntimeError):
        _save_with(monkeypatch, tmpdir, "")

    assert not (Path(tmpdir) / "测试节目" / "第一集.html").exists()


def test_save_transcript_refetches_empty_existing_file(monkeypatch, tmpdir):
    path = _save_with(
        monkeypatch, tmpdir, '<html>is_cut_str = "0"; body</html>',
        existing="",
    )

    assert 'is_cut_str = "0"' in path.read_text(encoding="utf-8")


def test_save_transcript_refetches_login_page(monkeypatch, tmpdir):
    path = _save_with(
        monkeypatch, tmpdir, '<html>is_cut_str = "0"; body</html>',
        existing="<html>Please log in</html>",
    )

    assert 'is_cut_str = "0"' in path.read_text(encoding="utf-8")
