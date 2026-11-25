import os, sys, tempfile, io, zipfile, importlib.util, hashlib
from pathlib import Path

TMP=Path(tempfile.mkdtemp(prefix='broute17-test-'))
os.environ['APP_ENV']='development'
os.environ['DATA_DIR']=str(TMP/'data')
os.environ['DATABASE_PATH']=str(TMP/'data'/'test.sqlite3')
os.environ['APP_ORIGIN']='https://testserver'
os.environ['GOOGLE_ADMIN_EMAIL']='owner@example.com'
os.environ['GOOGLE_CLIENT_ID']='dummy-client'
os.environ['SESSION_SECRET']='x'*40
os.environ['COS_SECRET_ID']='dummy-id'; os.environ['COS_SECRET_KEY']='dummy-secret'; os.environ['COS_BUCKET']='dummybucket-123'; os.environ['COS_REGION']='ap-guangzhou'
os.environ['GTFS_STAGING_PART_SIZE_MB']='8'

ROOT=Path(__file__).resolve().parents[2]
API_PATH=ROOT/'cloud-functions'/'api'/'index.py'
spec=importlib.util.spec_from_file_location('api17test', API_PATH)
api=importlib.util.module_from_spec(spec); sys.modules[spec.name]=api; spec.loader.exec_module(api)
api.init_db()

class FakeBody:
 def __init__(self,data): self.data=data
 def get_stream_to_file(self,path): Path(path).write_bytes(self.data)
class FakeCos:
 def __init__(self): self.parts_by_upload={}; self.data=b''; self.deleted=[]; self.uploads={}
 def create_multipart_upload(self,**kwargs):
  uid='upload-'+str(len(self.uploads)+1); self.uploads[uid]=kwargs['Key']; self.parts_by_upload[uid]=[]; return {'UploadId':uid}
 def get_presigned_url(self,**kwargs): return 'https://cos.invalid/upload?part='+str(kwargs['Params']['partNumber'])
 def list_parts(self,**kwargs): return {'Part':self.parts_by_upload.get(kwargs['UploadId'],[]),'IsTruncated':'false'}
 def complete_multipart_upload(self,**kwargs): self.completed=kwargs['Key']; return {'ETag':'complete'}
 def abort_multipart_upload(self,**kwargs): self.aborted=True
 def delete_object(self,**kwargs): self.deleted.append(kwargs['Key'])
 def get_object(self,**kwargs): return {'Body':FakeBody(self.data)}
cos=FakeCos()
api.cos_client=lambda:cos

# Synthetic GTFS zip
files={
 'agency.txt':'agency_id,agency_name,agency_url,agency_timezone\na1,Test Transit,https://example.org,Asia/Seoul\n',
 'stops.txt':'stop_id,stop_name,stop_lat,stop_lon\ns1,Start,37.5,127.0\ns2,End,37.6,127.1\n',
 'routes.txt':'route_id,route_short_name,route_long_name,route_type\nr1,10,Test Bus,3\n',
 'trips.txt':'route_id,service_id,trip_id,trip_headsign\nr1,svc1,t1,End\n',
 'stop_times.txt':'trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,08:00:00,08:00:00,s1,1\nt1,08:20:00,08:20:00,s2,2\n',
 'calendar.txt':'service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nsvc1,1,1,1,1,1,0,0,20260101,20261231\n'
}
zip_buf=io.BytesIO()
with zipfile.ZipFile(zip_buf,'w',zipfile.ZIP_DEFLATED) as z:
 for n,v in files.items(): z.writestr(n,v)
blob=zip_buf.getvalue()

with api.db() as con:
 con.execute("INSERT INTO data_sources(source_id,name,provider,dataset_type,transport_modes_json,country,region,source_url,license_name,update_frequency,notes,active,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
 ('src_test','Test GTFS','Test Provider','gtfs_static','[\"bus\"]','KR','Test Region','https://example.org/feed','Open data','manual','test',1,'owner@example.com','now','now'))
 con.commit()

