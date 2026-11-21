import pytest

from src import env
from src.parsing import html_parser
from src.parsing.medium import Animation, Audio, Image, Video

FEED_LINK = 'https://example.com/feed/'


def _parse(html, feed_link=FEED_LINK):
    return env.loop.run_until_complete(html_parser.parse(html, feed_link))


def _media(parsed):
    return [(type(medium), medium.original_urls) for medium in parsed.media._media]


@pytest.mark.parametrize('html, expected', [
    ('<p>a</p><p>b</p>', 'a\n\nb'),
    ('<div>a</div><div>b</div>', 'a\nb'),
    ('x<br>y', 'x\ny'),
    ('a<hr>b', 'a\n\n----------------------\nb'),
    ('<b>x</b> <strong>y</strong> <i>i</i> <em>e</em> <u>u</u> <ins>n</ins>',
     '<b>x</b> <b>y</b> <i>i</i> <i>e</i> <u>u</u> <u>n</u>'),
    ('<h1>T</h1>text', '<b><u>T</u></b>\ntext'),
    ('<h2>T</h2>text', '<b>T</b>\ntext'),
    ('<h3>T</h3>text', '<u>T</u>\ntext'),
    ('<script>alert(1)</script>ok', 'ok'),
    ('<span>unknown <font>tags</font> keep their text</span>', 'unknown tags keep their text'),
])
def test_text_formatting(html, expected):
    assert _parse(html).html == expected


@pytest.mark.parametrize('html, expected', [
    # relative links are resolved against the feed link
    ('<a href="/p/1">rel</a>', '<a href="https://example.com/p/1">rel</a>'),
    ('<a href="https://other.example/">abs</a>', '<a href="https://other.example/">abs</a>'),
    # links Telegram can't open are shown next to the text instead
    ('<a href="mailto:x@y.z">mail</a>', 'mail (<code>mailto:x@y.z</code>)'),
    ('<a href="javascript:void(0)">js</a>', 'js'),
    # a link without a target or text is dropped
    ('<a href="">empty</a>', ''),
    ('<a href="/p/1"></a>', ''),
])
def test_links(html, expected):
    assert _parse(html).html == expected


@pytest.mark.parametrize('html, expected', [
    ('<ul><li>a</li><li>b</li></ul>', '<b>● </b>a\n<b>● </b>b'),
    ('<ol><li>a</li><li><p>b</p></li></ol>', '<b>1. </b>a\n<b>2. </b>b'),
    # a stray <li> still gets its own line
    ('<li>stray</li>', '<b>● </b>stray'),
    ('<ul><li> </li></ul>', ''),
])
def test_lists(html, expected):
    assert _parse(html).html == expected


@pytest.mark.parametrize('html, expected', [
    ('<blockquote><p>q</p></blockquote>', '<blockquote>q</blockquote>'),
    ('<blockquote> </blockquote>', ''),
    ('<q>q</q>', '“q”'),
    ('<q cite="https://c.example/">q</q>', '“<a href="https://c.example/">q</a>”'),
    ('<pre><code class="language-py">x = 1</code></pre>', '<pre><code class="language-py">x = 1</code></pre>'),
    # a language-* class is the code language, whatever other classes come with it
    ('<code class="highlight language-py">x</code>', '<code class="language-py">x</code>'),
    # a lone bare class names the language
    ('<code class="py">x</code>', '<code class="language-py">x</code>'),
    # several classes and none of them language-* is ambiguous
    ('<code class="highlight other">x</code>', '<code>x</code>'),
    ('<code>c</code>', '<code>c</code>'),
])
def test_quotes_and_code(html, expected):
    assert _parse(html).html == expected


def test_single_row_table_is_flattened():
    assert _parse('<table><tr><td>a</td><td>b</td></tr></table>').html == 'a\n\nb'


def test_single_column_table_is_flattened():
    assert _parse('<table><tr><td>a</td></tr><tr><td>b</td></tr></table>').html == 'a\n\nb'


def test_real_table_is_dropped_without_table_to_image(monkeypatch):
    monkeypatch.setattr(env, 'TABLE_TO_IMAGE', False)
    parsed = _parse('<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>')
    assert parsed.html == ''
    assert _media(parsed) == []


@pytest.mark.parametrize('html, expected', [
    ('<img src="/a.png">', [(Image, ('https://example.com/a.png',))]),
    ('<img src="a.gif">', [(Animation, ('https://example.com/feed/a.gif',))]),
    # the widest srcset candidate comes first, src is the last fallback
    ('<img srcset="s.jpg 100w, l.jpg 800w" src="d.jpg">', [(Image, (
        'https://example.com/feed/l.jpg',
        'https://example.com/feed/s.jpg',
        'https://example.com/feed/d.jpg',
    ))]),
    ('<img srcset="a.jpg 1x, b.jpg 2x">', [(Image, (
        'https://example.com/feed/b.jpg',
        'https://example.com/feed/a.jpg',
    ))]),
    ('<img alt="no source">', []),
    ('<video poster="p.jpg"><source src="v.mp4"></video>', [(Video, ('https://example.com/feed/v.mp4',))]),
    ('<audio src="a.mp3"></audio>', [(Audio, ('https://example.com/feed/a.mp3',))]),
])
def test_media_is_collected(html, expected):
    parsed = _parse(html)
    assert parsed.html == ''
    assert _media(parsed) == expected


def test_duplicate_images_are_added_once():
    parsed = _parse('<img src="/a.png"><p>text</p><img src="https://example.com/a.png">')
    assert parsed.html == 'text'
    assert _media(parsed) == [(Image, ('https://example.com/a.png',))]


def test_emoticon_image_becomes_its_alt_text():
    parsed = _parse('hi <img class="emoji" alt="\U0001f600" src="https://s.w.org/images/core/emoji/1.png">')
    assert parsed.html == 'hi \U0001f600'
    assert _media(parsed) == []


def test_iframe_becomes_a_link(monkeypatch):
    # with TRAFFIC_SAVING the title is the host name, so no request is made
    monkeypatch.setattr(env, 'TRAFFIC_SAVING', True)
    parsed = _parse('<iframe src="https://video.example/embed/1"></iframe>')
    assert parsed.html == '<a href="https://video.example/embed/1">iframe (video.example)</a>'


def test_get_parsed_html_needs_parse_first():
    parser = html_parser.Parser('<p>a</p>')
    with pytest.raises(RuntimeError):
        parser.get_parsed_html()
