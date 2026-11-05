# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The quotes of a card are checked against the page they come from, when the card is written:
a quote that is not in the text, word for word, is refused (the idea comes from CaseCite, which
drops a citation it cannot find in its source). The page is read for the check and not kept."""
import re

import requests
from lxml import html as lxml_html

from .memory_source_feed import MAX_BYTES, TIMEOUT, USER_AGENT

# a quote is what stands between «», “”, or straight double quotes
QUOTED = re.compile(r'«([^»]+)»|“([^”]+)”|"([^"]+)"')
FOLD = str.maketrans({'’': "'", '‘': "'", '`': "'", '–': '-', '—': '-', ' ': ' '})


def quoted(text):
    """The quoted passages of a text, in order."""
    return [next(g for g in match.groups() if g) for match in QUOTED.finditer(text or '')]


def fold(text):
    """Lower case, one kind of apostrophe and dash, single spaces: how two copies of the same
    words are compared."""
    return " ".join((text or '').translate(FOLD).lower().split())


def page_text(url):
    """The visible text of a web page, without scripts and styles; raises requests.RequestException."""
    with requests.get(url, timeout=TIMEOUT, stream=True, headers={'User-Agent': USER_AGENT}) as answer:
        answer.raise_for_status()
        content = answer.raw.read(MAX_BYTES, decode_content=True)
    tree = lxml_html.fromstring(content)
    for node in tree.xpath('//script|//style|//noscript'):
        node.drop_tree()
    return tree.text_content()


def missing_quotes(quotes, text):
    """The quoted passages of quotes that are not in text, word for word (case and spacing aside)."""
    haystack = fold(text)
    return [q for q in quoted(quotes) if fold(q) not in haystack]