# Use FastAPI TestClient for owner endpoints.
from fastapi.testclient import TestClient
client=TestClient(api.app)
claims={'sub':'owner-sub','email':'owner@example.com','email_verified':True,'name':'Owner','iat':1,'exp':9999999999}
client.cookies.set(api.SESSION_COOKIE,api._session_token(claims))
headers={'Origin':'https://testserver'}
init=client.post('/admin/gtfs/staging/init',json={'source_id':'src_test','file_name':'nationwide.zip','file_size':2*1024*1024},headers=headers)
assert init.status_code==200,init.text
jid=init.json()['job_id']
sign=client.post('/admin/gtfs/staging/sign-parts',json={'job_id':jid,'part_numbers':[1]},headers=headers)
assert sign.status_code==200,sign.text
assert sign.json()['urls'][0]['url'].startswith('https://cos.invalid')
# Missing parts and wrong part size must both be rejected before queueing.
cos.parts_by_upload['upload-1']=[]
missing_first=client.post(f'/admin/gtfs/staging/{jid}/complete',headers=headers)
assert missing_first.status_code==400,missing_first.text
cos.parts_by_upload['upload-1']=[{'PartNumber':1,'ETag':'"etag-bad"','Size':1024*1024}]
wrong_size=client.post(f'/admin/gtfs/staging/{jid}/complete',headers=headers)
assert wrong_size.status_code==400,wrong_size.text
cos.parts_by_upload['upload-1']=[{'PartNumber':1,'ETag':'"etag1"','Size':2*1024*1024}]
complete=client.post(f'/admin/gtfs/staging/{jid}/complete',headers=headers)
assert complete.status_code==200,complete.text
jobs=client.get('/admin/gtfs/staging/jobs')
assert jobs.status_code==200,jobs.text
assert jobs.json()['jobs'][0]['status']=='queued'
# Non-owner users must not access the owner-only staging endpoints.
non_owner=TestClient(api.app)
non_owner_claims={'sub':'user-sub','email':'friend@example.com','email_verified':True,'name':'Friend','iat':1,'exp':9999999999}
non_owner.cookies.set(api.SESSION_COOKIE,api._session_token(non_owner_claims))
assert non_owner.get('/admin/gtfs/staging/jobs').status_code==403
assert non_owner.post('/admin/gtfs/staging/sign-parts',json={'job_id':jid,'part_numbers':[1]},headers=headers).status_code==403
# An incomplete multipart upload must not be queued.
second=client.post('/admin/gtfs/staging/init',json={'source_id':'src_test','file_name':'incomplete.zip','file_size':2*1024*1024},headers=headers)
assert second.status_code==200,second.text
second_id=second.json()['job_id']
missing=client.post(f'/admin/gtfs/staging/{second_id}/complete',headers=headers)
assert missing.status_code==400,missing.text
with api.db() as con:
 assert con.execute('SELECT status FROM gtfs_staging_uploads WHERE job_id=?',(second_id,)).fetchone()[0]=='uploading'


# Exercise stream validator + batch importer using the synthetic archive.
worker_path=ROOT/'workers'/'gtfs_import_worker.py'
specw=importlib.util.spec_from_file_location('worker17test',worker_path)
worker=importlib.util.module_from_spec(specw); sys.modules[specw.name]=worker; specw.loader.exec_module(worker)
worker.api.cos_client=lambda:cos
# ZIP path traversal is rejected before GTFS parsing.
unsafe_zip=TMP/'unsafe.zip'
with zipfile.ZipFile(unsafe_zip,'w',zipfile.ZIP_DEFLATED) as z:
 z.writestr('../escaped.txt','nope')
try:
 worker.validate_archive_streaming(unsafe_zip)
 raise AssertionError('unsafe ZIP path should be rejected')
