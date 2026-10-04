"""Regression checks for timestamped motion and independent browser playback."""
import json
import struct
import time
import cv2
import numpy as np
import pytest
from backend.db import Database
from backend.tracking import Tracker, assignment
from tests.test_pipeline import upload, complete


def detection(x, y=100, label='car', width=80, height=60):
    return {'class_name':label,'confidence':.9,'bbox':[x,y,x+width,y+height],
            'center':[x+width/2,y+height/2],'contours':[]}


def test_assignment_uses_global_minimum():
    assert sorted(assignment(np.array([[.10,.20],[.11,.90]])))==[(0,1),(1,0)]
    assert assignment(np.array([[100.]]))==[]


def test_tracks_survive_crossing_and_class_flicker():
    tracker=Tracker()
    first=tracker.update([detection(60),detection(220)],0,640,360)
    second=tracker.update([detection(180),detection(100)],.2,640,360)
    assert [o['id'] for o in second]==[first[1]['id'],first[0]['id']]
    third=tracker.update([detection(140,label='truck'),detection(140)],.4,640,360)
    assert sorted(o['id'] for o in third)==sorted(o['id'] for o in first)
    fourth=tracker.update([detection(180),detection(100)],.6,640,360)
    assert [o['id'] for o in fourth]==[first[0]['id'],first[1]['id']]


def test_optical_flow_measures_vehicle_motion_and_camera_pan():
    cv2.setNumThreads(1)
    rng=np.random.default_rng(14)
    background=cv2.GaussianBlur(rng.integers(0,255,(360,640,3),dtype=np.uint8),(3,3),0)
    patch=rng.integers(0,255,(60,80,3),dtype=np.uint8)
    stationary=rng.integers(0,255,(60,80,3),dtype=np.uint8)
    def scene(camera,x):
        image=cv2.warpAffine(background,np.float32([[1,0,camera],[0,1,0]]),(640,360))
        image[100:160,x:x+80]=patch
        image[240:300,400+camera:480+camera]=stationary
        return image
    tracker=Tracker()
    first=tracker.update([detection(100),detection(400,240)],0,640,360,scene(0,100))
    second=tracker.update([detection(134),detection(406,240)],.2,640,360,scene(6,134))
    assert [o['id'] for o in first]==[o['id'] for o in second]
    assert tracker.camera_motion['available']
    assert second[0]['motion_source']=='optical_flow'
    assert second[0]['velocity']['x']==pytest.approx(170,abs=5)
    assert second[0]['relative_velocity']['x']==pytest.approx(140,abs=5)
    assert second[0]['movement']=='moving'
    assert second[1]['velocity']['x']==pytest.approx(30,abs=3)
    assert second[1]['relative_velocity']['speed']<3
    assert second[1]['movement']=='stationary'


def test_browser_conversion_byte_ranges_and_timeline(admin,clip):
    media=upload(admin,clip);mid=media['id']
    assert admin.get(f'/api/media/{mid}/video').status_code==409
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=admin.get(f'/api/media/{mid}/playback').json()
        if state['status'] in ('ready','failed'):
            break
        time.sleep(.05)
    assert state['status']=='ready',state
    response=admin.get(state['url'],headers={'Range':'bytes=0-99'})
    assert response.status_code==206
    assert len(response.content)==100 and b'ftyp' in response.content
    assert response.headers['content-range'].startswith('bytes 0-99/')
    job=admin.post('/api/jobs',json={'media_id':mid,'adaptive_sampling':False}).json()
    complete(admin,job['id'])
    timeline=admin.get(f"/api/jobs/{job['id']}/timeline?at=0&ahead=8").json()['frames']
    assert len(timeline)==5 and timeline[0]['timestamp']==0
    assert timeline[-1]['timestamp']==pytest.approx(.8,abs=.02)
    assert admin.get(f"/api/jobs/{job['id']}/timeline?ahead=1000").status_code==422
    assert admin.get(f"/api/jobs/{job['id']}/timeline?at=nan").status_code==422
    assert admin.delete(f"/api/jobs/{job['id']}").status_code==200
    assert admin.delete(f'/api/media/{mid}').status_code==200
    assert not (admin.app.state.config.data_dir/'playback'/f'{mid}.mp4').exists()


def test_live_capture_timestamp_is_preserved(admin):
    jid=admin.post('/api/jobs',json={'source':'camera'}).json()['id']
    image=np.full((240,320,3),30,np.uint8)
    encoded=cv2.imencode('.jpg',image)[1].tobytes()
    time.sleep(.21)
    with admin.websocket_connect('/ws/live/'+jid) as ws:
        ws.send_json({'csrf':admin.headers['X-CSRF-Token']});assert ws.receive_json()['ready']
        ws.send_bytes(b'MTV1'+struct.pack('<d',.125)+encoded)
        frame=ws.receive_json()['frame']
        assert frame['timestamp']==.125
        assert admin.post('/api/jobs/'+jid+'/control',json={'action':'stop'}).status_code==200


def test_old_settings_get_new_defaults(tmp_path):
    db=Database(tmp_path/'old.sqlite3')
    db.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps({'confidence':.4,'analysis_fps':3}),))
    assert db.settings()['confidence']==.4
    assert db.settings()['analysis_fps']==3
    assert db.settings()['adaptive_sampling'] is True
    assert db.settings()['analysis_size']==960


def test_latest_snapshot_does_not_wait_for_inference_lock(admin):
    manager=admin.app.state.manager
    jid=admin.post('/api/jobs',json={'source':'camera'}).json()['id']
    runtime=manager.runtimes[jid]
    manager.process(runtime,np.full((240,320,3),30,np.uint8),0,0)
    with runtime.lock:
        started=time.monotonic()
        data=manager.frame(jid,0,'overlay')
        assert data and time.monotonic()-started<1
    admin.post('/api/jobs/'+jid+'/control',json={'action':'stop'})


def test_real_model_tracks_independently_moving_bus(admin):
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    media=upload(admin,root/'samples/vehicle-motion-demo.mp4')
    job=admin.post('/api/jobs',json={'media_id':media['id'],'analysis_fps':5,
                                  'adaptive_sampling':False}).json()
    complete(admin,job['id'])
    frames=admin.get('/api/jobs/'+job['id']+'/export/json').json()['frames']
    assert len(frames)==40
    buses=[next((o for o in f['objects'] if o['class_name']=='bus'),None) for f in frames]
    assert sum(o is not None for o in buses)>=36
    observed=[o for o in buses[3:] if o is not None]
    assert len({o['id'] for o in observed})==1
    assert np.median([o['velocity']['x'] for o in observed])==pytest.approx(95*.75,abs=6)
    assert sum(o['movement']=='moving' for o in observed)>=len(observed)*.9
    assert all(o['mask_area_px']>1000 and o['contours'] for o in observed)
