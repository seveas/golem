import beanstalkc
import json
import logging
import os
import sys
import traceback
import golem.repository
import golem.db

class Daemon(object):
    def __init__(self, logger, bs_host, bs_port, bs_queue):
        self.logger = logging.getLogger(logger)

        # Set up a beanstalk connection
        self.bs_host, self.bs_port = bs_host, bs_port
        self.bs_queue = bs_queue
        self.connect()

    def connect(self):
        self.bs = beanstalkc.Connection(host=self.bs_host, port=self.bs_port)
        self.bs.watch(self.bs_queue)

    def run(self):
        while True:
            try:
                job = self.find_update()
                ret = self.process_job(job)
                job.delete()
                if not ret:
                    break
            except Exception:
                for line in traceback.format_exc().split('\n'):
                    self.logger.error(line)
                job.bury()
                os.chdir('/')
            # Try to remove extraneous logging handlers to avoid logging infinitely after an error
            for handler in self.logger.handlers[:]:
                if getattr(handler, 'is_job_handler', False):
                    handler.close()
                    self.logger.removeHandler(handler)
                    del(handler)

    def find_update(self):
        self.logger.info("Waiting for update")
        try:
            return self.bs.reserve()
        except Exception, e:
            self.logger.error("Connection to beanstalk failed: %s, reconnecting" % str(e))
            self.connect()
            return self.bs.reserve()

    def daemonize(self, pidfile):
        # First fork
        try:
            if os.fork() > 0:
                sys.exit(0)     # kill off parent
        except OSError, e:
            sys.stderr.write("fork #1 failed: (%d) %s\n" % (e.errno, e.strerror))
            sys.exit(1)
        os.setsid()
        os.chdir('/')
        os.umask(022)

        # Second fork
        try:
            if os.fork() > 0:
                os._exit(0)
        except OSError, e:
            sys.stderr.write("fork #2 failed: (%d) %s\n" % (e.errno, e.strerror))
            os._exit(1)

        with open(pidfile, 'w') as fd:
            fd.write('%s\n' % os.getpid())
        si = open('/dev/null', 'r')
        so = open('/dev/null', 'a+', 0)
        se = open('/dev/null', 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())
        sys.stdout, sys.stderr = so, se

class Master(Daemon):
    def __init__(self, logger, bs_host, bs_port, bs_queue, repo_dir, chems, db, do_update):
        super(Master, self).__init__(logger, bs_host, bs_port, bs_queue)
        # Read repositories
        self.repos = {}
        self.repo_dir = repo_dir
        self.chems = chems
        self.engine = golem.db.create_engine(db, pool_recycle=3600)
        golem.db.metadata.create_all(self.engine)
        self.read_repos()
        gh = None
        for repo in self.repos.values():
            if repo.reflogtype == 'github' and not gh:
                self.logger.info("Verifying github login")
                gh = golem.repository.github()
            if do_update:
                self.logger.info("Updating %s" % repo.name)
                repo.update()

    def read_repos(self):
        self.logger.info("Loading repositories from %s" % self.chems)
        db = self.engine.connect()
        for file in os.listdir(self.chems):
            if not file.endswith('.conf'):
                continue
            repo = golem.repository.Repository(self, os.path.join(self.chems, file), db)
            self.repos[repo.name] = repo
        db.close()

    def process_job(self, job):
        try:
            job = json.loads(job.body)
        except ValueError:
            self.logger.warn("Invalid JSON received: %s" % job)
            job.bury()
        if job['repo'] in ('quit', 'exit'):
            self.logger.info("Exiting")
            return False
        else:
            db = self.engine.connect()
            if job['repo'] not in self.repos:
                # Are there new configfiles?
                confs = [x.configfile for x in self.repos.values()]
                for file in os.listdir(self.chems):
                    if not file.endswith('.conf') or file in confs:
                        continue
                repo = golem.repository.Repository(self, os.path.join(self.chems, file), db)
                self.repos[repo.name] = repo
                if job['repo'] not in self.repos:
                    self.logger.warning("Ignoring update for unknown repository %s" % job['repo'])
                    return True
            repo = self.repos[job['repo']]
            if not os.path.exists(repo.configfile):
                del self.repos[job['repo']]
                self.logger.warning("Ignoring update for removed repository %s" % job['repo'])
                return True

            self.logger.info("Update found for repo %s" % repo.name)
            if os.path.getmtime(repo.configfile) > repo.mtime:
                self.logger.info("Rereading configuration for %s" % repo.name)
                repo = self.repos[job['repo']] = golem.repository.Repository(self, repo.configfile, db)
            if job['why'] in ('post-receive', 'reschedule'):
                repo.update()
            repo.schedule(job, db)
            db.close()
        os.chdir('/')
        return True
