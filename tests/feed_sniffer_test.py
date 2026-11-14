import pytest

from src import env
from src.command.inner import sub as sub_module


@pytest.fixture(autouse=True)
def _clear_sniffer_cache():
    sub_module.FeedSnifferCache.clear()
    yield
    sub_module.FeedSnifferCache.clear()


def test_feed_sniffer_prefers_explicit_alternate_link():
    html = (
        '<html><head>'
        '<link rel="alternate" type="application/rss+xml" href="/custom.xml" />'
        '<link rel="stylesheet" href="https://example.com/wp-content/themes/main/style.css" />'
        '</head><body></body></html>'
    )
    result = env.loop.run_until_complete(sub_module.feed_sniffer('https://example.com/', html))
    assert result == 'https://example.com/custom.xml'


@pytest.mark.parametrize('url, html, expected', [
    (
        'https://finland.fi/',
        '<html><head><link rel="shortcut icon" href="https://finland.fi/wp-content/themes/t/fav.ico"/></head></html>',
        'https://finland.fi/feed',
    ),
    (
        'https://finland.fi',
        '<html><head><link rel="https://api.w.org/" href="https://finland.fi/wp-json/" /></head></html>',
        'https://finland.fi/feed',
    ),
    (
        'https://finland.fi/zh/?utm_source=test#top',
        '<html><head><link rel="stylesheet" href="/wp-includes/css/dist/block-library/style.min.css" /></head></html>',
        'https://finland.fi/zh/feed',
    ),
])
def test_feed_sniffer_falls_back_to_wordpress_feed_endpoint(url, html, expected):
    result = env.loop.run_until_complete(sub_module.feed_sniffer(url, html))
    assert result == expected
    assert sub_module.FeedSnifferCache[url] == expected


def test_feed_sniffer_does_not_append_feed_twice():
    html = '<html><head><link rel="stylesheet" href="https://example.com/wp-content/themes/a/s.css"/></head></html>'
    assert env.loop.run_until_complete(sub_module.feed_sniffer('https://example.com/feed', html)) is None
    assert env.loop.run_until_complete(sub_module.feed_sniffer('https://example.com/feed/', html)) is None


def test_feed_sniffer_returns_none_for_non_wordpress_page_without_feed_links():
    html = '<html><head><link rel="stylesheet" href="/static/app.css" /></head><body><a href="/about">About</a></body></html>'
    assert env.loop.run_until_complete(sub_module.feed_sniffer('https://example.com/', html)) is None
