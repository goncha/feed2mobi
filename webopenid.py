"""openid.py: an openid library for web.py

Notes:

 - This will create a file called .openid_secret_key in the
   current directory with your secret key in it. If someone
   has access to this file they can log in as any user. And
   if the app can't find this file for any reason (e.g. you
   moved the app somewhere else) then each currently logged
   in user will get logged out.

 - State must be maintained through the entire auth process
   -- this means that if you have multiple web.py processes
   serving one set of URLs or if you restart your app often
   then log ins will fail. You have to replace sessions and
   store for things to work.

 - We set cookies starting with "openid_".


Customization:

 - Use session API of web.py to implement openid session,
   make it usable in multi processes deployment.
"""

import os
import random
import hmac
import web
import openid.consumer.consumer
import openid.store.memstore

session = None                  # Must set after importing this module
store = openid.store.memstore.MemoryStore()

def _secret():
    try:
        secret = file('.openid_secret_key').read()
    except IOError:
        # file doesn't exist
        secret = os.urandom(20)
        file('.openid_secret_key', 'w').write(secret)
    return secret

def _hmac(identity_url):
    return hmac.new(_secret(), identity_url).hexdigest()

def status():
    oid_hash = web.cookies().get('openid_identity_hash', '').split(',', 1)
    if len(oid_hash) > 1:
        oid_hash, identity_url = oid_hash
        if oid_hash == _hmac(identity_url):
            return identity_url
    return None

def openid_form(openid_loc):
    oid = status()
    if oid:
        return '''
        <form method="post" action="%s" class="navbar-form pull-right">
          <img src="http://openid.net/login-bg.gif" alt="OpenID" />
          <strong>%s</strong>
          <input type="hidden" name="action" value="logout" />
          <input type="hidden" name="return_to" value="%s" />
          <button type="submit" class="btn btn-inverse">Logout</button>
        </form>''' % (openid_loc, oid, web.ctx.fullpath)
    else:
        return '''
        <form method="post" action="%s" class="navbar-form pull-right">
          <input type="text" name="openid_identifier" value=""
                 placeholder="Your OpenID" class="span3"/>
          <input type="hidden" name="return_to" value="%s" />
          <button type="submit" class="btn btn-primary">Login</button>
        </form>''' % (openid_loc, web.ctx.fullpath)

def logout():
    web.setcookie('openid_identity_hash', '', expires=-1)
    session.kill()

class host:
    def POST(self):
        # unlike the usual scheme of things, the POST is actually called
        # first here
        i = web.input(return_to='/')
        if i.get('action') == 'logout':
            logout()
            return web.redirect(i.return_to)

        i = web.input('openid_identifier', return_to='/')

        session['webpy_return_to'] = i.return_to

        c = openid.consumer.consumer.Consumer(session, store)
        a = c.begin(i.openid_identifier)
        f = a.redirectURL(web.ctx.home, web.ctx.home + web.ctx.fullpath)

        return web.redirect(f)

    def GET(self):
        return_to = session['webpy_return_to']

        c = openid.consumer.consumer.Consumer(session, store)
        a = c.complete(web.input(), web.ctx.home + web.ctx.fullpath)

        if a.status.lower() == 'success':
            web.setcookie('openid_identity_hash', _hmac(a.identity_url) + ',' + a.identity_url)

        session.kill()
        return web.redirect(return_to)
