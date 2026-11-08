import os
import re
import tempfile

import requests
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import urlretrieve, urlcleanup
from logging import getLogger
from functools import lru_cache
from typing import List, Optional
from pathvalidate import sanitize_filename

from .models import (
    Article,
    Catalog,
    ContentShow,
    RetagArticle,
    RetagSeries,
    SearchResult,
    SubscriptionsList,
    SubscriptionItem,
    validate_model,
)

logger = getLogger(__name__)

# Article pages are served by the API host only.
ARTICLE_HOST = "api.vistopia.com.cn"


class Visitor:
    def __init__(self, token: Optional[str]):
        self.token = token

    def authorized_url(self, url: Optional[str]) -> Optional[str]:
        """Attach the API token to an article URL.

        Article pages live on the same API host as the JSON endpoints.  An
        anonymous request is served a truncated article, so the token has to
        travel with the transcript URL as well.  The token is never sent to
        another host, and the URL is rebuilt through urlsplit so a fragment
        or an existing query cannot swallow or duplicate the credential.
        """
        if not url or not self.token:
            return url

        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != ARTICLE_HOST:
            raise ValueError(
                "refusing to attach credentials to an unexpected article URL"
            )

        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key != "api_token"
        ]
        query.append(("api_token", str(self.token)))
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query),
                parts.fragment,
            )
        )

    def get_api_response(self, uri: str, params: Optional[dict] = None):

        url = urljoin("https://api.vistopia.com.cn/api/v1/", uri)

        if params is None:
            params = {}

        params.update({"api_token": self.token})

        logger.debug(f"Visiting {url}")

        response = requests.get(url, params=params).json()
        assert response["status"] == "success"
        assert "data" in response.keys()

        return response["data"]

    @lru_cache()
    def get_catalog(self, id: int):
        response = self.get_api_response(f"content/catalog/{id}")
        return validate_model(Catalog, response)

    @lru_cache()
    def get_user_subscriptions_list(self):
        data: List[SubscriptionItem] = []
        while True:
            response = self.get_api_response("user/subscriptions-list")
            subscriptions = validate_model(SubscriptionsList, response)
            data.extend(subscriptions.data)
            break
        return data

    @lru_cache()
    def search(self, keyword: str) -> list:
        response = self.get_api_response("search/web", {'keyword': keyword})
        result = validate_model(SearchResult, response)
        return result.data

    @lru_cache()
    def get_content_show(self, id: int):
        response = self.get_api_response(f"content/content-show/{id}")
        return validate_model(ContentShow, response)

    def save_show(self, id: int,
                  no_tag: bool = False, no_cover: bool = False,
                  episodes: Optional[set] = None):

        from pathlib import Path

        catalog = self.get_catalog(id)
        series = self.get_content_show(id)

        show_dir = Path(catalog.title)
        show_dir.mkdir(exist_ok=True)

        for part in catalog.catalog:
            for article in part.part:

                if episodes and \
                        int(article.sort_number) not in episodes:
                    continue

                fname = show_dir / "{}.mp3".format(
                    sanitize_filename(article.title)
                )
                if not fname.exists():
                    urlretrieve(article.media_key_full_url, fname)

                if not no_tag:
                    self.retag(str(fname), article, catalog, series)

                if not no_cover:
                    self.retag_cover(str(fname), article, catalog, series)

    def save_transcript(self, id: int, episodes: Optional[set] = None):

        from pathlib import Path

        catalog = self.get_catalog(id)

        show_dir = Path(catalog.title)
        show_dir.mkdir(exist_ok=True)

        for part in catalog.catalog:
            for article in part.part:

                if episodes and \
                        int(article.sort_number) not in episodes:
                    continue

                fname = show_dir / "{}.html".format(
                    sanitize_filename(article.title)
                )
                if fname.exists() and not self._is_cut_transcript(fname):
                    continue
                self._download_transcript(article, fname)

    @staticmethod
    def _is_cut_transcript(path) -> bool:
        """Return True when a saved article is the truncated preview."""
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return bool(re.search(r'is_cut_str\s*=\s*"1"', handle.read()))
        except OSError:
            return False

    def _download_transcript(self, article, fname):
        """Fetch one article into a temporary file, then move it into place."""
        url = self.authorized_url(article.content_url)
        if not url:
            raise RuntimeError(
                "article URL is missing for {}".format(article.title)
            )

        descriptor, temporary = tempfile.mkstemp(
            dir=os.path.dirname(str(fname)) or ".", suffix=".part"
        )
        os.close(descriptor)
        try:
            try:
                urlretrieve(url, temporary)
            except Exception:
                # Never surface the request URL: it carries the API token.
                raise RuntimeError(
                    "failed to download the article for {}".format(
                        article.title
                    )
                ) from None

            with open(temporary, encoding="utf-8", errors="replace") as handle:
                content = handle.read()

            if re.search(r'is_cut_str\s*=\s*"1"', content):
                raise RuntimeError(
                    "the server returned a truncated article for {}; "
                    "check that the token can access this show".format(
                        article.title
                    )
                )

            content = content.replace(
                "/assets/article/course.css",
                "https://api.vistopia.com.cn/assets/article/course.css"
            )

            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(content)

            os.replace(temporary, str(fname))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save_transcript_with_single_file(self, id: int,
                                         episodes: Optional[set] = None,
                                         single_file_exec_path: str = "",
                                         cookie_file_path: str = ""):
        import subprocess
        from pathlib import Path
        logger.debug(f"save_transcript_with_single_file id {id}")

        catalog = self.get_catalog(id)
        show_dir = Path(catalog.title)
        show_dir.mkdir(exist_ok=True)

        for part in catalog.catalog:
            for article in part.part:
                if episodes and int(article.sort_number) not in episodes:
                    continue

                fname = show_dir / "{}.html".format(
                    sanitize_filename(article.title)
                )
                if not fname.exists():
                    command = [
                        single_file_exec_path,
                        "https://www.vistopia.com.cn/article/"
                        + article.article_id,
                        str(fname),
                        "--browser-cookies-file=" + cookie_file_path
                    ]
                    logger.debug(f"singlefile command {command}")
                    try:
                        subprocess.run(command, check=True)
                        print(
                            f"Successfully fetched and saved to {fname}")
                    except subprocess.CalledProcessError as e:
                        print(f"Failed to fetch page using single-file: {e}")

    @staticmethod
    def retag(
        fname: str,
        article_info: RetagArticle,
        catalog_info: Catalog,
        series_info: RetagSeries
    ):

        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3NoHeaderError

        try:
            track = EasyID3(fname)
        except ID3NoHeaderError:
            # No ID3 tag found, creating a new ID3 tag
            # See: https://github.com/quodlibet/mutagen/issues/327
            track = EasyID3()

        track['title'] = article_info.title
        track['album'] = series_info.title
        track['artist'] = series_info.author
        track['tracknumber'] = str(article_info.sort_number)
        track['website'] = article_info.content_url

        try:
            track.save(fname)
        except Exception as e:
            print(f"Error saving ID3 tags: {e}")

    @staticmethod
    def retag_cover(fname, article_info, catalog_info: Catalog, series_info):

        from mutagen.id3 import ID3, APIC

        @lru_cache()
        def _get_cover(url: str) -> bytes:
            cover_fname, _ = urlretrieve(url)
            with open(cover_fname, "rb") as fp:
                cover = fp.read()
            urlcleanup()
            return cover

        cover = _get_cover(catalog_info.background_img)

        track = ID3(fname)
        track["APIC"] = APIC(encoding=3, mime="image/jpeg",
                             type=3, desc="Cover", data=cover)
        track.save()
