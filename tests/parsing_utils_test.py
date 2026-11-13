import base64
from io import BytesIO

import pytest
from PIL import Image
from telethon.tl.types import MessageEntityBold, MessageEntityItalic, MessageEntityTextUrl

from src.parsing import utils


def _png_data_uri(width: int, height: int) -> str:
    buf = BytesIO()
    Image.new('RGB', (width, height)).save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def _spans(entities):
    return [(type(e).__name__, e.offset, e.length) for e in entities]


@pytest.mark.parametrize('s, expected', [
    ('', 0),
    ('abc', 3),
    ('\U0001f600', 2),  # outside the BMP, so it takes a surrogate pair in UTF-16
    ('a\U0001f600b', 4),
])
def test_surrogate_len(s, expected):
    assert utils.surrogate_len(s) == expected


@pytest.mark.parametrize('base, url, expected', [
    ('https://example.com/a/b/', 'c.png', 'https://example.com/a/b/c.png'),
    ('https://example.com/a/b/', '../c.png', 'https://example.com/a/c.png'),
    ('https://example.com/a/', '/c.png', 'https://example.com/c.png'),
    ('https://example.com/a/', 'https://cdn.example.org/c.png', 'https://cdn.example.org/c.png'),
    (None, 'c.png', 'c.png'),
    ('https://example.com/', None, ''),
    ('not a link', 'c.png', 'c.png'),
])
def test_resolve_relative_link(base, url, expected):
    assert utils.resolve_relative_link(base, url) == expected


def test_escape_hashtags():
    assert utils.escape_hashtag('foo bar-baz') == 'foo_bar_baz'
    assert list(utils.escape_hashtags(['a b', '', 'c'])) == ['a_b', 'c']
    assert list(utils.escape_hashtags(None)) == []


def test_merge_tags_keeps_order_and_drops_duplicates():
    assert utils.merge_tags(['a', 'b'], ['b', 'c'], ()) == ['a', 'b', 'c']


def test_decode_data_uri_image():
    data, ext = utils.decode_data_uri_image(_png_data_uri(64, 48))
    with Image.open(BytesIO(data)) as image:
        size = image.size
    assert ext == 'png'
    assert size == (64, 48)


@pytest.mark.parametrize('src', [
    'https://example.com/a.png',
    'data:image/png;base64,not-base64!',
    'data:text/plain;base64,aGVsbG8=',
])
def test_decode_data_uri_image_rejects_non_images(src):
    assert utils.decode_data_uri_image(src) is None


def test_decode_data_uri_image_rejects_emoticon_sized_images():
    assert utils.decode_data_uri_image(_png_data_uri(utils.EMOTICON_MAX_SIZE, 64)) is None


def test_entity_position_filters():
    bold, italic = MessageEntityBold(0, 3), MessageEntityItalic(5, 2)
    assert utils.filter_entities_by_position(2, [bold, italic]) == [bold]
    assert utils.filter_entities_by_position(3, [bold, italic]) == []
    assert utils.filter_entities_by_range(4, 10, [bold, italic]) == [italic]


def test_copy_entity_is_independent():
    original = MessageEntityTextUrl(1, 2, url='https://example.com')
    copy = utils.copy_entity(original)
    copy.offset = 10
    assert (original.offset, copy.url) == (1, 'https://example.com')


def test_compare_entity():
    assert utils.compare_entity(MessageEntityBold(0, 3), MessageEntityBold(0, 3))
    assert not utils.compare_entity(MessageEntityBold(0, 3), MessageEntityItalic(0, 3))
    assert not utils.compare_entity(MessageEntityBold(0, 3), MessageEntityBold(1, 3))
    assert utils.compare_entity(MessageEntityBold(0, 3), MessageEntityBold(1, 3), ignore_position=True)
    assert not utils.compare_entity(MessageEntityTextUrl(0, 3, url='https://a'),
                                    MessageEntityTextUrl(0, 3, url='https://b'), ignore_position=True)


def test_sort_entities_sorts_and_drops_duplicates():
    entities = [MessageEntityItalic(5, 1), MessageEntityBold(0, 3), MessageEntityBold(0, 3)]
    assert _spans(utils.sort_entities(entities)) == [('MessageEntityBold', 0, 3), ('MessageEntityItalic', 5, 1)]


def test_merge_contiguous_entities():
    entities = [MessageEntityBold(0, 3), MessageEntityItalic(1, 2), MessageEntityBold(3, 2), MessageEntityBold(8, 1)]
    assert _spans(utils.merge_contiguous_entities(entities)) == [
        ('MessageEntityBold', 0, 5),
        ('MessageEntityItalic', 1, 2),
        ('MessageEntityBold', 8, 1),
    ]


def test_merge_contiguous_entities_keeps_different_urls_apart():
    entities = [MessageEntityTextUrl(0, 3, url='https://a'), MessageEntityTextUrl(3, 3, url='https://b')]
    assert _spans(utils.merge_contiguous_entities(entities)) == [
        ('MessageEntityTextUrl', 0, 3),
        ('MessageEntityTextUrl', 3, 3),
    ]


def test_merge_contiguous_entities_chains_and_absorbs():
    entities = [MessageEntityBold(4, 2), MessageEntityBold(0, 2), MessageEntityBold(2, 2), MessageEntityBold(1, 1)]
    assert _spans(utils.merge_contiguous_entities(entities)) == [('MessageEntityBold', 0, 6)]


def test_merge_contiguous_entities_does_not_touch_input():
    first, second = MessageEntityBold(0, 3), MessageEntityBold(3, 2)
    utils.merge_contiguous_entities([first, second])
    assert (first.offset, first.length, second.offset, second.length) == (0, 3, 3, 2)
