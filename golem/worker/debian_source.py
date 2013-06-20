from golem.worker import Worker, GolemError, GolemRetryLater
import glob
import os
import re

class Daemon(Worker):
    repo_checkout = False

    def process_job_simple(self, job):
        self.logger.info("Building debian source package(s)")

        # Fetch tarball created in previous task
        files = job.fetch_artefacts(job.requires[0], job.tarball)

        # If version script: get version from there
        if hasattr(job, 'version_script'):
            # Check out debian dir
            job.run_hook('pre-debian-checkout')
            job.shell.git('checkout', job.debian_branch, '--', 'debian')
            job.run_hook('post-debian-checkout')

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

            job.run_hook('pre-version-mangle')
            job.version_script.append(job.commit)
            res = job.shell[job.version_script[0]](*job.version_script[1:])
            gitversion = res.stdout.strip()

            if gitversion != version:
                if epoch:
                    v = '%s:%s-1' % (epoch, gitversion)
                else:
                    v = '%s-1' % gitversion
                job.shell.dch('-v', v, '-u', 'low', '--distribution', dist, "Automated rebuild from git commit %s" % job.commit)
            job.run_hook('post-version-mangle')

        # Do we have debian/* tags?
        elif getattr(job, 'use_tags', 'no').lower() in ('true', 't', 'yes', 'y', '1'):
            # Do we have a debian tag?
            tags = job.shell.git('tag', '-l', 'debian/%s*' % job.ref[10:]).stdout.strip().split()
            if not tags:
                raise GolemRetryLater("Debian tag not found yet")
            else:
                tags.sort()
                job.run_hook('pre-debian-checkout')
                job.shell.git('checkout', tags[-1], '--', 'debian')
                job.run_hook('post-debian-checkout')

        # Detect the commit on the debian branch
        else:
            # Which commit on the debian branch do we want:
            # - Assume master is always merged into debian
            # - Go through the first-parent history of debian..current_commit
            # - If the earliest commit isn't a merge containing a debian dir: unclean merge, abort
            # - Walk forward in history until encountering another merge, we want the one just before that
            commits = job.shell.git('rev-list', '--parents', '--ancestry-path', 
                                    '--first-parent', '%s..%s' % (job.commit, job.debian_branch))
            commits = [x.split() for x in commits.stdout.splitlines()]
            commits.reverse() # Let's walk forward in time
            if not commits:
                # No commit added yet
                # Try without --first-parent to see if there is *any* path
                commits = job.shell.git('rev-list', '--parents', '--ancestry-path', 
                                        '%s..%s' % (job.commit, job.debian_branch))
                if commits.stdout.strip():
                    raise GolemError("First commit after %s is not a merge into the %s branch" % (job.ref, job.debian_branch))
                raise GolemRetryLater()
            if len(commits[0]) != 3:
                raise GolemError("First commit after %s is not a merge into the %s branch" % (job.ref, job.debian_branch))
            if not job.shell.git('ls-tree', commits[0][0], 'debian').stdout.strip():
                raise GolemError("First commit after %s is not a merge into the %s branch" % (job.ref, job.debian_branch))

            good_commit = commits[0][0]
            for commit in commits[1:]:
                if len(commit) > 2:
                    break
                else:
                    good_commit = commit[0]

            job.run_hook('pre-debian-checkout')
            job.shell.git('checkout', good_commit, '--', 'debian')
            job.run_hook('post-debian-checkout')

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

        # Rename tarball to what debuild expects
        tarball = files[0]
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
        args = getattr(job, 'debuild_args', ['-S', '-si'])
        if isinstance(args, basestring):
            args = [args]
        job.shell.debuild(*args, cwd=pkgdir)
        job.run_hook('post-build', cwd=pkgdir)

        changesfile = '%s_%s-%s_source.changes' % (pkgname, version, release)
        for src in job.shell.dcmd(changesfile).stdout.strip().split():
            os.rename(src, os.path.join(job.artefact_path, os.path.basename(src)))
