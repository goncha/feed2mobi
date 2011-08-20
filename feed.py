# -*- coding: utf-8 -*-

import datetime
import hashlib
import itertools
import os
import os.path
import sqlite3
import sys


from kindlegen import KindleGen, htmlNode
from lxml import etree
from subprocess import call, Popen, PIPE
from urllib2 import urlopen, Request, HTTPError
from StringIO import StringIO


def cd(path):
    class ChangeDir(object):
        def __init__(self, path):
            self._path = path
        def __enter__(self):
            self._oldpath = os.getcwd()
            os.chdir(self._path)
        def __exit__(self, exc_type, exc_value, traceback):
            os.chdir(self._oldpath)
    return ChangeDir(path)


class FeedFactory(object):

    _feedTypes=[]

    @classmethod
    def parseFeed(cls, url, lastModified=None, etag=None):
        '''
        Return tuple of feed object, last-modified, etag.
        '''
        req = Request(url)
        if lastModified:
            req.add_header('if-modified-since', lastModified)
        if etag:
            req.add_header('if-none-match', etag)
        resp = None
        try:
            resp = urlopen(req, None, 10)
        except HTTPError as error:
            # HTTP 304 not modifed raise an exception
            resp = error

        if resp.code != 200:
            return None

        feedDoc = etree.parse(resp)
        feedType = None
        for ft in cls._feedTypes:
            if ft.accept(feedDoc):
                feedType = ft
                break
        if not feedType:
            raise ValueError('Cannot handle ' + feedDoc.getroot().tag)
        return (feedType(url, feedDoc),
                resp.headers.get('last-modified'),
                resp.headers.get('etag'))

    @classmethod
    def register(cls, feedType):
        cls._feedTypes.append(feedType)


class Feed(object):

    _NSS = {}

    @classmethod
    def accept(cls, feedDoc):
        '''Return True if this feed impl can handle feedDoc's content, otherwise False.'''
        raise NotImplemented

    def __init__(self, url, doc):
        self._url = url
        self._doc = doc

    def _text(self, node, *nodeNames):
        for nn in nodeNames:
            ns = node.xpath(nn, namespaces=self._NSS)
            if ns:
                ns = ns[0]
                if 'xhtml' == ns.attrib.get('type') and ns.getchildren():
                    return etree.tostring(ns.getchildren()[0],
                                          pretty_print=False,
                                          encoding='utf-8',
                                          xml_declaration=False).decode('utf-8')
                else:
                    if ns.text:
                        return ns.text

    def _texts(self, node, *nodeNames):
        for nn in nodeNames:
            ns = node.xpath(nn+'/text()', namespaces=self._NSS)
            if ns:
                return ', '.join(ns)

    def doc(self):
        return self._doc

    def url(self):
        return self._url

    def title(self):
        '''Return title of feed.'''
        raise NotImplemented

    def description(self):
        '''Return description of feed.'''
        raise NotImplemented

    def lastUpdated(self):
        '''Return last updated date/timestamp str.'''
        raise NotImplemented

    def items(self):
        '''Return iterator of tuple (url, title, author, pubdate, summary, content).'''
        raise NotImplemented


class Rss2Feed(Feed):

    _NSS = {
        'content': 'http://purl.org/rss/1.0/modules/content/',
        'dc': 'http://purl.org/dc/elements/1.1/'
        }

    @classmethod
    def accept(cls, feedNode):
        root = feedNode.getroot()
        return ('rss' == root.tag and
                '2.0' == root.attrib.get('version'))

    def __init__(self, url, doc):
        Feed.__init__(self, url, doc)

    def title(self):
        nodes = self.doc().xpath('/rss/channel/title/text()')
        return nodes[0] if len(nodes) > 0 else url().split('/')[2]

    def description(self):
        nodes = self.doc().xpath('/rss/channel/description/text()')
        return nodes[0] if len(nodes) > 0 else None

    def lastUpdated(self):
        nodes = self.doc().xpath('/rss/channel/lastBuildDate/text()')
        return nodes[0] if len(nodes) > 0 else None

    def items(self):
        for item in self.doc().xpath('/rss/channel/item'):
            url = self._text(item, 'link', 'guid')
            title = self._text(item, 'title')
            author = self._text(item, 'dc:creator')
            pubdate = self._text(item, 'pubDate')
            summary = self._text(item, 'description')
            content = self._text(item, 'content:encoded')
            yield (url, title, author, pubdate, summary, content)


