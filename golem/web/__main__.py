from flask import Flask, g
import golem.web.views as v
import golem.web.filters
from golem.web.encoding import decode
import os

class Defaults:
    MAX_SEARCH_DEPTH = 2
    USE_X_SENDFILE = False
    USE_X_ACCEL_REDIRECT = False
    ADMINS         = []
    SENDER         = 'webmaster@localhost'
    DEBUG          = os.environ.get('GOLEM_DEBUG', 'False').lower() == 'true'
    THEME          = 'default'

class Golem(Flask):
    def __call__(self, environ, start_response):
        def x_accel_start_response(status, headers, exc_info=None):
            if self.config['USE_X_ACCEL_REDIRECT']:
                for num, (header, value) in enumerate(headers):
                    if header == 'X-Sendfile':
                        fn = value[value.rfind('/')+1:]
                        if os.path.exists(os.path.join(self.config['CACHE_ROOT'], fn)):
                            headers[num] = ('X-Accel-Redirect', '/artefacts/' + fn)
                        break
            return start_response(status, headers, exc_info)
        return super(Golem, self).__call__(environ, x_accel_start_response)

app = Golem(__name__)
app.config.from_object(Defaults)
if 'GOLEM_SETTINGS' in os.environ:
    app.config.from_envvar("GOLEM_SETTINGS")

# Configure parts of flask/jinja
golem.web.filters.register_filters(app)
@app.context_processor
def inject_functions():
    return {
        'decode': decode,
        'sorted': sorted,
        'isorted': lambda x: sorted(x, key=lambda y: y.lower()),
    }

@app.before_request
def before_request():
    g.db = app.config['DB'].connect()

@app.teardown_request
def teardown_request(exception):
    db = getattr(g, 'db', None)
    if db is not None:
        db.close()

app.template_folder = os.path.join('themes', app.config['THEME'], 'templates')
app.static_folder = os.path.join('themes', app.config['THEME'], 'static')

# URL structure
app.add_url_rule('/', view_func=v.IndexView.as_view('index'))
app.add_url_rule('/queues/', view_func=v.QueueView.as_view('queues'))
app.add_url_rule('/<repo>/', view_func=v.RepoView.as_view('repo'))
app.add_url_rule('/<repo>/<path:ref>/<sha1>/', view_func=v.RunView.as_view('run'))
app.add_url_rule('/<repo>/<path:ref>/<sha1>/artefact/<action>/<path:filename>', view_func=v.ArtefactView.as_view('artefact'))

# Logging
if not app.debug and app.config['ADMINS']:
    import logging
    from logging.handlers import SMTPHandler
    mail_handler = SMTPHandler('127.0.0.1', app.config['SENDER'], app.config['ADMINS'], "Golem error")
    mail_handler.setLevel(logging.ERROR)
    app.logger.addHandler(mail_handler)

if __name__ == '__main__':
    app.run()