except ValueError as exc:
 assert '안전하지 않은 파일 경로' in str(exc),str(exc)
validation=worker.validate_archive_streaming(Path(TMP/'feed.zip')) if False else None
feed_path=TMP/'feed.zip'; feed_path.write_bytes(blob)
validation=worker.validate_archive_streaming(feed_path)
assert validation['valid'] and validation['counts']['stop_times.txt']==2,validation
checksum=hashlib.sha256(blob).hexdigest()
cos.data=blob
# Set staged file size to actual synthetic ZIP and queue it.
with api.db() as con:
 con.execute('UPDATE gtfs_staging_uploads SET expected_size=?,status=?,object_key=?,feed_id=? WHERE job_id=?',(len(blob),'queued','staging/test.zip','',jid)); con.commit()
job={'job_id':jid,'source_id':'src_test','file_name':'nationwide.zip','expected_size':len(blob),'object_key':'staging/test.zip','source_version':'2026.11','effective_date':'2026-11-24','expected_sha256':'','feed_id':'feedtest001','created_by':'owner@example.com'}
result=worker.process_job(job)
assert result['counts']['stops.txt']==2,result
with api.db() as con:
 feed=con.execute('SELECT is_active,stop_count,route_count,trip_count FROM feeds WHERE feed_id=?',('feedtest001',)).fetchone()
 assert tuple(feed)==(1,2,1,1),tuple(feed)
 assert con.execute('SELECT COUNT(*) FROM stop_times WHERE feed_id=?',('feedtest001',)).fetchone()[0]==2
 assert con.execute('SELECT status FROM gtfs_staging_uploads WHERE job_id=?',(jid,)).fetchone()[0]=='completed'
 assert con.execute('SELECT COUNT(*) FROM data_releases WHERE feed_id=?',('feedtest001',)).fetchone()[0]==1
 heartbeat=con.execute('SELECT status,version FROM gtfs_worker_heartbeats ORDER BY last_seen DESC LIMIT 1').fetchone()
 assert heartbeat and heartbeat[0] in ('idle','processing'),heartbeat
 assert heartbeat[1] == api.APP_VERSION,(heartbeat[1],api.APP_VERSION)
# Health/readiness must reflect the Worker state and config status contains one staging descriptor.
health=client.get('/health').json()
assert 'gtfs_import_worker' in health['features']
status=client.get('/admin/config/status').json()
assert status['providers']['gtfs_large_file_staging']['worker_required'] is True
assert 'worker_online' in status['providers']['gtfs_large_file_staging']
print('PASS: COS multipart flow, non-owner denial, missing/wrong-size part rejection, ZIP path traversal rejection, GTFS validation/import, release activation, heartbeat/readiness')
print('tmp=',TMP)

# 1.9 streaming validator must reject malformed station hierarchies and duplicate
# transfers (large-feed path shares the same safety rules as direct imports).
def archive_with(overrides):
    buf = io.BytesIO()
    source = dict(files)
    source.update(overrides)
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in source.items():
            z.writestr(name, content)
    out = TMP / ('worker-check-' + str(len(list(TMP.glob('worker-check-*.zip')))) + '.zip')
    out.write_bytes(buf.getvalue())
    return out

bad_parent_archive = archive_with({
    'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon,parent_station,location_type\ns1,Start,37.5,127.0,s2,0\ns2,End,37.6,127.1,,0\n'
})
try:
    worker.validate_archive_streaming(bad_parent_archive)
    raise AssertionError('invalid parent_station location_type relationship should be rejected')
except ValueError as exc:
    assert 'parent_station 유형 관계' in str(exc), str(exc)

bad_location_archive = archive_with({
    'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon,location_type\ns1,Start,37.5,127.0,9\ns2,End,37.6,127.1,0\n'
})
try:
    worker.validate_archive_streaming(bad_location_archive)
    raise AssertionError('unsupported location_type should be rejected')
