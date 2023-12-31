from flask import Flask, render_template, redirect, url_for, request
from flask_admin import Admin, BaseView, expose, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_admin.contrib.sqla.ajax import QueryAjaxModelLoader
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, FieldList, FormField
from wtforms.form import Form
import xmlrpc.client
import json
from datetime import datetime
import pytz
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from sqlalchemy_utils import database_exists, create_database

db = SQLAlchemy()

class ManagedSupervisor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    host = db.Column(db.String(50), nullable=False)
    url = db.Column(db.String(200), nullable=False)
    processes = db.relationship('Process', backref='managed_supervisor', lazy=True)

class Process(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    managed_supervisor_id = db.Column(db.Integer, db.ForeignKey('managed_supervisor.id'), nullable=False)

class ProcessForm(Form):
    name = StringField('Name')

class ProcessAjaxModelLoader(QueryAjaxModelLoader):
    def get_list(self, term, offset=0, limit=10):
        query = self.session.query(self.model)

        filters = (self.model.name.contains(term),)

        if self.filters:
            filters += tuple(self.filters)

        query = query.filter(or_(*filters))

        if self.order_by:
            query = query.order_by(self.order_by)

        results = query.offset(offset).limit(limit).all()

        # Customize the format of the results
        results = [(str(getattr(item, self.get_pk_value(item))) + " - " + getattr(item, self.value_field), item) for item in results]

        return results

class SupervisorModelView(ModelView):
    form_columns = ['host', 'url', 'processes']
    column_list = ('host', 'url', 'processes')
    column_formatters = {
        'processes': lambda v, c, m, p: ', '.join([proc.name for proc in m.processes])
    }
    form_ajax_refs = {
        'processes': ProcessAjaxModelLoader('processes', db.session, Process, fields=['name'], page_size=10, placeholder='Please select a process')
    }

class ProcessModelView(ModelView):
    column_list = ('name', 'managed_supervisor.host')
    column_labels = {
        'managed_supervisor.host': 'Managed Supervisor Host'
    }

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'your-secret-key'  # Replace with your own secret key
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/your_database.db'  # SQLite database path

    db.init_app(app)

    with app.app_context():
        if not database_exists(app.config['SQLALCHEMY_DATABASE_URI']):
            create_database(app.config['SQLALCHEMY_DATABASE_URI'])
        db.create_all()  # Create the database tables

    return app

app = create_app()

admin = Admin(app, name='My App', template_mode='bootstrap3')
admin.add_view(SupervisorModelView(ManagedSupervisor, db.session))
admin.add_view(ProcessModelView(Process, db.session))

def convert_to_jst(timestamp):
    utc_time = datetime.utcfromtimestamp(timestamp)
    utc_time = pytz.utc.localize(utc_time)
    jst_time = utc_time.astimezone(pytz.timezone('Asia/Tokyo'))
    return jst_time

@app.route('/')
def get_process_status():
    status = []
    for supervisor in ManagedSupervisor.query.all():
        supervisor_url = supervisor.url
        process_names = [process.name for process in supervisor.processes]
        processes = []
        try:
            with xmlrpc.client.ServerProxy(supervisor_url) as server:
                for process_name in process_names:
                    try:
                        info = server.supervisor.getProcessInfo(process_name)
                        processes.append({
                            'name': info['name'],
                            'start': convert_to_jst(info['start']),
                            'stop': convert_to_jst(info['stop']),
                            'state': info['statename']
                        })
                    except xmlrpc.client.Fault as err:
                        processes.append({'error': err.faultString})
        except Exception as e:
            processes.append({'error': f"Failed to connect to {supervisor_url}. Error: {str(e)}"})
        status.append({
            'host': supervisor.host,
            'url': supervisor_url,
            'processes': processes
        })
    return render_template('status.html', status=status)

@app.route('/start/<host>/<process_name>')
def start_process(host, process_name):
    for supervisor in ManagedSupervisor.query.all():
        if supervisor.host == host:
            supervisor_url = supervisor.url
            with xmlrpc.client.ServerProxy(supervisor_url) as server:
                try:
                    result = server.supervisor.startProcess(process_name)
                    if result:  # If the process was successfully started
                        return redirect(url_for('get_process_status'))
                except xmlrpc.client.Fault as err:
                    return 'Error: ' + err.faultString, 500
    return 'Error: Could not start process', 500

@app.route('/stop/<host>/<process_name>')
def stop_process(host, process_name):
    for supervisor in ManagedSupervisor.query.all():
        if supervisor.host == host:
            supervisor_url = supervisor.url
            with xmlrpc.client.ServerProxy(supervisor_url) as server:
                try:
                    result = server.supervisor.stopProcess(process_name)
                    if result:  # If the process was successfully stopped
                        return redirect(url_for('get_process_status'))
                except xmlrpc.client.Fault as err:
                    return 'Error: ' + err.faultString, 500
    return 'Error: Could not stop process', 500

@app.route('/restart/<host>/<process_name>')
def restart_process(host, process_name):
    for supervisor in ManagedSupervisor.query.all():
        if supervisor.host == host:
            supervisor_url = supervisor.url
            with xmlrpc.client.ServerProxy(supervisor_url) as server:
                try:
                    result = server.supervisor.restartProcess(process_name)
                    if result:  # If the process was successfully restarted
                        return redirect(url_for('get_process_status'))
                except xmlrpc.client.Fault as err:
                    return 'Error: ' + err.faultString, 500
    return 'Error: Could not restart process', 500

class SupervisorForm(FlaskForm):
    host = StringField('Host')
    url = StringField('URL')
    processes = StringField('Processes')
    submit = SubmitField('Submit')

@app.route('/', methods=['GET', 'POST'])
def home():
    form = SupervisorForm()
    if form.validate_on_submit():
        # Process the form data
        host = form.host.data
        url = form.url.data
        processes = form.processes.data.split(',')
        # Check if the supervisor already exists
        existing_supervisor = ManagedSupervisor.query.filter_by(host=host, url=url).first()
        if not existing_supervisor:
            # Create a new ManagedSupervisor and save it to the database
            ms = ManagedSupervisor(host=host, url=url)
            db.session.add(ms)
            for process in processes:
                p = Process(name=process, managed_supervisor=ms)
                db.session.add(p)
            db.session.commit()
        return redirect(url_for('home'))
    return render_template('supervisor_setting.html', form=form)


# Add current_time to the application context
app.jinja_env.globals.update(current_time=datetime.now)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
