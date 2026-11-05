# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.tests import BaseCase, tagged

from ..models import structure
from .common import MemoryCase

LAW = """# D.Lgs. di prova, testo vigente

Fonte: una gazzetta di prova

## TITOLO I
## DISPOSIZIONI GENERALI

## Art. 1.
## Oggetto
1. Il presente decreto disciplina la progettazione delle opere.

## Art. 2.
## Definizioni
1. Ai fini del presente decreto si intende per progettista il tecnico incaricato.
2. Si intende per sopralluogo la visita sul posto prima del progetto.

## CAPO II
## Art. 43.
## Metodi e strumenti digitali
1. {long1}
2. Le stazioni appaltanti adottano il fascicolo informativo con codice XQ7781 per ogni opera.
3. {long3}
"""


def law():
    return LAW.format(long1="Le stazioni appaltanti adottano metodi di gestione informativa. " * 15,
                      long3="Il piano di gestione informativa accompagna il progetto esecutivo. " * 15)


@tagged('post_install', '-at_install')
class TestStructure(BaseCase):

    def test_the_path_follows_the_structure_of_the_act(self):
        passages = structure.passages(law())
        paths = [p['path'] for p in passages]
        self.assertEqual(paths[0], '', "the lines before the first unit, under the title of the document")
        self.assertIn('TITOLO I (DISPOSIZIONI GENERALI) > Art. 1 (Oggetto)', paths)
        self.assertIn('TITOLO I (DISPOSIZIONI GENERALI) > Art. 2 (Definizioni)', paths, "a short article is one passage")
        # a long article is cut at its commas: the chapter replaces nothing above the title
        self.assertIn('TITOLO I (DISPOSIZIONI GENERALI) > CAPO II > Art. 43 (Metodi e strumenti digitali) > commi 1-2',
                      paths)
        self.assertTrue(any(p.endswith('Art. 43 (Metodi e strumenti digitali) > comma 3') for p in paths))
        text = law()
        for passage in passages:
            self.assertEqual(text[passage['start']:passage['end']].strip(), passage['text'])
            self.assertLessEqual(len(passage['text']), structure.PASSAGE_CHARS)

    def test_a_text_without_structure_is_cut_at_its_paragraphs(self):
        text = "\n\n".join(f"Paragrafo {n}. " + "parola " * 60 for n in range(10))
        passages = structure.passages(text, size=500, limit=3)
        self.assertEqual(len(passages), 3)
        self.assertTrue(passages[0]['text'].startswith("Paragrafo 0."))
        self.assertTrue(all(len(p['text']) <= 500 for p in passages))
        self.assertEqual(structure.passages("  "), [])
        self.assertEqual(structure.passages("Un testo breve, senza titoli."),
                         [{'path': '', 'start': 0, 'end': 29, 'text': "Un testo breve, senza titoli."}])

    def test_a_line_of_the_body_is_not_a_heading(self):
        text = ("## Art. 5.\nArticolo 3 del decreto legislativo citato in premessa: si applica anche alle opere minori.\n"
                "Art. 7\nRinvio alle norme generali dello Stato.\n")
        paths = [p['path'] for p in structure.passages(text)]
        self.assertEqual(paths, ['Art. 5', 'Art. 7'],
                         "a short line that starts with an article opens a unit; a long one is body")


@tagged('post_install', '-at_install')
class TestPassages(MemoryCase):

    def write(self, text, **kwargs):
        written = self.env['ir.attachment'].with_user(self.member)._texo_write(
            name='Decreto di prova', url='https://docs.example.com/decreto', project_id=self.project.id,
            summary='Un decreto sulla progettazione.', text=text, **kwargs)
        return self.env['ir.attachment'].browse(written['id'])

    def passages(self, document):
        return self.env['memory.document.passage'].search([('attachment_id', '=', document.id)])

    def test_the_search_answers_with_the_passage(self):
        document = self.write(law())
        passages = self.passages(document)
        self.assertEqual(passages.mapped('title'), ['Decreto di prova'] * len(passages))
        found = self.env['memory.note'].with_user(self.member)._agent_search('XQ7781', scope='documents')
        self.assertEqual(found[0]['id'], document.id)
        self.assertEqual(found[0]['words'], 'all')
        self.assertTrue(found[0]['passage']['path'].endswith('Art. 43 (Metodi e strumenti digitali) > commi 1-2'))
        self.assertIn('XQ', law()[found[0]['passage']['start']:][:3000], "the offset reads the passage")
        named = found[0]['passages']
        self.assertEqual(named[0], {'path': found[0]['passage']['path'], 'start': found[0]['passage']['start']},
                         "the passages to read, the one that answered first")
        self.assertLessEqual(len(named), 3)
        # every word in one passage, though the summary and the title say nothing of it
        found = self.env['memory.note'].with_user(self.member)._agent_search('sopralluogo progettista',
                                                                               scope='documents')
        self.assertEqual(found[0]['passage']['path'], 'TITOLO I (DISPOSIZIONI GENERALI) > Art. 2 (Definizioni)')

    def test_the_passages_follow_the_text_and_the_title(self):
        document = self.write(law())
        before = len(self.passages(document))
        self.assertGreater(before, 3)
        document.name = 'Decreto rinominato'
        self.assertEqual(set(self.passages(document).mapped('title')), {'Decreto rinominato'})
        self.env['ir.attachment'].with_user(self.member)._texo_write(document_id=document.id,
                                                                             text="Un testo nuovo e breve.")
        self.assertEqual(self.passages(document).mapped('text'), ["Un testo nuovo e breve."])
        # a sensitive document: no text, no passages
        self.env['ir.attachment'].with_user(self.member)._texo_write(document_id=document.id, keep_text=False)
        self.assertFalse(self.passages(document))
        self.assertEqual(self.env['memory.note'].with_user(self.member)._agent_search('nuovo breve', scope='documents'),
                         [])

    def test_the_passages_are_read_only_through_their_document(self):
        document = self.write(law())
        self.assertFalse(self.env['memory.document.passage'].with_user(self.member).has_access('read'))
        self.assertEqual(self.env['memory.note'].with_user(self.outsider)._agent_search('XQ7781', scope='documents'),
                         [], "a document of a followers-only project: neither it nor its passages")
        self.assertTrue(self.passages(document))
