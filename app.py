from flask import Flask, render_template, redirect, url_for
import xmlrpc.client
import json
from datetime import datetime
import pytz

app = Flask(__name__)

# Supervisor設定ファイルのパス
supervisor_conf_path = 'supervisor.json'

# JSON形式の設定ファイルからホストごとの情報を取得
with open(supervisor_conf_path, 'r') as file:
    config = json.load(file)

supervisors = config['supervisors']

# UNIXタイムスタンプをJSTに変換する関数
def convert_to_jst(unix_timestamp):
    utc_time = datetime.utcfromtimestamp(unix_timestamp)
    jst_time = utc_time.replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Asia/Tokyo'))
    return jst_time.strftime('%Y-%m-%d %H:%M:%S')

# ルートURLに対するリクエストを処理
@app.route('/')
def get_process_status():
    status = []
    for supervisor in supervisors:
        supervisor_url = supervisor['url']
        process_names = supervisor['processes']
        processes = []
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
        status.append({
            'host': supervisor['host'],
            'url': supervisor_url,
            'processes': processes
        })
    return render_template('status.html', status=status)

@app.route('/start/<host>/<process_name>')
def start_process(host, process_name):
    for supervisor in supervisors:
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
    for supervisor in supervisors:
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
    for supervisor in supervisors:
        if supervisor['host'] == host:
            supervisor_url = supervisor['url']
            with xmlrpc.client.ServerProxy(supervisor_url) as server:
                try:
                    server.supervisor.stopProcess(process_name)
                    server.supervisor.startProcess(process_name)
                except xmlrpc.client.Fault as err:
                    print(f"Error: {err.faultString}")
    return redirect(url_for('get_process_status'))

# Add current_time to the application context
app.jinja_env.globals.update(current_time=datetime.now)

if __name__ == '__main__':
    app.run(debug=True)

