from golem.notifier import Notifier
from email.mime.text import MIMEText
import os
import smtplib
import uuid

class Daemon(Notifier):
    def process_job_simple(self, job):
        self.logger.info("Emailing log to %s" % job.to)
        with open(os.path.join(job.artefact_path, 'log')) as fd:
            log = fd.read()
        gitlog = job.shell.git('shortlog', '--format=[%h] %s', '%s..%s' % (job.prev_sha1, job.sha1))
        preprocess = getattr(job, 'preprocess_log')
        if preprocess:
            log = job.shell[preprocess](input=log).stdout
        self.send_log(job, '\n'.join(gitlog, log))

    def send_log(self, job, log):
        message = self.prepare_message(job, log)
        server = smtplib.SMTP(self.config['smtp_server'])
        server.sendmail(job.from_, [job.to], message.as_string())
        server.quit()

    def prepare_message(self, job, log):
        message = MIMEText(log)
        message.set_charset('utf-8')
        result = {'fail': 'failed', 'success': 'succeeed'}[job.result]
        duration = job.duration
        dur = []
        if duration > 3600:
            h = int(duration / 3600)
            dur.append('%d %s' % (h, 'hour' if h == 1 else 'hours'))
            duration %= 3600
        if duration > 60:
            m = int(duration / 60)
            dur.append('%d %s' % (m, 'minute' if m == 1 else 'minutes'))
            duration %= 60
        dur.append('%d %s' % (duration, 'second' if duration == 1 else 'seconds'))
        if len(dur) == 2:
            duration = ' and '.join(dur)
        else:
            duration = '%s, %s and %s' % dur
        message['Subject'] = 'Action %s for %s %s@%s %s in %s' % (job.action, job.repo, job.ref, job.sha1, result, duration)
        message['From'] = job.from_
        message['To'] = job.to
        message['Message-Id'] = '<%s@golem-ci>' % uuid.uuid4().hex
        return message
