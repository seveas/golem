import datetime
import re
import os

class GolemError(Exception): pass
class GolemRetryLater(Exception): pass

class OutputLogger(object):
    def __init__(self, logger):
        self.logger = logger
        self.data = {}

    def __call__(self, cmd, sp, fd, data, *args, **kwargs):
        if data is None:
            if (sp.pid, fd) not in self.data:
                return
            data = self.data.pop((sp.pid, fd)) + '\n'
        else:
            data = self.data.pop((sp.pid, fd), '') + data
        while '\n' in data:
            line, data = data.split('\n', 1)
            self.logger.debug(line)
        if data:
            self.data[(sp.pid, fd)] = data

class RunLogger(object):
    env_blacklist = ['GIT_WORK_TREE', 'GIT_DIR']

    def __init__(self, logger):
        self.logger = logger

    def __call__(self, cmd):
        args = [_quote(x) for x in [cmd.name] + list(cmd.args)]
        env = cmd.sp_kwargs.get('env', '')
        if env:
            env = ['%s=%s' % (x, _quote(env[x])) for x in env if env[x] != os.environ.get(x, None) and x not in self.env_blacklist]
            env = '%s ' % ' '.join(env)
        self.logger.debug("Running %s%s" % (env, ' '.join(args)))

def _quote(cmd):
    if not cmd:
        return "''"
    if re.match(r'^[-0-9a-zA-Z@%_+=:,./]+$', cmd):
        return cmd
    return "'%s'" % cmd.replace("'", "'\"'\"'")

from ConfigParser import ConfigParser as CP
from ConfigParser import NoSectionError, NoOptionError

class ConfigParser(CP):
    def __init__(self, file, defaults={}):
        CP.__init__(self, defaults=defaults)
        self.optionxform = str
        self.read(file)

    def get(self, sections, option, raw=False):
        _defaults = self._defaults
        self._defaults = {}
        if isinstance(sections, basestring):
            sections = [sections]
        for section in sections:
            try:
                val = CP.get(self, section, option, raw, None)
            except NoSectionError:
                continue
            except NoOptionError:
                continue
            self._defaults = _defaults
            return val

        self._defaults = _defaults
        return CP.get(self, sections[-1],option, raw, None)

def now():
    return datetime.datetime.utcnow()
epoch = datetime.datetime.utcfromtimestamp(0)

def toutctimestamp(dt):
    return (dt - epoch).total_seconds()
