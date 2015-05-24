#!/usr/bin/env python2

import pprint
from oauth2client import client
import httplib2
from apiclient.discovery import build
from apiclient.http import MediaFileUpload
from apiclient import errors
from apiclient import http
import webbrowser
from oauth2client.file import Storage
import re, json, os, sys



import yaml
import datetime

_SAFE_FILENAME_RE = re.compile(r'[^a-zA-Z.]+')

def safe_file_name(file_name):
	return _SAFE_FILENAME_RE.sub('_', file_name)

def get_credentials(email):
	flow = client.flow_from_clientsecrets(
		'client_secrets.json',
		scope= ('https://www.googleapis.com/auth/drive.appfolder',
			    'https://www.googleapis.com/auth/drive.file'),
#		scope='https://www.googleapis.com/auth/drive',
		redirect_uri='urn:ietf:wg:oauth:2.0:oob')
	auth_uri = flow.step1_get_authorize_url()
	webbrowser.open(auth_uri)
	auth_code = raw_input("Enter your authorization code:")
	credentials = flow.step2_exchange(auth_code)
	return credentials

def get_storage(email):
	file_name = safe_file_name(email) + '.cred'
	storage = Storage(file_name)
	return storage

def load_credentials(email):
	storage = get_storage(email)
	credentials = storage.get()
	return credentials

def save_credentials(email, credentials):
	storage = get_storage(email)
	storage.put(credentials)

def load_settings():
	file_path = 'settings.yaml'
	settings = None
	if os.path.exists(file_path):
		with open(file_path) as f:
			settings = yaml.load(f)
	return settings

def init_settings():
	settings = load_settings()
	if settings is None:
		main_account = raw_input("Enter your main google account email\n this account will be used to store your settings\n you may add more accounts later\n main account email:")
		settings = {
			'main_account': main_account,
			'accounts': {
				main_account: {
					'root_folder_id': None,
				},
			},
		}
	return settings

def get_drive_service(credentials):
	http_auth = credentials.authorize(httplib2.Http())
	drive_service = build('drive', 'v2', http=http_auth)
	return drive_service

def settings_to_yaml(settings):
	doc = yaml.dump(settings, default_flow_style=False)
	return doc

def uplaod_settings(settings, drive_service):
	body = {
		'title': 'settings.yaml',
		'parents': [{'id': 'appfolder'}],
	}
	file_path = 'settings.yaml'
	media_body = MediaFileUpload(file_path, mimetype='text/yaml', resumable=True)
	file_obj = drive_service.files().insert(body=body, media_body=media_body).execute()
# 	pprint.pprint(file_obj)

def find_files(service, query):
	files = service.files().list(q=query).execute()
	return files

def download_settings(drive_service):
	files = find_files(drive_service, "title = 'settings.yaml' and 'appfolder' in parents")
	if not files['items']:
		return None
	file_id = files['items'][0]['id']
	file_content = drive_service.files().get_media(fileId=file_id).execute()
	settings = yaml.load(file_content)
	return settings

class DriveService(object):
	def __init__(self, drive_service):
		self.service = drive_service

# 	def upload_file_by_content(self, file_desc, file_content):
# 		media_body = MediaFileUpload(local_file_path, resumable=True)
# 		return self.service.files().insert(body=file_desc, media_body=media_body).execute()

	def upload_file_by_path(self, file_desc, file_path):
		media_body = MediaFileUpload(file_path, resumable=True)
		file_desc = self.service.files().insert(body=file_desc, media_body=media_body).execute()
		return file_desc

	def about(self):
		return self.service.about().get().execute()

	def get_file_by_id(self, file_id):
		return self.service.files().get(fileId=file_id).execute()

	def get_child_by_name(self, parent_id, file_name):
		query = "'%s' in parents and title = '%s'" % (parent_id, file_name)
		query_result = find_files(self.service, query)
		items = query_result['items']
		return items[0] if items else None

	def create_dir(self, parent_id, dir_name):
		file_desc = {
			'title': dir_name,
			"mimeType": "application/vnd.google-apps.folder"
		}
		return self.service.files().insert(body=file_desc).execute()

	def download_file(self, file_desc, local_file_path, callback=None, context=None):
		request = self.service.files().get_media(fileId=file_desc['id'])
		with open(local_file_path, 'wb') as f:
			media_request = http.MediaIoBaseDownload(f, request)
			while True:
				try:
					download_progress, done = media_request.next_chunk()
				except errors.HttpError, error:
					print >> sys.stderr, 'An error occurred: %s' % error
					return False
				if download_progress and callback is not None:
					callback(download_progress.progress(), context)
				if done:
					if callback is not None:
						callback(1.0, context)
					break
		return True

	def update_mtime(self, file_desc, mtime):
		mtime_str = mtime.isoformat("T") + "Z"
		print 'mtime_str=', mtime_str
		exit(0)
		new_file_desc = {
			'modifiedDate': mtime_str,
			'setModifiedDate': True,
		}
		updated_file = self.service.files().patch(
			fileId=file_desc['id'],
			body=new_file_desc,
			fields='modifiedDate').execute()
		print 'modifiedDate=', updated_file['modifiedDate']
		return updated_file
		

class FileNotFoundEx(Exception):
	pass

