from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import os
from main import S3Uploader
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Change this in production
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
DB_PATH = 's3_servers.db'

# Helper to get all servers
def get_servers():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM s3_servers")
    servers = c.fetchall()
    conn.close()
    return servers

# Helper to get server config by id
def get_server_config(server_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM s3_servers WHERE id=?", (server_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'aws_access_key_id': row[2],
        'aws_secret_access_key': row[3],
        'aws_region': row[4],
        's3_endpoint_url': row[5],
        'bucket_name': row[6]
    }

@app.route('/')
def index():
    servers = get_servers()
    return render_template('index.html', servers=servers)

@app.route('/add-server', methods=['GET', 'POST'])
def add_server():
    if request.method == 'POST':
        name = request.form['name']
        aws_access_key_id = request.form['aws_access_key_id']
        aws_secret_access_key = request.form['aws_secret_access_key']
        aws_region = request.form['aws_region'] or 'us-east-1'
        s3_endpoint_url = request.form['s3_endpoint_url']
        bucket_name = request.form['bucket_name']
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO s3_servers (name, aws_access_key_id, aws_secret_access_key, aws_region, s3_endpoint_url, bucket_name) VALUES (?, ?, ?, ?, ?, ?)",
                  (name, aws_access_key_id, aws_secret_access_key, aws_region, s3_endpoint_url, bucket_name))
        conn.commit()
        conn.close()
        flash('Server added successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('add_server.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    servers = get_servers()
    if request.method == 'POST':
        server_id = request.form['server_id']
        file = request.files['file']
        make_public = 'make_public' in request.form
        if not file:
            flash('No file selected!', 'danger')
            return redirect(request.url)
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        config = get_server_config(server_id)
        uploader = S3Uploader(config)
        url = uploader.upload_file(filepath, filename, make_public)
        os.remove(filepath)
        if url:
            flash(f'File uploaded! <a href="{url}" target="_blank">View</a>', 'success')
        else:
            flash('Upload failed.', 'danger')
        return redirect(request.url)
    return render_template('upload.html', servers=servers)

@app.route('/upload-url', methods=['GET', 'POST'])
def upload_url():
    servers = get_servers()
    if request.method == 'POST':
        server_id = request.form['server_id']
        url = request.form['url']
        s3_key = request.form.get('s3_key')
        make_public = 'make_public' in request.form
        config = get_server_config(server_id)
        uploader = S3Uploader(config)
        result_url = uploader.upload_from_url(url, s3_key, make_public)
        if result_url:
            flash(f'File uploaded! <a href="{result_url}" target="_blank">View</a>', 'success')
        else:
            flash('Upload failed.', 'danger')
        return redirect(request.url)
    return render_template('upload_url.html', servers=servers)


# View files for a specific server
@app.route('/server/<int:server_id>/', methods=['GET'])
def server_files(server_id):
    server = None
    files = []
    servers = get_servers()
    for s in servers:
        if s[0] == server_id:
            server = s
            break
    if not server:
        flash('Server not found.', 'danger')
        return redirect(url_for('index'))
    config = get_server_config(server_id)
    uploader = S3Uploader(config)
    # List files using boto3 directly for structured data
    try:
        response = uploader.s3_client.list_objects_v2(Bucket=config['bucket_name'], MaxKeys=100)
        if 'Contents' in response:
            for obj in response['Contents']:
                # Check if public
                public_url = None
                is_public = False
                if config['s3_endpoint_url']:
                    public_url = f"{config['s3_endpoint_url'].rstrip('/')}/{config['bucket_name']}/{obj['Key']}"
                else:
                    public_url = f"https://{config['bucket_name']}.s3.{config['aws_region']}.amazonaws.com/{obj['Key']}"
                # Try to check ACL (optional, may fail if no permission)
                try:
                    acl = uploader.s3_client.get_object_acl(Bucket=config['bucket_name'], Key=obj['Key'])
                    for grant in acl['Grants']:
                        if grant.get('Grantee', {}).get('URI', '').endswith('AllUsers') and grant.get('Permission') == 'READ':
                            is_public = True
                except Exception:
                    pass
                files.append({
                    'Key': obj['Key'],
                    'Size': obj['Size'],
                    'LastModified': obj['LastModified'],
                    'Public': is_public,
                    'Url': public_url
                })
    except Exception as e:
        flash(f'Error listing files: {e}', 'danger')
    return render_template('server_files.html', server=server, files=files)

# Delete file directly from server files page
@app.route('/server/<int:server_id>/delete/<path:s3_key>', methods=['POST'])
def delete_file_direct(server_id, s3_key):
    config = get_server_config(server_id)
    uploader = S3Uploader(config)
    uploader.delete_file(s3_key)
    flash(f'File {s3_key} deleted (if it existed).', 'info')
    return redirect(url_for('server_files', server_id=server_id))

# Make file public
@app.route('/server/<int:server_id>/make-public/<path:s3_key>', methods=['POST'])
def make_public(server_id, s3_key):
    config = get_server_config(server_id)
    uploader = S3Uploader(config)
    try:
        uploader.s3_client.put_object_acl(Bucket=config['bucket_name'], Key=s3_key, ACL='public-read')
        flash(f'File {s3_key} is now public.', 'success')
    except Exception as e:
        flash(f'Failed to make public: {e}', 'danger')
    return redirect(url_for('server_files', server_id=server_id))

if __name__ == '__main__':
    app.run(debug=True)
