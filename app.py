from flask import Flask, render_template, redirect, url_for, request
from flask_admin import Admin, BaseView, expose, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
import xmlrpc.client
import json
from datetime import datetime
import pytz
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # Replace with your own secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/your_database.db'  # SQLite database path

db = SQLAlchemy(app)

class ManagedSupervisor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    host = db.Column(db.String(50), nullable=False)
    url = db.Column(db.String(200), nullable=False)
    processes = db.relationship('Process', backref='managed_supervisor', lazy=True)

    @staticmethod
    def load_from_json():
        with open(managed_supervisors_conf_path, 'r') as file:
            data = json.load(file)
        for supervisor in data['managed_supervisors']:
            ms = ManagedSupervisor(host=supervisor['host'], url=supervisor['url'])
            db.session.add(ms)
            for process in supervisor['processes']:
                p = Process(name=process, managed_supervisor=ms)
                db.session.add(p)
        db.session.commit()

class Process(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    managed_supervisor_id = db.Column(db.Integer, db.ForeignKey('managed_supervisor.id'), nullable=False)

class SupervisorModelView(ModelView):
    form_columns = ['host', 'url', 'processes']

admin = Admin(app, name='My App', template_mode='bootstrap3')
admin.add_view(SupervisorModelView(ManagedSupervisor, db.session))
admin.add_view(ModelView(Process, db.session))

# Supervisor設定ファイルのパス
managed_supervisors_conf_path = 'managed_supervisors.json'

# JSON形式の設定ファイルからホストごとの情報を取得
with open(managed_supervisors_conf_path, 'r') as file:
    config = json.load(file)

managed_supervisors = config['managed_supervisors']

# UNIXタイムスタンプをJSTに変換する関数
def convert_to_jst(unix_timestamp):
    utc_time = datetime.utcfromtimestamp(unix_timestamp)
    jst_time = utc_time.replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Tokyo'))
    return jst_time.strftime('%Y-%m-%d %H:%M:%S')

# ルートURLに対するリクエストを処理
@app.route('/')
def get_process_status():
    status = []
    for supervisor in managed_supervisors:
        supervisor_url = supervisor['url']
        process_names = supervisor['processes']
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
            'host': supervisor['host'],
            'url': supervisor_url,
            'processes': processes
        })
    return render_template('status.html', status=status)

@app.route('/start/<host>/<process_name>')
def start_process(host, process_name):
    for supervisor in managed_supervisors:
        if supervisor['host'] == host:
            supervisor_url = supervisor['url']
            with xmlrpc.client.ServerProxy(supervisor_url) as server:
                try:
                    server.supervisor.startProcess(process_name)
                except xmlrpc.client.Fault as err:
                    print(f"Error: {err.faultString}")
    return redirect(url_for('get_process_status'))

@app.route('/stop/<host>/<process_name>')
def stop_process(host, process_name):
    for supervisor in managed_supervisors:
        if supervisor['host'] == host:
            supervisor_url = supervisor['url']
            with xmlrpc.client.ServerProxy(supervisor_url) as server:
                try:
                    server.supervisor.stopProcess(process_name)
                except xmlrpc.client.Fault as err:
                    print(f"Error: {err.faultString}")
    return redirect(url_for('get_process_status'))

@app.route('/restart/<host>/<process_name>')
def restart_process(host, process_name):
    for supervisor in managed_supervisors:
        if supervisor['host'] == host:
            supervisor_url = supervisor['url']
            with xmlrpc.client.ServerProxy(supervisor_url) as server:
                try:
                    server.supervisor.stopProcess(process_name)
                    server.supervisor.startProcess(process_name)
                except xmlrpc.client.Fault as err:
                    print(f"Error: {err.faultString}")
    return redirect(url_for('get_process_status'))

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
        processes = form.processes.data
        # Save the data to the JSON file
        with open(managed_supervisors_conf_path, 'r') as file:
            data = json.load(file)
        data['managed_supervisors'] = [{'host': host, 'url': url, 'processes': processes.split(',')}]
        with open(managed_supervisors_conf_path, 'w') as file:
            json.dump(data, file)
        return redirect(url_for('home'))
    return render_template('supervisor_setting.html', form=form)

# Add current_time to the application context
app.jinja_env.globals.update(current_time=datetime.now)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Add this line
    app.run(debug=True)
