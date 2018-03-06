from __future__ import unicode_literals, division, absolute_import
from builtins import *  # noqa pylint: disable=unused-import, redefined-builtin

import logging
import re

from flexget import plugin
from flexget.event import event
from flexget.plugins.internal.urlrewriting import UrlRewritingError
from flexget.utils.requests import Session, TimedLimiter
from flexget.utils.soup import get_soup

from flexget.entry import Entry
from flexget.utils.search import normalize_unicode

import unicodedata

log = logging.getLogger('tumejortorrent')

requests = Session()
requests.headers.update({'User-Agent': 'Mozilla/4.0 (compatible; MSIE 5.5; Windows NT)'})
requests.add_domain_limiter(TimedLimiter('tumejortorrent.com', '2 seconds'))

class UrlRewriteTMT(object):
    """TuMejorTorrent urlrewriter and search."""

    schema = {
        'type': 'boolean',
        'default': False
    }

    # urlrewriter API
    def url_rewritable(self, task, entry):
        url = entry['url']
        rewritable_regex = '^http:\/\/(www[.])?tumejortorrent[.]com\/.*'
        return re.match(rewritable_regex, url) and not url.endswith('.torrent')

    # urlrewriter API
    def url_rewrite(self, task, entry):
        entry['url'] = self.parse_download_page(entry['url'])

    @plugin.internet(log)
    def parse_download_page(self, url):
        log.verbose('Tumejortorrent URL: %s', url)

        try:
            page = requests.get(url)
        except requests.exceptions.RequestException as e:
            raise UrlRewritingError(e)
        try:
            text = page.text
        except Exception as e:
            raise UrlRewritingError(e)

        torrent_id = None

        torrent_id_prog = re.compile(r"http://tumejortorrent\.com/descargar-torrent/([^/\"]*)/?")
        match = torrent_id_prog.search(text)
        if match:
            torrent_id = match.group(1)

        if not torrent_id:
            raise UrlRewritingError('Unable to locate torrent ID from url %s' % url)

        url_format = 'http://tumejortorrent.com/download/{:0>6}.torrent'
        return url_format.format(torrent_id)

@event('plugin.register')
def register_plugin():
    plugin.register(UrlRewriteTMT, 'tumejortorrent', interfaces=['urlrewriter'], api_ver=2)