class AtomFeed(Feed):

    _NSS = {
        'a': 'http://www.w3.org/2005/Atom',
        }
    _XMLBASE = '{%s}base' % 'http://www.w3.org/XML/1998/namespace'

    @classmethod
    def accept(cls, feedNode):
        root = feedNode.getroot()
        return '{http://www.w3.org/2005/Atom}feed' == root.tag

    def __init__(self, url, doc):
        Feed.__init__(self, url, doc)

    def title(self):
        nodes = self.doc().xpath('/a:feed/a:title/text()',
                                 namespaces=self._NSS)
        return nodes[0] if len(nodes) > 0 else url().split('/')[2]

    def description(self):
        nodes = self.doc().xpath('/a:feed/a:subtitle/text()',
                                 namespaces=self._NSS)
        return nodes[0] if len(nodes) > 0 else None

    def lastUpdated(self):
        nodes = self.doc().xpath('/a:feed/a:updated/text()',
                                 namespaces=self._NSS)
        return nodes[0] if len(nodes) > 0 else None

    def items(self):
        feedBase = self.doc().getroot().attrib.get(self._XMLBASE, '')
        if feedBase:
            path = feedBase.split('/')
            if len(path) == 3: # http://host:port
                feedBase = '/'.join(path) + '/'
            else:
                path[-1] = ''
                feedBase = '/'.join(path)
        feedAuthor = self._text(self.doc(), '/a:feed/a:author/a:name')
        for item in self.doc().xpath('/a:feed/a:entry', namespaces=self._NSS):
            entryBase = item.attrib.get(self._XMLBASE, '')
            link = item.xpath('a:link[not(@rel)]', namespaces=self._NSS)
            if not link:
                link = item.xpath('a:link', namespaces=self._NSS)
            link = link[0].attrib['href']
            url = ''.join([feedBase, entryBase, link])
            title = self._text(item, 'a:title')
            author = self._texts(item, 'a:author/a:name')
            pubdate = self._text(item, 'a:updated', 'a:published')
            summary = self._text(item, 'a:summary')
            content = self._text(item, 'a:content')
            yield (url, title, author if author else feedAuthor,
                   pubdate, summary, content)


FeedFactory.register(Rss2Feed)
FeedFactory.register(AtomFeed)


