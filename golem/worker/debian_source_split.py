from golem.worker import Worker, GolemError
import csv
import glob
import os
import re
import requests
import shutil
import stat
import time

class Daemon(Worker):
    repo_checkout = False
    distro_info = {
        'debian': 'http://anonscm.debian.org/cgit/collab-maint/distro-info-data.git/plain/debian.csv',
        'ubuntu': 'http://anonscm.debian.org/cgit/collab-maint/distro-info-data.git/plain/ubuntu.csv',
    }

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
            for release in self.expand_releases(job.release):
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

    def expand_releases(self, releases):
        if isinstance(releases, basestring):
            releases = [releases]
        cache = os.path.join(os.path.expanduser('~'), '.cache', 'distro-info-data')
        if not os.path.exists(cache):
            os.makedirs(cache)
        now = time.time()
        today = time.strftime('%Y-%m-%d')
        distinfo = {}
        for name,url in self.distro_info.items():
            path = os.path.join(cache, name)
            if not os.path.exists(path) or os.stat(path)[stat.ST_MTIME] < now - 604800:
                with open(path,'w') as fd:
                    fd.write(requests.get(url).text)
            with open(path) as fd:
                distinfo[name] = list(csv.DictReader(fd))

        for release in releases:
            if not release.endswith('+'):
                yield release
                continue
            release = release[:-1]
            for dist in self.distro_info:
                data = distinfo[dist]
                if release in [r['series'] for r in data]:
                    oldest = [r['created'] for r in data if r['series'] == release][0]
                    for release in data:
                        if (release['created'] >= oldest and                    # Filter out older releases
                            release['created'] < today and                      # Debian lists upcoming not-yet-created releases
                            (release['eol'] > today or not release['eol']) and  # active Debian releases may not have an eol set
                            release['version']):                                # experimental/sid don't have versions
                            yield release['series']
