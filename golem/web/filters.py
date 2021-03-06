from flask import current_app as app, url_for
from jinja2 import Markup, escape, Undefined
from collections import defaultdict
import hashlib
from golem import toutctimestamp
from golem.web.memoize import memoize
from golem.web.encoding import decode as decode_
import stat
import datetime
import re
import json
import copy

filters = {}
def filter(name_or_func):
    if callable(name_or_func):
        filters[name_or_func.__name__] = name_or_func
        return name_or_func
    def decorator(func):
        filters[name_or_func] = func
        return func
    return decorator

@filter('gravatar')
@memoize
def gravatar(email, size=21):
    return 'http://www.gravatar.com/avatar/%s?s=%d&d=mm' % (hashlib.md5(email).hexdigest(), size)

@filter
def humantime(ctime):
    timediff = (datetime.datetime.utcnow() - ctime).total_seconds()
    if timediff < 0:
        return 'in the future'
    if timediff < 60:
        return 'just now'
    if timediff < 120:
        return 'a minute ago'
    if timediff < 3600:
        return "%d minutes ago" % (timediff / 60)
    if timediff < 7200:
        return "an hour ago"
    if timediff < 86400:
        return "%d hours ago" % (timediff / 3600)
    if timediff < 172800:
        return "a day ago"
    if timediff < 2592000:
        return "%d days ago" % (timediff / 86400)
    if timediff < 5184000:
        return "a month ago"
    if timediff < 31104000:
        return "%d months ago" % (timediff / 2592000)
    if timediff < 62208000:
        return "a year ago"
    return "%d years ago" % (timediff / 31104000)

@filter
def humantimediff(timediff):
    elts = []
    if timediff > 31104000:
        elts.append('%d years' % (timediff / 31104000))
        timediff %= 31104000
    if timediff > 86400:
        elts.append("%d days" % (timediff / 86400))
        timediff %= 86400
    if timediff > 3600:
        elts.append("%d hours" % (timediff / 3600))
        timediff %= 3600
    if timediff > 60:
        elts.append("%d minutes" % (timediff / 60))
        timediff %= 60
    if timediff:
        elts.append("%d seconds" % timediff)
    return ', '.join(elts)

@filter
def shortmsg(message):
    message += "\n"
    short, long = message.split('\n', 1)
    if len(short) > 80:
        short = escape(short[:short.rfind(' ',0,80)]) + Markup('&hellip;')
    return short

@filter
def longmsg(message):
    message += "\n"
    short, long = message.split('\n', 1)
    if len(short) > 80:
        long = message
    long = re.sub(r'^[-a-z]+(-[a-z]+)*:.+\n', '', long, flags=re.MULTILINE|re.I).strip()
    if not long:
        return ""
    return Markup('<pre class="invisible">%s</pre>') % escape(long)

@filter
def acks(message):
    if '\n' not in message:
        return []
    acks = defaultdict(list)
    for ack, who in re.findall(r'^([-a-z]+(?:-[a-z]+)*):(.+?)(?:<.*)?\n', message.split('\n', 1)[1], flags=re.MULTILINE|re.I):
        ack = ack.lower().replace('-', ' ')
        ack = ack[0].upper() + ack[1:] # Can't use title
        acks[ack].append(who.strip())
    return sorted(acks.items())

@filter
def strftime(timestamp, format):
    return time.strftime(format, time.gmtime(timestamp))

@filter
def decode(data):
    return decode_(data)

@filter
def ornull(data):
    if isinstance(data, list):
        for d in data:
            if not isinstance(d, Undefined):
                data = d
                break
        else:
            return 'null'
    if isinstance(data, Undefined):
        return 'null'
    for attr in ('name', 'hex'):
        data = getattr(data, attr, data)
    return Markup('"%s"') % data

@filter
def highlight(data, search):
    return Markup(data).replace(Markup(search), Markup('<span class="searchresult">%s</span>' % Markup(search)))

@filter
def dlength(diff):
    return len(list(diff))

@filter('json')
def json_(data):
    data = my_deepcopy(data)
    return Markup(json.dumps(data))

re_class = re.compile('').__class__
def my_deepcopy(data):
    if isinstance(data, list):
        return [my_deepcopy(x) for x in data]
    elif isinstance(data, dict):
        return dict([(my_deepcopy(x), my_deepcopy(data[x])) for x in data])
    elif isinstance(data, datetime.datetime):
        return toutctimestamp(data)
    elif data.__class__ == re_class:
        return data.pattern
    return data

@filter
def humanize(data):
    if isinstance(data, dict):
        data = [Markup('<dt>%s</dt><dd>%s</dd>') % (humanize(x), humanize(data[x])) for x in sorted(data.keys())]
        return Markup('<dl>%s</dl>' % '\n'.join(data))
    if isinstance(data, list) or isinstance(data, tuple):
        data = [humanize(x) for x in data]
        return Markup('\n').join(data)
    return escape(str(data))

def register_filters(app):
    app.jinja_env.filters.update(filters)