class FeedManager(object):
    '''
    Manage user accounts and feed subscription.

        >>> import web
        >>> db = web.database(dbn='sqlite', db='data/feed2mobi.db')
        >>> mgr = FeedManager(db)
        >>> mgr.list()
        []
        >>> mgr.account('tom@example.com')
        (1, 1)
        >>> mgr.account('tom@example.com')
        (1, 1)
        >>> mgr.account('jerry@example.com')
        (2, 1)
        >>> mgr.account('john@example.com')
        (3, 1)
        >>> mgr.list()
        []
        >>> mgr.subscribe('samples/ifanr.rss2.xml', 1)
        (1, 1)
        >>> mgr.subscribe(1, 1)
        (1, 1)
        >>> mgr.subscribe(1, 2)
        (1, 2)
        >>> mgr.subscribe('samples/ongoing.atom.xml', 2)
        (2, 2)
        >>> feeds = mgr.list()
        >>> len(feeds)
        2
        >>> feeds[0].id
        1
        >>> feeds[0].subscribed
        2
        >>> len(mgr.list(limit=1, offset=0))
        1
        >>> mgr.unsubscribe(2, 2)
        >>> feeds = mgr.list()
        >>> len(feeds)
        2
        >>> feeds[1].id
        2
        >>> feeds[1].subscribed
        0
        >>> len(mgr.listSubscribed(1))
        1
        >>> mgr.listSubscribed(3)
        []
    '''

    _INIT_SQLS = [
'''
CREATE TABLE IF NOT EXISTS account
(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL UNIQUE,
 delivery_address TEXT,
 delivery_hour INTEGER DEFAULT 8,
 delivery_actived INTEGER NOT NULL DEFAULT 0,
 actived INTEGER NOT NULL DEFAULT 1
)
''',
'''
CREATE TABLE IF NOT EXISTS feed
(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 url TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL,
 description TEXT,
 last_updated TEXT,
 http_last_modified TEXT,
 http_etag TEXT,
 actived INTEGER NOT NULL DEFAULT 1
)
''',
'''
CREATE TABLE IF NOT EXISTS entry
(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 feed_id INTEGER NOT NULL,
 path TEXT NOT NULL,
 link TEXT,
 title TEXT NOT NULL,
 author TEXT,
 pub_date TEXT,
 CONSTRAINT fk_feed_id FOREIGN KEY (feed_id) REFERENCES feed (id)
)
''',
'''
CREATE TABLE IF NOT EXISTS account_feed
(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 account_id INTEGER NOT NULL,
 feed_id INTEGER NOT NULL,
 CONSTRAINT fk_af_account_id FOREIGN KEY (account_id) REFERENCES account (id),
 CONSTRAINT fk_af_feed_id FOREIGN KEY (feed_id) REFERENCES feed (id)
)
''',
'''
CREATE TABLE IF NOT EXISTS account_entry
(
 account_id INTEGER NOT NULL,
 feed_id INTEGER NOT NULL,
 entry_id INTEGER NOT NULL,
 unread INTEGER NOT NULL DEFAULT 1,
 CONSTRAINT pk_ae PRIMARY KEY (account_id, feed_id, entry_id),
 CONSTRAINT fk_ae_account_id FOREIGN KEY (account_id) REFERENCES account (id),
 CONSTRAINT fk_ae_feed_id FOREIGN KEY (feed_id) REFERENCES feed (id),
 CONSTRAINT fk_ae_entry_id FOREIGN KEY (entry_id) REFERENCES entry (id)
)
''',
'''
CREATE INDEX IF NOT EXISTS ix_account_actived ON account (actived)
''',
'''
CREATE INDEX IF NOT EXISTS ix_feed_actived ON feed (actived)
''',
'''
CREATE UNIQUE INDEX IF NOT EXISTS ix_account_feed_pk ON account_feed (account_id, feed_id)
''',
'''
CREATE INDEX IF NOT EXISTS ix_entry_feed_path ON entry (feed_id, path)
''',
'''
CREATE INDEX IF NOT EXISTS ix_account_actived_hour ON account (actived, delivery_actived, delivery_hour)
''',
'''
CREATE INDEX IF NOT EXISTS ix_account_entry_unread ON account_entry (account_id, unread)
'''
]

    def __init__(self, db, datapath='.'):
        """
        Constructor
        Arguments:
        - `db`: web.database returned object
        """
        self._db = db
        cursor = db.ctx.db.cursor()
        try:
            for sql in self._INIT_SQLS:
                cursor.execute(sql)
        finally:
            cursor.close()

        self._datapath = datapath


    def account(self, name):
        db = self._db
        found = list(db.where('account', what='id,actived', name=name))
        if found:
            return (found[0].id, found[0].actived)
        else:
            try:
                return (db.insert('account', name=name), 1)
            except sqlite3.IntegrityError:
                found = list(db.where('account', what='id,actived', name=name)[0])
                return (found[0].id, found[0].actived)


    def _acount_entries(self, account):
        """
        Ensure account_entries_#
        Arguments:
        - `account`:
        """

        self._db.ctx.db.cursor()


    def subscribe(self, feed, account):
        db = self._db
        if not bool(db.where('account', what='id', id=account)):
            raise ValueError('account#'+account+' does not exist')

        found = None
        # try `feed' as feed id
        try:
            found = list(db.where('feed', what='id,actived', id=int(feed)))
        except ValueError:
            pass
        # try `feed' as feed url
        if not found:
            found = list(db.where('feed', what='id,actived', url=feed))

        if found:
            if found[0].actived:
                feed = found[0].id
            else:
                raise ValueError('feed#'+feed+' does not exist')
        else:
            # here is new feed
            feedObj, lastModified, etag = FeedFactory.parseFeed(feed)
            try:
                feed = db.insert('feed', url=feed,
                                 title=feedObj.title(),
                                 description=feedObj.description())
            except sqlite3.IntegrityError:
                feed = db.where('feed', what='id', url=feed)[0].id

        try:
            db.insert('account_feed', feed_id=feed, account_id=account)
        except sqlite3.IntegrityError:
            pass
        return (feed, account)


    def unsubscribe(self, feed, account):
        self._db.delete('account_feed',
                        where='feed_id=$feed and account_id=$account',
                        vars = locals())


    def list(self, account=None, limit=None, offset=None):
        query = '''
SELECT feed.id, feed.url, feed.title, feed.description, count(account_feed.id) account_count
FROM feed LEFT OUTER JOIN account_feed ON feed.id=account_feed.feed_id AND feed.actived=1
GROUP BY feed.id, feed.url, feed.title, feed.description
ORDER BY count(account_feed.id) DESC, feed.id DESC
'''
        if limit:
            query = query + ' LIMIT $limit'
        if offset:
            query = query + ' OFFSET $offset'
        if account:
            query = 'SELECT a.id, a.url, a.title, a.description, a.account_count, b.id subscribed FROM (' \
                + query \
                + ') a LEFT OUTER JOIN account_feed b ON a.id=b.feed_id and b.account_id=$account'
        return list(self._db.query(query,
                                   vars=locals()))

    def listNew(self, account=None, limit=None, offset=None):
        query = '''
SELECT feed.id, feed.url, feed.title, feed.description, count(account_feed.id) account_count
FROM feed LEFT OUTER JOIN account_feed ON feed.id=account_feed.feed_id AND feed.actived=1
GROUP BY feed.id, feed.url, feed.title, feed.description
ORDER BY feed.id DESC
'''
        if limit:
            query = query + ' LIMIT $limit'
        if offset:
            query = query + ' OFFSET $offset'
        if account:
            query = 'SELECT a.id, a.url, a.title, a.description, a.account_count, b.id subscribed FROM (' \
                + query \
                + ') a LEFT OUTER JOIN account_feed b ON a.id=b.feed_id and b.account_id=$account'
        return list(self._db.query(query,
                                   vars=locals()))


    def listSubscribed(self, account, limit=None, offset=None):
        return list(self._db.select(['feed', 'account_feed'],
                                    what='feed.id, feed.url, feed.title, feed.description, account_feed.id subscribed',
                                    where='feed.id=account_feed.feed_id AND feed.actived=1 AND account_feed.account_id=$account',
                                    order='account_feed.id DESC',
                                    limit=limit,
                                    offset=offset,
                                    vars=locals()))

    def update(self):
        db = self._db
        for feed in list(db.select(['feed'], where='actived=1')):
            print '>>>', feed.url
            try:
                feedObj = FeedFactory.parseFeed(feed.url,
                                                lastModified=feed.http_last_modified,
                                                etag=feed.http_etag)
            except:
                print 'Error when fetching and parsing feed,', sys.exc_info()[0]
                continue

            if not feedObj:
                continue # feed not updated by HTTP 304 not modified

            feedObj, lastModified, etag = feedObj

            if feed.last_updated and feed.last_updated == feedObj.lastUpdated():
                continue # double check feed not updated

            for entry in reversed(list(feedObj.items())):
                try:
                    self._update(feed.id, entry)
                except:
                    print 'Error save entry `%s`,' % (entry.url,), sys.exc_info()[0]

            db.update('feed', where='id=$id', vars={'id':feed.id},
                      last_updated=feedObj.lastUpdated(),
                      title=feedObj.title(),
                      description=feedObj.description(),
                      http_last_modified=lastModified,
                      http_etag=etag)


    def _update(self, feedId, entryObj):
        db = self._db
        url, title, author, pubdate, summary, content = entryObj
        hashval = hashlib.sha1(str(feedId)+':'+url.encode('utf-8')).hexdigest()
        path = os.path.join(str(feedId), hashval[:2])
        if not os.path.exists(os.path.join(self._datapath, path)):
            os.makedirs(os.path.join(self._datapath, path), 0755)
        path = os.path.join(path, hashval[2:]+'.html')

        entry = list(db.select(['entry'],
                               where='feed_id=$feedId and path=$path',
                               vars=locals()))

        # already existed, and not updated
        if entry and entry[0].pub_date == pubdate:
            return

        with db.transaction() as tx:
            if entry:
                db.update('entry', where='id=$id', vars={'id':entry[0].id},
                                title=title, author=author, pub_date=pubdate)
            else:
                entryId = db.insert('entry',
                                    feed_id=feedId,
                                    path=path,
                                    link=url,
                                    title=title,
                                    author=author,
                                    pub_date=pubdate)
                miValues = list(db.select('account_feed', what='account_id, feed_id, $entryId entry_id',
                                          where='feed_id=$feedId', vars=locals()))
                db.multiple_insert('account_entry', miValues)
            self._writefile(url, path, title, content if content else summary)


    def _writefile(self, url, path, title, content):
        path = os.path.join(self._datapath, path)

        parser = etree.HTMLParser(encoding='utf-8')
        html = etree.parse(StringIO(content.encode('utf-8')), parser)
        # Remove empty links and images
        for n in itertools.chain(html.xpath('//img'), \
                                     html.xpath('//script'), \
                                     html.xpath('//style')):
            n.getparent().remove(n)
        for a in html.xpath('//a'):
            if not a.text:
                a.getparent().remove(a)
            # else:
            #   a.tag='span'
            #   a.attrib.clear()

        cont_nodes = html.xpath('/html/body')[0].getchildren()
        html = htmlNode()
        body = etree.SubElement(html, 'body')
        etree.SubElement(body,'h2').text = title
        body.extend(cont_nodes)
        with open(path, 'w') as fo:
            fo.write(etree.tostring(html,
                                    pretty_print=True,
                                    encoding='utf-8',
                                    xml_declaration=False))


    def kindlegen(self, hour):
        """
        Call kindlegen to generate .mobi for accounts whose delivery_hour equals `hour`.
        """
        with cd(self._datapath) as notused:
            date = datetime.datetime.strftime(datetime.datetime.now(),'%Y-%m-%d')
            title = 'Feed2Mobi '
            kindlegen = KindleGen()

            db = self._db
            accounts = list(db.select(['account'],
                                      what='id,delivery_address',
                                      where='actived=1 AND delivery_actived=1 AND delivery_hour=$hour',
                                      vars=locals()))

            for account in accounts:
                address = account.delivery_address

                with db.transaction() as tx:
                    entries = list(db.select(['account_entry', 'entry', 'feed'],
                                             what='''
account_entry.feed_id,
feed.title feed_title,
account_entry.entry_id,
entry.title entry_title,
entry.author,
entry.path''',
                                             where='''
account_entry.account_id=$account_id
 AND account_entry.unread=1
 AND account_entry.entry_id=entry.id
 AND account_entry.feed_id=feed.id''',
                                             order='account_entry.feed_id ASC, account_entry.entry_id ASC',
                                             vars={'account_id':account.id}))

                    if entries:
                        mobi = None
                        try:
                            mobi = kindlegen.execute(title, date, entries)
                            if os.path.exists(mobi):
                                mailfile = 'delivery.mail'
                                with open(mailfile,'w') as fo:
                                    fo.write(os.linesep.join(['From: feed2mobi@skypiea.info',
                                                              'To: ' + address,
                                                              'Subject: feed2mobi daily delivery']))
                                p = Popen(['mutt', '-x', '-H', mailfile, '-a', mobi],
                                              stdin=PIPE)
                                p.communicate()
                                if (0 == p.returncode):
                                    print mobi, 'created successfully'
                                else:
                                    raise 'mutt return `%s` for `%s`' % (p.returncode, address)
                            else:
                                raise '.mobi file not generated for `%s`' % (address,)
                        except:
                            print "Unexpected error:", sys.exc_info()[0]
                        else:
                            for entry in entries:
                                db.update('account_entry',
                                          where='account_id=$account_id AND entry_id=$entry_id',
                                          vars={'account_id': account.id, 'entry_id': entry.entry_id},
                                          unread=0)
                        finally:
                            if os.path.exists(mobi):
                                os.remove(mobi) # should do backup?



if __name__ == "__main__":
    import doctest
    doctest.testmod()

# Local Variables: **
# comment-column: 56 **
# indent-tabs-mode: nil **
# python-indent: 4 **
# End: **
