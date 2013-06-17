from golem.worker import Worker, GolemError
import glob
import os
import re

class Daemon(Worker):
    name = 'debian-source'
    logger = 'golem.worker.debian-source'
    queue = 'golem-build-debian-source'
    repo_checkout = False

    def process_job_simple(self, job):
        self.logger.info("Building debian source package(s)")

        # Fetch tarball created in previous task
        job.fetch_artefacts(job.requires[0], job.tarball)

        # Check out debian dir
        job.shell.git('checkout', job.debian_branch, '--', 'debian')

        # Get version from debian dir
        with open('debian/changelog') as fd:
            version_line = fd.readline()

        pkgname, epoch, version, release, dist, urgency = re.match('''^
            (\S+)
            \s+
            \(
                (?:(\d+):)?
                ([^)]+)
                -([^)]+)
            \)
            \s+
            (\S+)
            \s*;\s*urgency\s*=\s*
            (\S+)
            $''', version_line, re.VERBOSE).groups()

        # If version script: get version from there
        if hasattr(job, 'version_script'):
            job.run_hook('pre-version-mangle', cwd=pkgdir)
            job.version_script.append(job.commit)
            res = job.shell[job.version_script[0]](*job.version_script[1:])
            gitversion = res.stdout.strip()

            if gitversion != version:
                if epoch:
                    v = '%s:%s-1' % (epoch, gitversion)
                else:
                    v = '%s-1' % gitversion
                job.shell.dch('-v', v, '-u', 'low', '--distribution', dist, "Automated rebuild from git commit %s" % job.commit)
                version = gitversion
                release = '1'
            job.run_hook('post-version-mangle', cwd=pkgdir)

        # Rename tarball to what debuild expects
        tarball = glob.glob(job.tarball)[0]
        ext = tarball[tarball.rfind('tar'):]
        orig = '%s_%s.orig.%s' % (pkgname, version, ext)
        os.rename(tarball, orig)

        # Now work from the clean tarball
        job.shell.tar('-x', '-f', orig)
        dirname = job.shell.tar('-tf', orig, output_callback=None).stdout.split('\n')[0]
        dirname = dirname[:dirname.find('/')]
        pkgdir = '%s-%s' % (pkgname, version)
        os.rename(dirname, pkgdir)
        os.rename('debian', os.path.join(pkgdir, 'debian'))
        job.run_hook('pre-build', cwd=pkgdir)
        job.shell.debuild('-S', '-si', cwd=pkgdir)
        job.run_hook('post-build', cwd=pkgdir)

        changesfile = '%s_%s-%s_source.changes' % (pkgname, version, release)
        for src in job.shell.dcmd(changesfile).stdout.strip().split():
            os.rename(src, os.path.join(job.artefact_path, os.path.basename(src)))
