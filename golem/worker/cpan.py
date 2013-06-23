from golem.worker import Worker
from golem import GolemError, ConfigParser
import os, sys
import requests
import getpass

class Daemon(Worker):
    repo_sync = False
    pause_url = 'https://pause.perl.org/pause/authenquery'

    def __init__(self, *args, **kwargs):
        super(Daemon, self).__init__(*args, **kwargs)
        p = ConfigParser(os.path.join(os.path.expanduser('~'), '.pause'))
        self.username = p.get('pause', 'username')
        self.password = p.get('pause', 'password')

    def process_job_simple(self, job):
        self.logger.info("Uploading to pause.perl.org")
        files = job.fetch_artefacts(job.requires[0], job.tarball)
        for file in files:
            resp = requests.post(self.pause_url, auth=(self.username, self.password),
                data = {
                    'HIDDENNAME': self.username,
                    'CAN_MULTIPART': '1',
                    'pause99_add_uri_uri': "",
                    'pause99_add_uri_subdirtext': "",
                    'SUBMIT_pause99_add_uri_httpupload': " Upload this file from my disk "
                },
                files = {'pause99_add_uri_httpupload': (os.path.basename(file), open(file, 'rb'))}
            )
            if resp.status_code != 200:
                raise GolemError("Upload failed: %s" % resp.text)

    @classmethod
    def login(klass):
        cf = os.path.join(os.path.expanduser('~'), '.pause')
        if os.path.exists(cf):
            print >>sys.stderr, "%s already exists. Remove to relogin" % cf
            sys.exit(1)
        user = raw_input("CPAN user: ").strip()
        password = getpass.getpass("Pause password: ")
        resp = requests.get(klass.pause_url, auth=(user, password))
        if resp.status_code != 200:
            print >>sys.stderr, "Login failed"
            sys.exit(1)
        with open(cf,'w') as fd:
            fd.write('[pause]\nusername = %s\npassword = %s\n' % (user, password))
