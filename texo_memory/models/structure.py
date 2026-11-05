# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The passages of a long document, cut where the document itself is cut.

A law, a call for tenders or a manual converted to Markdown keeps its structure in its
headings and in its numbered paragraphs: titles, chapters, sections, articles, annexes,
commas. A passage is a piece of the text within one unit of that structure, with its path
(«TITOLO II > Art. 43 (Definizioni) > comma 2») and its place in the text, so that a search
answers with the passage and the agent cites «art. 43, comma 2», not only the document.

Only the cut is decided here: what a passage is indexed with (the title of the document
before the path, for the vectors and the full-text index) is up to who stores it. The text
of a passage is the text of the document, as it is.
"""
import re

# about this many characters per passage; a unit longer than this is cut at its commas, then
# at its paragraphs, then at its sentences, with a little overlap between the pieces
PASSAGE_CHARS = 1500
OVERLAP = 150
MAX_PASSAGES = 400

HEADING = re.compile(r'^\s{0,3}(#{1,6})\s*(.*?)\s*#*\s*$')
# the units of a legal text, from the widest; a heading or a plain line that starts with one
LEGAL = [
    (2, re.compile(r'^(?:PARTE|Parte|LIBRO|Libro|TITOLO|Titolo)\s+[IVXLC\d]+\b', re.UNICODE)),
    (2, re.compile(r'^(?:ALLEGATO|Allegato)\b(?:\s+[\w.]+)?', re.UNICODE)),
    (3, re.compile(r'^(?:CAPO|Capo)\s+[IVXLC\d]+\b', re.UNICODE)),
    (4, re.compile(r'^(?:SEZIONE|Sezione)\s+[IVXLC\d]+\b', re.UNICODE)),
    (5, re.compile(r'^(?:art\.|articolo)\s*\d+[\w-]*\.?', re.UNICODE | re.IGNORECASE)),
]
# a passage with fewer characters than this says nothing on its own («Art. 1.»)
MIN_CHARS = 20
GENERIC = 6
ARTICLE = 5
COMMA = re.compile(r'^\s*(?:-\s*)?(\d+(?:-(?:bis|ter|quater|quinquies|sexies|septies|octies))?)\.\s+\S')
SENTENCE_END = re.compile(r'(?<=[.;:!?])\s+')


def _label(text):
    """The label of a heading for a path: its words, without the dots and spaces at the end."""
    return " ".join(text.split()).rstrip(' .:')[:120]


def _heading(line, title_seen):
    """(level, label) when the line opens a unit of the structure, else None. The first Markdown
    title of the document (#) is its name, not a unit."""
    match = HEADING.match(line)
    text = match.group(2) if match else line.strip()
    if match and not text.strip('#').strip():
        return None
    if not match and len(text) > 80:
        return None  # a line of the body that happens to start with «Art. 5 del decreto...»
    for level, pattern in LEGAL:
        if pattern.match(text):
            return level, _label(text)
    if match:
        if len(match.group(1)) == 1 and not title_seen:
            return 1, _label(text)
        return GENERIC, _label(text)
    return None


def _sections(text):
    """[(path, start, end)] of the bodies of the units of the text, in order, with the offset of
    their first and past their last character."""
    sections = []
    stack = []  # [(level, label)]
    body_start, has_body, title_seen = 0, False, False
    pending_title = None  # a unit just opened, still without a body: a heading after it is its title
    offset = 0
    for line in text.splitlines(keepends=True):
        found = _heading(line, title_seen)
        if found:
            level, label = found
            if level == 1:
                title_seen = True
                if has_body:
                    sections.append((list(stack), body_start, offset))
                body_start, has_body = offset + len(line), False
                offset += len(line)
                continue
            if level == GENERIC and pending_title is not None and not has_body:
                # «## Art. 2.» then «## Definizioni»: the second is the title of the article
                lvl, lbl = stack[pending_title]
                stack[pending_title] = (lvl, f"{lbl} ({label})")
                pending_title = None
                body_start = offset + len(line)
                offset += len(line)
                continue
            if has_body:
                sections.append((list(stack), body_start, offset))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, label))
            pending_title = len(stack) - 1 if level < GENERIC else None
            body_start, has_body = offset + len(line), False
        elif line.strip():
            has_body = True
            pending_title = None
        offset += len(line)
    if has_body:
        sections.append((list(stack), body_start, len(text)))
    return sections


def _cut(text, start, end, size, overlap):
    """[(start, end)] of pieces of text[start:end] of about size characters, cut at a paragraph,
    else after a sentence, else at a space, each after the first starting overlap characters
    before the end of the previous one."""
    pieces = []
    while end - start > size:
        window = text[start:start + size]
        cut = next((at for at in (window.rfind('\n\n'), window.rfind('\n'),
                                  max((m.start() for m in SENTENCE_END.finditer(window)), default=-1),
                                  window.rfind(' ')) if at >= size // 2), size)
        pieces.append((start, start + cut))
        start = max(start + cut - overlap, start + 1)
        # the overlap starts at a word
        space = text.find(' ', start, start + overlap)
        if space != -1:
            start = space + 1
    pieces.append((start, end))
    return pieces


def _commas(text, start, end):
    """[(label, start, end)] of the commas of an article body (lines «1. ...», «2-bis. ...»); the
    lines before the first comma go with it. [] when the body has fewer than two."""
    marks = []
    offset = start
    for line in text[start:end].splitlines(keepends=True):
        match = COMMA.match(line)
        if match:
            marks.append((match.group(1), offset))
        offset += len(line)
    if len(marks) < 2:
        return []
    units = []
    for index, (label, at) in enumerate(marks):
        unit_start = start if index == 0 else at
        unit_end = marks[index + 1][1] if index + 1 < len(marks) else end
        units.append((label, unit_start, unit_end))
    return units


def _join(path):
    return " > ".join(label for _level, label in path)


def passages(text, size=PASSAGE_CHARS, overlap=OVERLAP, limit=MAX_PASSAGES):
    """[{path, start, end, text}] of the passages of text, in order, at most limit. A unit that
    fits is one passage; an article too long is cut at its commas (consecutive commas together
    while they fit, «commi 1-3»); what is still too long is cut at paragraphs and sentences
    («(segue)» in the path of the pieces after the first). A text without structure is cut
    the same way, with an empty path."""
    text = text or ''
    out = []

    def add(path, start, end):
        piece = text[start:end].strip()
        if len(piece) >= MIN_CHARS and len(out) < limit:
            out.append({'path': path, 'start': start, 'end': end, 'text': piece})

    def add_cut(path, start, end):
        for index, (piece_start, piece_end) in enumerate(_cut(text, start, end, size, overlap)):
            add(f"{path} (segue)" if index and path else path, piece_start, piece_end)

    for stack, start, end in _sections(text):
        if len(out) >= limit:
            break
        path = _join(stack)
        if end - start <= size:
            add(path, start, end)
            continue
        units = _commas(text, start, end) if stack and stack[-1][0] == ARTICLE else []
        if not units:
            add_cut(path, start, end)
            continue
        group = []
        for unit in units + [None]:
            if unit and group and unit[2] - group[0][1] <= size:
                group.append(unit)
                continue
            if group:
                first, last = group[0], group[-1]
                label = f"comma {first[0]}" if len(group) == 1 else f"commi {first[0]}-{last[0]}"
                if last[2] - first[1] <= size:
                    add(f"{path} > {label}", first[1], last[2])
                else:
                    add_cut(f"{path} > {label}", first[1], last[2])
            group = [unit] if unit else []
    return out
