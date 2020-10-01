import re
import json
import html2text

# re
isBrokenDivision = (
    (re.compile(r'((via )|(via)|(vi)|(v))$'), re.compile(r'^((ia )|(a )|( )|(\[))')),
    (re.compile(r'(via )?\[.+?\]\([^\)]*?$'), re.compile(r'^.*?\)')),
    (re.compile(r'(via )?\[.+?\]$'), re.compile(r'^\(.+?\)')),
    (re.compile(r'(via )?\[[^\]]*?$'), re.compile(r'^.*?\]\(.+?\)')),
    (re.compile(r'(\\|\\\\)$'), re.compile(r'^.*'))
)
deleteBlockquote = re.compile(r'</?blockquote>')
deleteHr = re.compile(r'<hr ?/?>')
isHn = (re.compile(r'<h\d>'), re.compile(r'</h\d>'))

# html2text configuration
html2text.config.RE_MD_CHARS_MATCHER_ALL = re.compile(r'([\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!])')
md_ize = html2text.HTML2Text()
md_ize.body_width = 0
md_ize.strong_mark = '*'
md_ize.ul_item_mark = '•'
md_ize.emphasis_mark = "__"
md_ize.ignore_images = True
md_ize.ignore_tables = True
md_ize.escape_snob = True
md_ize.use_automatic_links = False


def preprocess(xml):
    result = xml
    delete = (deleteHr, deleteBlockquote)
    for d in delete:
        result = d.sub('', result)
    for i in range(2):
        result = isHn[i].sub(f'{"<u><b>" * (1-i) }{"</b></u>" * i}', result)
    return result


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


def emojify(xml):  # note: get all emoticons on https://api.weibo.com/2/emotions.json?source=1362404091
    for emoticon, emoji in emoji_dict.items():
        xml = xml.replace(f'[{emoticon}]', emoji)
    return xml


with open('emojify.json', 'r', encoding='utf-8') as emojify_json:
    emoji_dict = json.load(emojify_json)

if __name__ == '__main__':
    import feedparser
    url = input('Please input an RSS feed:')
    d = feedparser.parse(url)
    text = d.entries[0]['summary']
    preprocessed = preprocess(text)
    print(preprocessed)
    print(repr(md_ize.handle(preprocessed)))
