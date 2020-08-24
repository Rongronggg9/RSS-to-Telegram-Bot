import re
import json
import html2text

# re
isBrokenLink = (
    (re.compile(r'(via )?\[.+?\]\([^\)]*?$'), re.compile(r'^.*?\)')),
    (re.compile(r'(via )?\[.+?\]$'), re.compile(r'^\(.+?\)')),
    (re.compile(r'(via )?\[[^\]]*?$'), re.compile(r'^.*?\]\(.+?\)'))
)
deleteBlockquote = re.compile(r'</?blockquote>')

# html2text configuration
html2text.config.IGNORE_IMAGES = True
html2text.config.RE_MD_CHARS_MATCHER_ALL = re.compile(r'([_\*\[\]\(\)~`>#\+-=\|\{\}\.!])')
html2text.config.ESCAPE_SNOB = True
md_ize = html2text.HTML2Text()


def get_md(xml, feed_title, url, split_length=4096):
    preprocessed = deleteBlockquote.sub('', xml)
    emojified = emojify(preprocessed)
    md = md_ize.handle(emojified).strip() + f'\n\nvia [{feed_title}]({url})'
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
            for sub in isBrokenLink:
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
