import datetime

class GolemError(Exception): pass
class GolemRetryLater(Exception): pass

class CmdLogger(object):
    def __init__(self, logger, logfd=None):
        self.logger = logger
        self.data = {}
        self.logfd = logfd

    def __call__(self, shell, sp, fd, data, *args, **kwargs):
        if data is None:
            if (sp.pid, fd) not in self.data:
                return
            data = self.data.pop((sp.pid, fd)) + '\n'
        else:
            data = self.data.pop((sp.pid, fd), '') + data
        while '\n' in data:
            line, data = data.split('\n', 1)
            self.logger.debug(line)
            if self.logfd:
                self.logfd.write(line + "\n")
                self.logfd.flush()
        if data:
            self.data[(sp.pid, fd)] = data

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
