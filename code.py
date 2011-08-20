#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import os

import feed
import web

# Chdir into this module file's directory
moduledir = os.path.dirname(__file__)
if moduledir:
    os.chdir(moduledir)

# Data path to store this app's db file, fecthed feed entries
datapath = 'data'
if not os.path.exists(datapath):
    os.makedirs(datapath)

# Webpy config
#web.config.debug = True

# Webpy app instance
app = web.auto_application()

# Webpy database
db = web.database(dbn='sqlite', db=os.path.join(datapath, 'feed2mobi.db'))

# Webpy session
if not web.config.get('_session'):
    session = web.session.Session(app,
                                  web.session.DiskStore(os.path.join(datapath, 'sessions')))
    web.config._session = session
else:
    session = web.config._session

# Webpy template
render = web.template.render('templates/',
                             base='layout',
                             globals={'context': session})

# Feed manager
mgr = feed.FeedManager(db, datapath=datapath)


# ----------------------------------------
# Google account service
# ----------------------------------------
from urllib2 import urlopen
from urllib import urlencode
import re

_GOOGLE_OPENID_PARAMS = {
    'openid.ns': 'http://specs.openid.net/auth/2.0',
    'openid.ns.pape': 'http://specs.openid.net/extensions/pape/1.0',
    'openid.ns.max_auth_age': '0',
    'openid.claimed_id': 'http://specs.openid.net/auth/2.0/identifier_select',
    'openid.identity': 'http://specs.openid.net/auth/2.0/identifier_select',
    # 'openid.return_to': 'http://www.example.com/checkauth',
    # 'openid.realm': 'http://www.example.com/',
    # 'openid.assoc_handle': 'ABSmpf6DNMw',
    'openid.mode': 'checkid_setup',
    'openid.ui.ns': 'http://specs.openid.net/extensions/ui/1.0',
    'openid.ui.mode': 'popup',
    'openid.ui.icon': 'true',
    'openid.ns.ax': 'http://openid.net/srv/ax/1.0',
    'openid.ax.mode': 'fetch_request',
    'openid.ax.type.email': 'http://axschema.org/contact/email',
    'openid.ax.required': 'email',
    }
_GOOGLE_OPENID_URL = 'https://www.google.com/accounts/o8/id'
_XRDS_RE = re.compile(u'<URI>([^<]+)</URI>')
def google_login():
    params = dict(_GOOGLE_OPENID_PARAMS)
    params['openid.return_to'] = web.ctx.home + web.http.url('/checkauth')
    queryStr = '?'+urlencode(params)
    try:
        resp = urlopen(_GOOGLE_OPENID_URL + queryStr)
        m = _XRDS_RE.search(resp.read().decode('utf-8'))
        if m:
            uri = m.group(1)
            raise web.seeother(uri + queryStr)
    except:
        pass
    return render.notlogin('Cannot connect Google Account service')

def require_auth(fn):
    def new_func(*args, **kws):
        if not (session.get('account') and session.get('account_id')):
            google_login()
        else:
            return fn(*args, **kws)
    return new_func



# ----------------------------------------
# Auth web handlers
# ----------------------------------------
class login(app.page):
    def GET(self):
        if session.get('account'):
            raise web.seeother(web.ctx.home + web.http.url('/'))
        else:
            google_login()


class checkauth(app.page):
    def GET(self):
        i = web.input()
        if i.get('openid.mode') == 'id_res':
            account = i.get('openid.ext1.value.email')
            account_id, account_actived = mgr.account(account)
            if account_actived:
                session['account'] = account
                session['account_id'] = account_id
                raise web.seeother(web.ctx.home + web.http.url('/'))
            else:
                raise web.forbidden('Account has been locked')
        return render.notlogin('Unsuccessful log-in or has declined to approve authentication')


class logout(app.page):
    def GET(self):
        session.kill()
        raise web.seeother(web.ctx.home + web.http.url('/'))