except ValueError as exc:
    assert 'location_type은 0~4' in str(exc), str(exc)

duplicate_transfer_archive = archive_with({
    'transfers.txt': 'from_stop_id,to_stop_id,transfer_type,min_transfer_time\ns1,s2,2,60\ns1,s2,2,90\n'
})
try:
    worker.validate_archive_streaming(duplicate_transfer_archive)
    raise AssertionError('duplicate transfer composite keys should be rejected')
except ValueError as exc:
    assert '중복 환승 규칙 키' in str(exc), str(exc)

bad_pathway_archive = archive_with({
    'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\nSTN,Station,37.5,127.0,1,\nP1,Platform,37.5,127.0,0,STN\nP2,Platform2,37.6,127.1,0,STN\n',
    'stop_times.txt': 'trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,08:00:00,08:00:00,P1,1\nt1,08:20:00,08:20:00,P2,2\n',
    'pathways.txt': 'pathway_id,from_stop_id,to_stop_id,pathway_mode,is_bidirectional\np1,STN,P1,1,1\n'
})
try:
    worker.validate_archive_streaming(bad_pathway_archive)
    raise AssertionError('pathways must not connect station location_type=1 as a node')
except ValueError as exc:
    assert 'location_type=1' in str(exc), str(exc)

bad_exit_gate_archive = archive_with({
    'pathways.txt': 'pathway_id,from_stop_id,to_stop_id,pathway_mode,is_bidirectional,traversal_time\nexit,s1,s2,7,1,30\n'
})
try:
    worker.validate_archive_streaming(bad_exit_gate_archive)
    raise AssertionError('exit gate cannot be bidirectional')
except ValueError as exc:
    assert 'exit gate' in str(exc), str(exc)

bad_transfer_scope_archive = archive_with({
    'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\nSTN,Station,37.5,127.0,1,\nENT,Entrance,37.5,127.0,2,STN\nP1,Platform,37.5,127.0,0,STN\n',
    'stop_times.txt': 'trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,08:00:00,08:00:00,P1,1\n',
    'transfers.txt': 'from_stop_id,to_stop_id,transfer_type,min_transfer_time\nENT,P1,2,60\n'
})
try:
    worker.validate_archive_streaming(bad_transfer_scope_archive)
    raise AssertionError('transfer_type 0-3 cannot reference an entrance as stop pair')
except ValueError as exc:
    assert '정류장(0) 또는 역(1)' in str(exc), str(exc)

print('PASS: streaming GTFS validator rejects invalid station hierarchies, unsupported location types, invalid transfer scopes, duplicate transfer keys, and illegal exit-gate pathways')

# Staging Worker validator and direct API validator must agree that stop_access=1
# nodes cannot participate as pathways. They are not passenger-traversable nodes.
bad_stop_access_archive = archive_with({
    'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station,stop_access\nSTN,Station,37.5,127.0,1,,0\nENT,Restricted,37.5,127.0,2,STN,1\nP1,Platform,37.5,127.0,0,STN,0\n',
    'stop_times.txt': 'trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,08:00:00,08:00:00,P1,1\n',
    'pathways.txt': 'pathway_id,from_stop_id,to_stop_id,pathway_mode,is_bidirectional,traversal_time\np1,ENT,P1,1,1,30\n'
})
try:
    worker.validate_archive_streaming(bad_stop_access_archive)
    raise AssertionError('pathways must not connect stop_access=1 nodes')
except ValueError as exc:
    assert 'stop_access=1' in str(exc), str(exc)
api_stop_access_result = api.validate_gtfs_bytes(bad_stop_access_archive.read_bytes())
assert not api_stop_access_result['valid'], api_stop_access_result
assert any('pathways.txt' in error and '노드유형' in error for error in api_stop_access_result['errors']), api_stop_access_result

print('PASS: staging/API GTFS validation parity for stop_access restrictions')
