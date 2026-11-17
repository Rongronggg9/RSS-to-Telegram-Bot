import pytest
from telethon.extensions.html import unparse
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityItalic,
    MessageEntityPre,
    MessageEntityTextUrl,
)

from src.parsing import splitter


def _spans(entities):
    return [(type(e).__name__, e.offset, e.length) for e in entities]


@pytest.mark.parametrize('html, expected', [
    ('', 0),
    ('plain text', 10),
    ('<b>Hello &amp; world!</b>', 14),
    ('<p>a</p><a href="https://example.com">link</a>', 5),
])
def test_get_plain_text_length(html, expected):
    assert splitter.get_plain_text_length(html) == expected


def test_split_entities_partitions_and_splits_straddling_entity():
    before_only = MessageEntityBold(0, 3)
    straddling = MessageEntityTextUrl(2, 6, url='https://example.com')
    after_only = MessageEntityItalic(9, 2)

    before, after = splitter.split_entities(5, [before_only, straddling, after_only])

    assert _spans(before) == [
        ('MessageEntityBold', 0, 3),
        ('MessageEntityTextUrl', 2, 3),
    ]
    assert before[1].url == 'https://example.com'
    assert _spans(after) == [
        ('MessageEntityTextUrl', 5, 3),
        ('MessageEntityItalic', 9, 2),
    ]
    assert after[0].url == 'https://example.com'
    # Input entities must not be mutated in place
    assert (straddling.offset, straddling.length) == (2, 6)


def test_split_text_respects_queue_and_separators():
    assert splitter.split_text('') == []
    assert splitter.split_text('short', length_limit_tail=10) == ['short']

    text = 'First sentence. Second sentence is longer than the first one.'
    chunks = splitter.split_text(text, length_limit_queue=[20], length_limit_tail=30)
    assert chunks == [
        'First sentence. ',
        'Second sentence is longer ',
        'than the first one.',
    ]
    assert ''.join(chunks) == text


def test_is_entities_within_limit_checks_count_and_byte_budget():
    assert splitter.is_entities_within_limit([])
    assert splitter.is_entities_within_limit([MessageEntityBold(i * 2, 1) for i in range(100)])
    assert not splitter.is_entities_within_limit([MessageEntityBold(i * 2, 1) for i in range(101)])

    long_url = 'https://example.com/' + ('a' * 1000)
    oversized_entities = [MessageEntityTextUrl(i * 2, 1, url=long_url) for i in range(10)]
    assert not splitter.is_entities_within_limit(oversized_entities)


def test_html_to_telegram_split_single_chunk_merges_and_strips():
    chunks = splitter.html_to_telegram_split('  <b>Hello</b><b> world</b>  ')
    assert len(chunks) == 1
    text, entities = chunks[0]
    assert text == 'Hello world'
    assert _spans(entities) == [('MessageEntityBold', 0, 11)]


def test_html_to_telegram_split_respects_head_and_tail_limits():
    html = (
        '<b>First paragraph</b> with a sentence.\n'
        '<i>Second paragraph with a much longer body that fits in the tail limit.</i>'
    )
    chunks = splitter.html_to_telegram_split(
        html,
        length_limit_head=45,
        head_count=1,
        length_limit_tail=120,
    )
    assert len(chunks) == 2
    first_text, first_entities = chunks[0]
    second_text, second_entities = chunks[1]

    assert len(first_text) <= 45
    assert first_text == 'First paragraph with a sentence.'
    assert _spans(first_entities) == [('MessageEntityBold', 0, 15)]

    assert second_text == 'Second paragraph with a much longer body that fits in the tail limit.'
    assert _spans(second_entities) == [('MessageEntityItalic', 0, len(second_text))]


def test_html_to_telegram_split_rebases_entities_across_utf16_surrogates():
    # Each emoji outside the BMP takes 2 UTF-16 code units in Telegram entity offsets
    html = 'Lead \U0001f600\U0001f600 <b>bold across middle chunk and into third chunk</b>'
    chunks = splitter.html_to_telegram_split(html, length_limit_head=25, length_limit_tail=25)

    assert len(chunks) == 3
    rendered = [unparse(text, entities) for text, entities in chunks]
    assert rendered == [
        'Lead \U0001f600\U0001f600 <strong>bold across</strong>',
        '<strong>middle chunk and into</strong>',
        '<strong>third chunk</strong>',
    ]


def test_text_and_format_entities_split_raises_when_unable_to_make_progress():
    with pytest.raises(RuntimeError, match='Stuck while splitting'):
        splitter.text_and_format_entities_split('non-empty', [], length_limit_head=0, length_limit_tail=0)


def test_html_to_telegram_split_steps_down_when_entity_count_exceeds_limit():
    # Over 100 entities inside a short message must force a split even when len(text) < limit
    html = ' '.join(f'<b>w{i}</b>' for i in range(120))
    chunks = splitter.html_to_telegram_split(html, length_limit_head=4096, length_limit_tail=4096)

    assert len(chunks) >= 2
    for text, entities in chunks:
        assert text
        assert splitter.is_entities_within_limit(entities)


def test_text_and_format_entities_concat_roundtrips_split_entity():
    chunks = [
        ('Hello \U0001f600 ', [MessageEntityPre(6, 3, language='py')]),
        ('world', [MessageEntityPre(0, 5, language='py')]),
    ]
    text, entities = splitter.text_and_format_entities_concat(*chunks)
    assert text == 'Hello \U0001f600 world'
    assert _spans(entities) == [('MessageEntityPre', 6, 8)]
    assert entities[0].language == 'py'
