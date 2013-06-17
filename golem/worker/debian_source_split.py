from golem.worker import Worker, GolemError
import glob
import os
import re

class Daemon(Worker):
    name = 'debian-source-split'
    logger = 'golem.worker.debian-source-split'
    queue = 'golem-build-debian-source-split'
    repo_checkout = False

    def process_job_simple(self, job):
        self.logger.info("Building debian source packages")
        # Fetch tarball created in previous task
        orig_files = job.fetch_artefacts(job.requires[0], "*")
        dsc = [x for x in orig_files if x.endswith('.dsc')][0]

        # Unpack sources, and build extra packages
        job.shell.dpkg_source('-x', dsc)
        pkgdir = os.path.abspath(glob.glob("*/")[0]) # Ugly much?
        with open(os.path.join(pkgdir, 'debian', 'changelog')) as fd:
            line = fd.readline()
            version = re.search(r'(?<=\().*(?=\))', line).group(0)
        for release in job.release:
            self.logger.info("Building source package for release %s" % release)
            job.shell.sed('-e', '1s/(.*).*;/(%s~%s) %s;/' % (version, release, release), '-i', 'debian/changelog', cwd=pkgdir)
            job.shell.debuild('-S', '-si', cwd=pkgdir)

        for changes in glob.glob('*.changes'):
            if changes in orig_files:
                continue
            for src in job.shell.dcmd(changes).stdout.strip().split():
                if os.path.exists(src): # Can't move the orig.tar.gz more than once
                    os.rename(src, os.path.join(job.artefact_path, os.path.basename(src)))
