# -*- coding: utf-8 -*-


from itertools import groupby
from operator import attrgetter
from subprocess import call

from lxml import etree


def htmlNode():
    html = etree.Element('html')
    head = etree.SubElement(html, 'head')
    # This is important for kindlegen to decode utf-8 files
    etree.SubElement(head, 'meta', attrib={
            'http-equiv': 'Content-Type',
            'content': 'text/html;charset=UTF-8'})
    return html


class KindleGen(object):

    TOC = 'periodical.html'
    NCX = 'periodical.ncx'
    OPF = 'periodical.opf'

    MIME = {
        'html' : 'application/xhtml+xml',
        'jpg' : 'image/jpeg',
        'gif' : 'image/gif',
        'png' : 'image/png',
        'ncx' : 'application/x-dtbncx+xml'
        }

    def __init__(self, program='kindlegen'):
        self._program = program


    def execute(self, title, date, entries):
        '''
        Generate .mobi file in periodical format.

        Arguments:
        - `title`: ebook title
        - `date`: ebook date in format 'YYYY-MM-DD'
        - `output`: output file name, exclude '.mobi'
        - `entries`: list of maps having key ('feed_id', 'feed_title', 'entry_id', 'entry_title', 'author', 'path')

        Return:
        Output filename
        '''
        if not len(entries):
            return

        book_id = title.replace(' ', '_')+'_'+date

        self.generateTOC(entries)
        self.generateOPF(book_id, title, date, entries)
        self.generateNCX(book_id, title, entries)

        output = book_id + '.mobi'
        call([self._program, '-c2', '-o', output, self.OPF])
        return output


    def generateTOC(self, entries):
        html = htmlNode()
        body = etree.SubElement(html, 'body')
        etree.SubElement(body,'h2').text = 'Table of Contents'

        for section, articles in groupby(entries, attrgetter('feed_title')):
            etree.SubElement(body, 'h4').text = section
            for article in articles:
                etree.SubElement(body, 'a', attrib={'href': article.path}).text = article.entry_title
                etree.SubElement(body, 'br')

        with open(self.TOC, 'w') as fo:
            fo.write(etree.tostring(html,
                                    pretty_print=True,
                                    encoding='utf-8',
                                    xml_declaration=False))


    def generateOPF(self, book_id, title, date, entries):
        opf_namespace = 'http://www.idpf.org/2007/opf'
        dc_namespace = 'http://purl.org/dc/elements/1.1/'
        dc_metadata_nsmap = { 'dc' : dc_namespace }
        dc = '{{{0}}}'.format(dc_namespace)

        package = etree.Element('{{{0}}}package'.format(opf_namespace),
                                nsmap={None:opf_namespace},
                                attrib={'version':'2.0',
                                        'unique-identifier':book_id})
        metadata = etree.Element('metadata')
        package.append(metadata)

        # etree.SubElement(metadata,'meta',attrib={'name':'cover',
        #                                           'content':cover[:-4]})
        dc_metadata = etree.Element('dc-metadata',
                                    nsmap=dc_metadata_nsmap)
        metadata.append(dc_metadata)

        etree.SubElement(dc_metadata,dc+'title').text = title
        etree.SubElement(dc_metadata,dc+'language').text = 'en-us'
        etree.SubElement(dc_metadata,dc+'creator').text = title
        etree.SubElement(dc_metadata,dc+'publisher').text = title
        etree.SubElement(dc_metadata,dc+'subject').text = "News"
        etree.SubElement(dc_metadata,dc+'date').text = date
        etree.SubElement(dc_metadata,dc+'description').text = '{0} on {1}'.format(title, date)

        x_metadata = etree.Element('x-metadata')
        metadata.append( x_metadata )
        etree.SubElement(x_metadata,'output',attrib={'encoding':'utf-8',
                                                     'content-type':'application/x-mobipocket-subscription-magazine'})

        manifest = etree.SubElement(package,'manifest')
        etree.SubElement(manifest, 'item',
                         attrib={'id' : self.TOC,
                                 'media-type' : self.MIME['html'],
                                 'href' : self.TOC})
        etree.SubElement(manifest, 'item',
                         attrib={'id' : self.NCX,
                                 'media-type' : self.MIME['ncx'],
                                 'href' : self.NCX})

        spine = etree.SubElement(package, 'spine',
                                 attrib={'toc' : self.NCX})
        etree.SubElement(spine, 'itemref',
                         attrib={'idref': self.TOC})

        for e in  entries:
            etree.SubElement(manifest, 'item',
                             attrib={'id' : str(e.entry_id),
                                     'media-type' : self.MIME[e.path.split('.')[-1]],
                                     'href' : e.path})
            etree.SubElement(spine, 'itemref',
                             attrib = {'idref' : str(e.entry_id)})

        guide = etree.SubElement(package,'guide')
        etree.SubElement(guide,'reference',
                         attrib={'type':'toc',
                                 'title':'Table of Contents',
                                 'href':self.TOC})
        etree.SubElement(guide,'reference',
                         attrib={'type':'text',
                                 'title':'Welcome',
                                 'href':self.TOC})

        with open(self.OPF, 'w') as fo:
            fo.write(etree.tostring(package,
                                    pretty_print=True,
                                    encoding='utf-8',
                                    xml_declaration=True))


    def generateNavPoint (self, nav_point_node, label, source):
        content = etree.Element('content', attrib={'src' : source})
        text_element = etree.Element('text')
        text_element.text = label
        nav_label = etree.SubElement(nav_point_node, "navLabel")
        nav_label.append(text_element)
        nav_point_node.append(content)


    def generateNCX (self, book_id, title, entries):
        mbp_namespace = 'http://mobipocket.com/ns/mbp'

        ncx_namespace = 'http://www.daisy.org/z3986/2005/ncx/'
        ncx_nsmap = { None: ncx_namespace, 'mbp': mbp_namespace }

        ncx = etree.Element('ncx',
                            nsmap=ncx_nsmap,
                            attrib={'version' : '2005-1',
                                    '{http://www.w3.org/XML/1998/namespace}lang' : 'en-US'})

        head = etree.SubElement(ncx, 'head')
        etree.SubElement(head,'meta',
                         attrib={'name' : 'dtb:uid',
                                 'content' : book_id })
        etree.SubElement(head,'meta',
                         attrib={'name' : 'dtb:depth',
                                 'content' : '2' })
        etree.SubElement(head,'meta',
                         attrib={'name' : 'dtb:totalPageCount',
                                 'content' : '0' })
        etree.SubElement(head,'meta',
                         attrib={'name' : 'dtb:maxPageNumber',
                                 'content' : '0' })

        title_text_element = etree.Element('text')
        title_text_element.text = title
        author_text_element = etree.Element("text")
        author_text_element.text = title

        etree.SubElement(ncx,'docTitle').append(title_text_element)
        etree.SubElement(ncx,'docAuthor').append(author_text_element)

        nav_map = etree.SubElement(ncx,'navMap')

        nav_point_periodical = etree.SubElement(nav_map, 'navPoint',
                                                attrib={'class': 'periodical', 'id': 'periodical', 'playOrder': '0'})
        self.generateNavPoint(nav_point_periodical, 'Table of Contents', self.TOC)

        i = 1
        scount = 0
        for section, articles in groupby(entries, attrgetter('feed_title')):
            scount = scount+1
            articles = list(articles)
            nav_point_section = etree.SubElement(nav_point_periodical,"navPoint",
                                                 attrib={"class" : "section",
                                                         "id" : ('sec_' + str(scount)),
                                                         "playOrder" : str(i) })
            self.generateNavPoint(nav_point_section, section, articles[0].path)
            i += 1

            acount = 0
            for article in articles:
                acount += 1
                nav_point_article = etree.SubElement(nav_point_section,"navPoint",
                                                     attrib={"class" : "article",
                                                             "id" : ('art_' + str(scount) + '_' + str(acount)),
                                                             "playOrder" : str(i) })
                self.generateNavPoint(nav_point_article, article.entry_title, article.path)
                i += 1

        with open(self.NCX, 'w') as fo:
            fo.write('<?xml version="1.0" encoding="utf-8"?>\n')
            fo.write('<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">\n')
            fo.write(etree.tostring(ncx,
                                    pretty_print=True,
                                    encoding="utf-8",
                                    xml_declaration=False))


# Local Variables: **
# comment-column: 56 **
# indent-tabs-mode: nil **
# python-indent: 4 **
# End: **
