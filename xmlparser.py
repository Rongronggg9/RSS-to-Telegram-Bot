import re
import json
import html2text
from bs4 import BeautifulSoup

# re
isBrokenDivision = (
    (re.compile(r'((via )|(via)|(vi)|(v))$'), re.compile(r'^((ia )|(a )|( )|(\[))')),
    (re.compile(r'(via )?\[.+?\]\([^\)]*?$'), re.compile(r'^.*?\)')),
    (re.compile(r'(via )?\[.+?\]$'), re.compile(r'^\(.+?\)')),
    (re.compile(r'(via )?\[[^\]]*?$'), re.compile(r'^.*?\]\(.+?\)')),
    (re.compile(r'(\\|\\\\)$'), re.compile(r'^.*'))
)
deleteTags = ('hr', 'blockquote')

# html2text configuration
html2text.config.RE_MD_CHARS_MATCHER_ALL = re.compile(r'([\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!])')
md_ize = html2text.HTML2Text()
md_ize.body_width = 0
md_ize.strong_mark = '*'
md_ize.ul_item_mark = '•'
md_ize.emphasis_mark = '__'
md_ize.ignore_images = True
md_ize.ignore_tables = True
md_ize.escape_snob = True
md_ize.use_automatic_links = False

# load emoji dict
with open('emojify.json', 'r', encoding='utf-8') as emojify_json:
    emoji_dict = json.load(emojify_json)


def get_media(xml):
    soup = BeautifulSoup(xml, 'html.parser')
    video = None
    if soup.video:
        video = soup.video['src']
    pics = [img['src'] for img in soup('img')]

    return video, pics


def preprocess(xml):
    soup = BeautifulSoup(xml, 'html.parser')
    for d in soup(deleteTags):  # delete unsupported tags
        d.unwrap()
    for pre in soup('pre'):  # code block
        pre.code.unwrap()
        pre.unwrap()
    for hn in soup(re.compile(r'h\d')):  # replace <h*> with <b><i>
        hn.name = 'i'
        hn.wrap(soup.new_tag('b'))
    return soup.decode(formatter=None)


def emojify(xml):  # note: get all emoticons on https://api.weibo.com/2/emotions.json?source=1362404091
    for emoticon, emoji in emoji_dict.items():
        xml = xml.replace(f'[{emoticon}]', emoji)
    return xml


def get_md(xml, feed_title, url, split_length=4096):
    preprocessed = preprocess(xml)
    emojified = emojify(preprocessed)
    via = md_ize.handle(f'via <a href="{url}">{feed_title}</a>').strip()  # escape 'via [feed_title](post_url)'
    md = md_ize.handle(emojified).strip() + f'\n\n{via}'
    return split_text(md, split_length)


def split_text(text, length):
    length -= length % 100  # generally, length should be 1024 or 4096, preventatively reduced

    if len(text) <= length:
        return [text]

    else:
        result = []
        latter = text
        while True:
            former = latter[:length]
            latter = latter[length:]
            for sub in isBrokenDivision:
                if sub[0].search(former) and sub[1].search(latter):
                    latter = sub[0].search(former).group(0) + latter
                    former = sub[0].sub('', former)
                    break
            result.append(former.strip('\n'))
            if len(latter) <= length:
                result.append(latter.strip('\n'))
                break
            if length == 1000:  # media message only
                length = 4000
    return result


if __name__ == '__main__':
    import feedparser

    _url = input('Please input an RSS feed: ')
    test_d = feedparser.parse(_url)
    print(f'Got {len(test_d.entries)} post(s).')
    index = int(input('Please input post index: '))
    _xml = test_d.entries[index]['summary']
    print(get_media(_xml))
    print(repr(get_md(_xml, test_d.feed.title, _url)))
