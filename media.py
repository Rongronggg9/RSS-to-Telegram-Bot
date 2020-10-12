from urllib import request
import xmlparser
import re

# getPic = re.compile(r'<img[^>]*\bsrc="([^"]*)"')
# getVideo = re.compile(r'<video[^>]*\bsrc="([^"]*)"')
getSize = re.compile(r'^Content-Length: (\d+)$', re.M)
sizes = ['large', 'mw2048', 'mw1024', 'mw720', 'middle']
sizeParser = re.compile(r'(^https?://\w+\.sinaimg\.\S+/)(large|mw2048|mw1024|mw720|middle)(/\w+\.\w+$)')

def get_valid_media(xml):
    video, pics = xmlparser.get_media(xml)
    if video:
        video = validate_medium(video, 20971520)
    if pics:
        pics = validate_media(pics)
    return video, pics


def get_pic_info(url):
    urlopen = request.urlopen(url)
    headers = urlopen.info()
    pic_header = urlopen.read(256)

    size = int(getSize.search(str(headers)).group(1))

    height = width = -1
    if url.find('jpg') == -1 and url.find('jpeg') == -1:  # only for jpg
        return size, width, height

    pointer = -1
    for marker in (b'\xff\xc2', b'\xff\xc1', b'\xff\xc0'):
        p = pic_header.find(marker)
        if p != -1:
            pointer = p
    if pointer != -1:
        width = int(pic_header[pointer + 7:pointer + 9].hex(), 16)
        height = int(pic_header[pointer + 5:pointer + 7].hex(), 16)

    return size, width, height


def validate_medium(url, max_size=5242880):  # warning: only design for weibo
    max_size -= max_size % 1000
    try:
        size, width, height = get_pic_info(url)
    except:
        print('\t\t- Get Medium failed, dropped.\n'
              f'\t\t\t- {url}')
        return None

    if size > max_size or width + height > 10000:
        if sizeParser.search(url):  # is a large weibo pic
            parsed = sizeParser.search(url).groups()
            if parsed[1] == sizes[-1]:
                print('\t\t- Medium too large, dropped: reduced, but still too large.\n'
                      f'\t\t\t- {url}')
                return None
            reduced = parsed[0] + sizes[sizes.index(parsed[1]) + 1] + parsed[2]
            return validate_medium(reduced)
        else:  # TODO: reduce non-weibo pic size
            print('\t\t- Medium too large, dropped: non-weibo medium.\n'
                  f'\t\t\t- {url}')
            return None

    return url


def validate_media(media):  # reduce pic size to <5MB
    reduced_pics = []
    for url in media:
        reduced = validate_medium(url)
        if reduced:  # warning: too large non-weibo pic will be discarded
            reduced_pics.append(reduced)
    return reduced_pics