class Account(object):
	def __init__(self, email):
		self.email = email
		credentials = self.get_credentials()
		self.service = DriveService(get_drive_service(credentials))
		self.data = {}

	def get_credentials(self):
		credentials = load_credentials(self.email)
		if credentials is None:
			credentials = get_credentials(self.email)
			save_credentials(self.email, credentials)
		return credentials

	def get_root_folder_id(self):
		root_folder_id = self.data.get('root_folder_id', None)
		if root_folder_id is None:
			about = self.service.about()
			root_folder_id = about['rootFolderId']
			self.data['root_folder_id'] = root_folder_id
		return root_folder_id

	def upload_file(self, local_file_path, remote_dir_path):
		remote_dir = self.get_remote_dir(remote_dir_path, create=True)
		basename = os.path.basename(local_file_path)
		body = {
			'title': basename,
			'parents': [{'id': remote_dir['id']}],
		}
		file_desc = self.service.upload_file_by_path(body, local_file_path)
		self._update_mtime(local_file_path, file_desc)
		return file_desc

	def get_remote_file(self, remote_file_path, create_dir=False):
		parent_id = self.get_root_folder_id()
		for file_name in remote_file_path.split('/'):
			file_desc = self.service.get_child_by_name(parent_id, file_name)
			if file_name is None and create_dir:
				file_desc = self.service.create_dir(parent_id, file_name)
			parent_id = file_desc['id']
		return file_desc

	def download_file(self, remote_file_path, local_file_path):
		remote_dir_path, basename = os.path.split(remote_file_path)
		remote_dir = self.get_remote_dir(remote_dir_path)
		if not remote_dir:
			raise FileNotFoundEx()
		file_desc = self.service.get_child_by_name(remote_dir['id'], basename)
# 		pprint.pprint(file_desc)
		def callback(progress, context):
			print 'Download Progress: %d%%' % int(progress * 100)
		if self.service.download_file(file_desc, local_file_path, callback):
			file_desc = self.service.get_file_by_id(file_desc['id'])
			self._update_mtime(local_file_path, file_desc)

	def _update_mtime(self, local_file_path, remote_file_desc):
		local_mtime = stat_timestamp_to_datetime(os.stat(local_file_path).st_mtime)
		remote_mtime = rfc3339_to_datetime(remote_file_desc['modifiedDate'])
		diff = _compare_datetime(local_mtime, remote_mtime)
		if diff > 0:
			self._update_local_mtime(local_file_path, remote_mtime)
		elif diff < 0:
			self._update_remote_mtime(remote_file_desc, local_mtime)

	def _update_local_mtime(self, local_file_path, mtime):
		mtime = datetime_to_timestamp(mtime)
		atime = mtime
		os.utime(local_file_path, (atime, mtime))

	def _update_remote_mtime(self, file_desc, mtime):
		updated_file = self.service.update_mtime(file_desc, mtime)
		return updated_file

	def get_remote_dir(self, remote_dir_path, create=False):
		return self.get_remote_file(remote_dir_path, create_dir=create)

	def compare_file(self, local_file_path, remote_file_path):
		remote_file_desc = self.get_remote_file(remote_file_path)
		local_file_stat = os.stat(local_file_path)
		local_mtime = stat_timestamp_to_datetime(local_file_stat.st_mtime)
		remote_mtime = rfc3339_to_datetime(remote_file_desc['modifiedDate'])
		print 'remote_mtime=', remote_mtime
		print ' local_mtime=', local_mtime
		return _compare_datetime(local_mtime, remote_mtime)

def _compare_datetime(datetime_1, datetime_2):
	time_delta = (datetime_1 - datetime_2).total_seconds()
	if abs(time_delta) < 1:
		time_delta = 0
	elif time_delta > 0:
		time_delta = 1
	else:
		time_delta = -1
	return time_delta

def stat_timestamp_to_datetime(st_mtime):
	datetime_ = datetime.datetime.utcfromtimestamp(st_mtime)
	return datetime_

def rfc3339_to_datetime(time_str):
	datetime_ = datetime.datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%S.%fZ')
	return datetime_

def datetime_to_timestamp(datetime_):
	td = datetime_ - datetime.datetime.utcfromtimestamp(0)
	return td.total_seconds()


def main():
	settings = init_settings()
# 	pprint.pprint(settings)
# 	exit(0)
	email = settings['main_account']
	account = Account(email)
	
# 	downloaded_settings = download_settings(drive_service)
# 	print 'settings=', settings, 'downloaded_settings=', downloaded_settings
# 	uplaod_settings(settings, drive_service)

	account.upload_file(r'C:\Users\legion\Desktop\tmp\cover.jpg', 'Music')
# 	account.download_file('Music/cover.jpg', r'C:\Users\legion\Desktop\tmp\cover_2.jpg')
	print account.compare_file(r'C:\Users\legion\Desktop\tmp\cover_2.jpg', 'Music/cover.jpg')
	exit(0)
# 	for sync_desc in settings.get('syncs', []):
# 		local_path = sync_desc['local_path']
# 		remote_path = sync_desc['remote_path']


	files = drive_service.files().list().execute()
	print 'nextLink=', files['nextLink'], 'nextPageToken=', files['nextPageToken']
	for f in files['items']:
# 		print json.dumps(f, indent=4)
		print 'title=', f['title'].encode('utf8')
		if 'md5Checksum' in f:
			print '\t\tmd5Checksum=', f['md5Checksum']

if __name__ == "__main__":
	main()
