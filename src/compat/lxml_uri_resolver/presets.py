#  RSS to Telegram Bot
#  Copyright (C) 2025  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

# Collected from:
# - https://github.com/kurtmckee/feedparser/blob/6cdc20849a66c29e2d08b0334fceb22f210bdb26/feedparser/urls.py#L39-L47
# - https://docs.python.org/3.12/library/urllib.parse.html
# - https://docs.python.org/3.12/library/urllib.parse.html
ACCEPTABLE_URI_SCHEMES: set[str] = {
    'acap',
    'aim',
    'callto',
    'cvs',
    'facetime',
    'feed',
    'file',
    'ftp',
    'git',
    'gopher',
    'gtalk',
    'h323',
    'hdl',
    'http',
    'https',
    'icap',
    'imap',
    'irc',
    'irc6',
    'ircs',
    'itms',
    'magnet',
    'mailto',
    'mms',
    'msnim',
    'mtqp',
    'news',
    'nntp',
    'prospero',
    'rsync',
    'rtsp',
    'rtspsrtspu',
    'sftp',
    'shttp',
    'sip',
    'sips',
    'skype',
    'smb',
    'snews',
    'ssh',
    'svn',
    'svn+ssh',
    'telnet',
    'wais',
    'ws',
    'wss',
    'ymsg',
}

# Collected from:
# - https://github.com/kurtmckee/feedparser/blob/6cdc20849a66c29e2d08b0334fceb22f210bdb26/feedparser/urls.py#L107-L137
TAG_ATTR_MAP: dict[str, set[str]] = {
    'a': {'href'},
    'applet': {'codebase'},
    'area': {'href'},
    'audio': {'src'},
    'blockquote': {'cite'},
    'body': {'background'},
    'del': {'cite'},
    'form': {'action'},
    'frame': {'longdesc', 'src'},
    'head': {'profile'},
    'iframe': {'longdesc', 'src'},
    'img': {'longdesc', 'src', 'usemap'},
    'input': {'src', 'usemap'},
    'ins': {'cite'},
    'link': {'href'},
    'object': {'classid', 'codebase', 'data', 'usemap'},
    'q': {'cite'},
    'script': {'src'},
    'source': {'src'},
    'video': {'poster', 'src'},
}

TAG_ATTR_MAP_RSSTT: dict[str, set[str]] = {
    'a': {'href'},
    'audio': {'src'},
    'iframe': {'src'},
    'img': {'src'},
    'q': {'cite'},
    'source': {'src'},
    'video': {'poster', 'src'},
}
