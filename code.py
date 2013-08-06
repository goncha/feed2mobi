#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import os

import feed
import web
import web.webopenid


# Chdir into this module file's directory
moduledir = os.path.dirname(__file__)
if moduledir:
    os.chdir(moduledir)

# Data path to store this app's db file, fecthed feed entries
datapath = 'data'
if not os.path.exists(datapath):
    os.makedirs(datapath)

# Webpy config
web.config.debug = False

# Webpy app instance
app = web.auto_application()

# Webpy database
db = web.database(dbn='sqlite', db=os.path.join(datapath, 'feed2mobi.db'))

# Webpy template
render = web.template.render(base='layout',
                             globals={'openid': web.webopenid,
                                      'context': web.ctx})

# Feed manager
mgr = feed.FeedManager(db, datapath=datapath)


# ----------------------------------------
# OpenID service
# ----------------------------------------
app.add_mapping(r'/openid', 'web.webopenid.host')

def set_auth_info(fn):
    def new_func(*args, **kws):
        oid = web.webopenid.status()
        if oid:
            account_id, account_actived = mgr.account(oid)
            web.ctx.account_id = account_id
            web.ctx.account_actived = account_actived
        return fn(*args, **kws)
    return new_func


def require_auth(fn):
    def new_func(*args, **kws):
        if web.ctx.get('account_id'):
            if web.ctx.get('account_actived'):
                return fn(*args, **kws)
            else:
                raise web.forbidden('Account has been locked')
        else:
            raise web.seeother(web.ctx.home + web.http.url('/'))
    return new_func


# ----------------------------------------
# Bizz web handlers
# ----------------------------------------
class top(app.page):
    path='^/(?:top)?(?:\?o=[0-9]+)?$'
    pagesize = 15

    @set_auth_info
    def GET(self):
        i = web.input()
        offset = int(i.get('o', 0))
        feeds = mgr.list(account=web.ctx.get('account_id'),
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

    @set_auth_info
    def GET(self):
        i = web.input()
        offset = int(i.get('o', 0))
        feeds = mgr.listNew(web.ctx.get('account_id'),
                            offset=offset, limit=self.pagesize+1)
        feeds, prevOffset, nextOffset = self.calcPageData(feeds, offset)
        return render.list(feeds, prevOffset, nextOffset, self.page())


class subscribed(top):
    path='^/subscribed(?:\?o=[0-9]+)?$'

    @set_auth_info
    @require_auth
    def GET(self):
        i = web.input()
        offset = int(i.get('o', 0))
        feeds = mgr.listSubscribed(web.ctx.get('account_id'),
                                   offset=offset, limit=self.pagesize+1)
        feeds, prevOffset, nextOffset = self.calcPageData(feeds, offset)
        return render.list(feeds, prevOffset, nextOffset, self.page())


class subscribe(app.page):
    path='^/subscribe/([0-9]+)$'

    @set_auth_info
    @require_auth
    def GET(self, feed):
        mgr.subscribe(feed, web.ctx.get('account_id'))
        raise web.seeother(web.ctx.home + web.http.url('/subscribed'))


class subscribe1(app.page):
    path='^/subscribe$'

    @set_auth_info
    @require_auth
    def POST(self):
        i = web.input()
        mgr.subscribe(i.feed, web.ctx.get('account_id'))
        raise web.seeother(web.ctx.home + web.http.url('/subscribed'))


class unsubscribe(app.page):
    path='^/unsubscribe/([0-9]+)$'

    @set_auth_info
    @require_auth
    def GET(self, feed):
        mgr.unsubscribe(feed, web.ctx.get('account_id'))
        raise web.seeother(web.ctx.home + web.http.url('/subscribed'))


class delivery(app.page):

    @set_auth_info
    @require_auth
    def GET(self):
        delivery = list(db.select(['account'],
                                  what='delivery_hour hour,delivery_address address,delivery_actived actived,delivery_bundle bundle',
                                  where='id=$account',
                                  vars={'account': web.ctx.get('account_id')}))
        return render.delivery(delivery[0])

    @set_auth_info
    @require_auth
    def POST(self):
        i = web.input()
        actived = int(i.get('actived',0))
        hour = int(i.get('hour', 8))
        bundle = int(i.get('bundle', 20))
        address = i.get('address', None)
        if address:
            address = address.strip()

        db.update('account',
                  where='id=$account',
                  delivery_actived = actived,
                  delivery_hour = hour,
                  delivery_address = address,
                  delivery_bundle = bundle,
                  vars={'account': web.ctx.get('account_id')})
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

# uWSGI requires this variable
application = app.wsgifunc()

# Local Variables: **
# comment-column: 56 **
# indent-tabs-mode: nil **
# python-indent: 4 **
# End: **
