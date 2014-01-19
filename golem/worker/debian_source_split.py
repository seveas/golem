from golem.worker import Worker, GolemError
import glob
import os
import re
import shutil

class Daemon(Worker):
    repo_checkout = False

    def process_job_simple(self, job):
        self.logger.info("Splitting debian source packages")
        # Fetch package created in previous task
        orig_files = job.fetch_artefacts(job.requires[0], "*")

        for dsc in orig_files:
            if not dsc.endswith('.dsc'):
                continue
            # Unpack sources, and build extra packages
            job.shell.dpkg_source('-x', dsc)
            pkgdir = os.path.abspath(glob.glob("*/")[0]) # Ugly much?
            with open(os.path.join(pkgdir, 'debian', 'changelog')) as fd:
                line = fd.readline()
                version = re.search(r'(?<=\().*(?=\))', line).group(0)
            for release in job.release:
                self.logger.info("Building source package for release %s" % release)
                job.shell.sed('-e', '1s/(.*).*;/(%s~%s) %s;/' % (version, release, release), '-i', 'debian/changelog', cwd=pkgdir)
                args = getattr(job, 'debuild_args', ['-S', '-si'])
                if isinstance(args, basestring):
                    args = [args]
                job.shell.debuild(*args, cwd=pkgdir)
            shutil.rmtree(pkgdir)

        for changes in glob.glob('*.changes'):
            if changes in orig_files:
                continue
            for src in job.shell.dcmd(changes).stdout.strip().split():
                if os.path.exists(src): # Can't move the orig.tar.gz more than once
                    os.rename(src, os.path.join(job.artefact_path, os.path.basename(src)))
