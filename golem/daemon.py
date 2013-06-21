import beanstalkc
import json
import logging
import os
import sys
import traceback
import golem.repository

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

    def find_update(self):
        self.logger.info("Waiting for update")
        try:
            return self.bs.reserve()
        except Exception, e:
            self.logger.error("Connection to beanstalk failed: %s, reconnecting" % str(e))
            self.connect()
            return self.bs.reserve()

    def daemonize(self):
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

        si = open('/dev/null', 'r')
        so = open('/dev/null', 'a+', 0)
        se = open('/dev/null', 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())
        sys.stdout, sys.stderr = so, se

class Master(Daemon):
    def __init__(self, logger, bs_host, bs_port, bs_queue, repo_dir, chems):
        super(Master, self).__init__(logger, bs_host, bs_port, bs_queue)
        # Read repositories
        self.repos = {}
        self.repo_dir = repo_dir
        self.chems = chems
        self.read_repos()
        for repo in self.repos.values():
            if repo.reflogtype == 'github':
                golem.repository.github()

    def read_repos(self):
        self.logger.info("Loading repositories from %s" % self.chems)
        for file in os.listdir(self.chems):
            repo = golem.repository.Repository(self, os.path.join(self.chems, file))
            self.repos[repo.name] = repo
            self.logger.info("Updating %s" % repo.name)
            repo.update()

    def process_job(self, job):
        try:
            job = json.loads(job.body)
        except ValueError:
            self.logger.warn("Invalid JSON received: %s" % job)
            job.bury()
        if job['repo'] in ('quit', 'exit'):
            self.logger.info("Exiting")
            return False
        elif job['repo'] == 'reload':
            self.repos = {}
            self.read_repos()
        else:
            if job['repo'] not in self.repos:
                self.logger.warning("Ignoring update for unknown repository %s" % job['repo'])
            else:
                self.logger.info("Update found for repo %s" % job['repo'])
                if job['update']:
                    self.repos[job['repo']].update()
                self.repos[job['repo']].schedule(job['ref'], job['old-sha1'], job['new-sha1'])
        os.chdir('/')
        return True
