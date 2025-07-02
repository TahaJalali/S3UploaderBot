
import boto3
import sys
import sqlite3
import os
from pathlib import Path
from botocore.exceptions import ClientError, NoCredentialsError

class S3Uploader:
    def __init__(self, config):
        self.aws_access_key_id = config['aws_access_key_id']
        self.aws_secret_access_key = config['aws_secret_access_key']
        self.aws_region = config['aws_region']
        self.s3_endpoint_url = config['s3_endpoint_url']
        self.bucket_name = config['bucket_name']
        try:
            if self.s3_endpoint_url:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                    region_name=self.aws_region,
                    endpoint_url=self.s3_endpoint_url
                )
            else:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                    region_name=self.aws_region
                )
        except Exception as e:
            raise Exception(f"Failed to initialize S3 client: {str(e)}")
    
    def upload_file(self, local_file_path, s3_key=None, make_public=False):
        try:
            if not os.path.exists(local_file_path):
                print(f"Error: File '{local_file_path}' not found.")
                return None
            
            if s3_key is None:
                s3_key = Path(local_file_path).name
            
            extra_args = {}
            if make_public:
                extra_args['ACL'] = 'public-read'
            
            print(f"Uploading '{local_file_path}' to S3 bucket '{self.bucket_name}' as '{s3_key}'...")
            
            self.s3_client.upload_file(
                local_file_path,
                self.bucket_name,
                s3_key,
                ExtraArgs=extra_args
            )
            
            if self.s3_endpoint_url:
                file_url = f"{self.s3_endpoint_url.rstrip('/')}/{self.bucket_name}/{s3_key}"
            else:
                file_url = f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"
            
            print(f"✅ File uploaded successfully!")
            print(f"📁 S3 Key: {s3_key}")
            print(f"🔗 URL: {file_url}")
            
            return file_url
            
        except FileNotFoundError:
            print(f"❌ Error: File '{local_file_path}' not found.")
        except NoCredentialsError:
            print("❌ Error: AWS credentials not found.")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchBucket':
                print(f"❌ Error: Bucket '{self.bucket_name}' does not exist.")
            elif error_code == 'AccessDenied':
                print("❌ Error: Access denied. Check your credentials and permissions.")
            else:
                print(f"❌ Error: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {str(e)}")
        
        return None
    
    def list_files(self, prefix="", max_keys=100):
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            
            if 'Contents' in response:
                print(f"📂 Files in bucket '{self.bucket_name}':")
                for obj in response['Contents']:
                    print(f"  - {obj['Key']} (Size: {obj['Size']} bytes, Modified: {obj['LastModified']})")
            else:
                print(f"📂 No files found in bucket '{self.bucket_name}' with prefix '{prefix}'")
                
        except ClientError as e:
            print(f"❌ Error listing files: {e}")
    
    def delete_file(self, s3_key):
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            print(f"✅ File '{s3_key}' deleted successfully from bucket '{self.bucket_name}'")
        except ClientError as e:
            print(f"❌ Error deleting file: {e}")

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python main.py add-server")
        print("  python main.py list-servers")
        print("  python main.py upload <file_path> [s3_key] [--public] [--server <server_id>]")
        print("  python main.py list [prefix] [--server <server_id>]")
        print("  python main.py delete <s3_key> [--server <server_id>]")
        print("\nExamples:")
        print("  python main.py add-server")
        print("  python main.py list-servers")
        print("  python main.py upload logo.png --server 1")
        print("  python main.py list --server 1")
        print("  python main.py delete images/logo.png --server 1")
        return

    db_path = "s3_servers.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS s3_servers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        aws_access_key_id TEXT,
        aws_secret_access_key TEXT,
        aws_region TEXT,
        s3_endpoint_url TEXT,
        bucket_name TEXT
    )''')
    conn.commit()

    def get_server_config(server_id=None):
        if server_id is None:
            c.execute("SELECT * FROM s3_servers")
            servers = c.fetchall()
            if not servers:
                print("No S3 servers configured. Please add one with 'add-server'.")
                sys.exit(1)
            print("Select a server:")
            for s in servers:
                print(f"  {s[0]}: {s[1]} (bucket: {s[6]})")
            try:
                server_id = int(input("Enter server id: "))
            except Exception:
                print("Invalid input.")
                sys.exit(1)
        c.execute("SELECT * FROM s3_servers WHERE id=?", (server_id,))
        row = c.fetchone()
        if not row:
            print(f"Server id {server_id} not found.")
            sys.exit(1)
        return {
            'aws_access_key_id': row[2],
            'aws_secret_access_key': row[3],
            'aws_region': row[4],
            's3_endpoint_url': row[5],
            'bucket_name': row[6]
        }

    command = sys.argv[1].lower()

    if command == "add-server":
        name = input("Server name: ")
        aws_access_key_id = input("AWS Access Key ID: ")
        aws_secret_access_key = input("AWS Secret Access Key: ")
        aws_region = input("AWS Region (default: us-east-1): ") or "us-east-1"
        s3_endpoint_url = input("S3 Endpoint URL (leave blank for AWS): ")
        bucket_name = input("Bucket Name: ")
        c.execute("INSERT INTO s3_servers (name, aws_access_key_id, aws_secret_access_key, aws_region, s3_endpoint_url, bucket_name) VALUES (?, ?, ?, ?, ?, ?)",
                  (name, aws_access_key_id, aws_secret_access_key, aws_region, s3_endpoint_url, bucket_name))
        conn.commit()
        print("✅ Server added.")
        return

    if command == "list-servers":
        c.execute("SELECT * FROM s3_servers")
        servers = c.fetchall()
        if not servers:
            print("No S3 servers configured.")
        else:
            print("Configured S3 servers:")
            for s in servers:
                print(f"  {s[0]}: {s[1]} (bucket: {s[6]})")
        return

    server_id = None
    if '--server' in sys.argv:
        idx = sys.argv.index('--server')
        if idx + 1 < len(sys.argv):
            try:
                server_id = int(sys.argv[idx + 1])
            except Exception:
                print("Invalid server id.")
                sys.exit(1)

    config = get_server_config(server_id)
    uploader = S3Uploader(config)

    try:
        if command == "upload":
            if len(sys.argv) < 3:
                print("❌ Error: Please provide a file path to upload.")
                return
            file_path = sys.argv[2]
            s3_key = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith('--') else None
            make_public = '--public' in sys.argv
            uploader.upload_file(file_path, s3_key, make_public)
        elif command == "list":
            prefix = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else ""
            uploader.list_files(prefix)
        elif command == "delete":
            if len(sys.argv) < 3:
                print("❌ Error: Please provide an S3 key to delete.")
                return
            s3_key = sys.argv[2]
            uploader.delete_file(s3_key)
        else:
            print(f"❌ Unknown command: {command}")
            print("Available commands: add-server, list-servers, upload, list, delete")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