# ----------------------------------------
# Bizz web handlers
# ----------------------------------------
class top(app.page):
    path='^/(?:top)?(?:\?o=[0-9]+)?$'
    pagesize = 15

    def GET(self):
        i = web.input()
        offset = int(i.get('o', 0))
        feeds = mgr.list(account=session.get('account_id'),
                         offset=offset, limit=self.pagesize+1)
        feeds, prevOffset, nextOffset = self.calcPageData(feeds, offset)
        return render.list(feeds, prevOffset, nextOffset, self.page())

    def page(self):
        return ('top' if web.ctx.path=='/' else web.ctx.path[1:])

    def calcPageData(self, feeds, offset):
        return (feeds if len(feeds) <= self.pagesize else feeds[:-1],\
                    None if offset == 0 else offset-self.pagesize,\
                    None if len(feeds) <= self.pagesize else offset+self.pagesize)


class new(top):
    path='^/new(?:\?o=[0-9]+)?$'

    def GET(self):
        i = web.input()
        offset = int(i.get('o', 0))
        feeds = mgr.listNew(session.get('account_id'),
                            offset=offset, limit=self.pagesize+1)
        feeds, prevOffset, nextOffset = self.calcPageData(feeds, offset)
        return render.list(feeds, prevOffset, nextOffset, self.page())


class subscribed(top):
    path='^/subscribed(?:\?o=[0-9]+)?$'

    @require_auth
    def GET(self):
        if not session.get('account'):
            raise web.forbidden('Not logged in')
        i = web.input()
        offset = int(i.get('o', 0))
        feeds = mgr.listSubscribed(session['account_id'],
                                   offset=offset, limit=self.pagesize+1)
        feeds, prevOffset, nextOffset = self.calcPageData(feeds, offset)
        return render.list(feeds, prevOffset, nextOffset, self.page())


class subscribe(app.page):
    path='^/subscribe/([0-9]+)$'

    @require_auth
    def GET(self, feed):
        mgr.subscribe(feed, session['account_id'])
        raise web.seeother(web.ctx.home + web.http.url('/subscribed'))


class subscribe1(app.page):
    path='^/subscribe$'

    @require_auth
    def POST(self):
        i = web.input()
        mgr.subscribe(i.feed, session['account_id'])
        raise web.seeother(web.ctx.home + web.http.url('/subscribed'))


class unsubscribe(app.page):
    path='^/unsubscribe/([0-9]+)$'

    @require_auth
    def GET(self, feed):
        mgr.unsubscribe(feed, session['account_id'])
        raise web.seeother(web.ctx.home + web.http.url('/subscribed'))


class delivery(app.page):

    @require_auth
    def GET(self):
        delivery = list(db.select(['account'],
                                  what='delivery_hour hour,delivery_address address,delivery_actived actived',
                                  where='id=$account',
                                  vars={'account': session['account_id']}))
        return render.delivery(delivery[0])

    @require_auth
    def POST(self):
        i = web.input()
        actived = int(i.get('actived',0))
        hour = int(i.get('hour', 8))
        address = i.get('address', None)
        if address:
            address = address.strip()

        db.update('account',
                  where='id=$account',
                  delivery_actived = actived,
                  delivery_hour = hour,
                  delivery_address = address,
                  vars={'account': session['account_id']})
        raise web.seeother(web.ctx.home + web.http.url('/delivery'))



if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser('Usage: %prog [options]')
    parser.add_option('--update', dest='update', action='store_true',
                      help='Update contents of feeds')
    parser.add_option('--kindlegen', dest='kindlegen', action='store_true',
                      help='Run kindlegen and send files')
    options, args = parser.parse_args()

    if options.update or options.kindlegen:
        if options.update:
            mgr.update()
        else:
            # cron job always runs before delivery hour
            hour = datetime.datetime.now().hour + 1
            if hour > 23:
                hour = 0
            mgr.kindlegen(hour)
    else:
        app.run()

# Local Variables: **
# comment-column: 56 **
# indent-tabs-mode: nil **
# python-indent: 4 **
# End: **
