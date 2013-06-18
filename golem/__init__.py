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
