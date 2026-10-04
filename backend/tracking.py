"""Timestamp-based vehicle tracking with global assignment and sparse optical flow.

IDs are local to a session. Image motion is pixels/second, not road speed.
Camera compensation is reported only when background features support an affine fit.
"""
from collections import deque
import math
import cv2
import numpy as np


def overlap(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, right-left)*max(0, bottom-top)
    return intersection/max(1e-6, (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)


def assignment(cost):
    """Rectangular Hungarian assignment, with a private unmatched column per row."""
    n, real_columns = cost.shape
    if not n or not real_columns:
        return []
    values = np.concatenate((cost, np.full((n, n), 1.05)), axis=1)
    m = values.shape[1]
    u, v = np.zeros(n+1), np.zeros(m+1)
    p, way = np.zeros(m+1, int), np.zeros(m+1, int)
    for row in range(1, n+1):
        p[0] = row
        j0 = 0
        minimum, used = np.full(m+1, np.inf), np.zeros(m+1, bool)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], np.inf, 0
            for j in range(1, m+1):
                if used[j]:
                    continue
                current = values[i0-1, j-1]-u[i0]-v[j]
                if current < minimum[j]:
                    minimum[j], way[j] = current, j0
                if minimum[j] < delta:
                    delta, j1 = minimum[j], j
            for j in range(m+1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if not j0:
                break
    return [(int(p[j]-1), j-1) for j in range(1, real_columns+1)
            if p[j] and cost[p[j]-1, j-1] < 1.05]


class Tracker:
    def __init__(self, trail=40, max_age=2., compensate=True):
        self.trail, self.max_age, self.compensate = trail, max_age, compensate
        self.tracks, self.next_id = {}, 1
        self.previous_gray, self.previous_timestamp = None, None
        self.camera_motion = {"available": False, "method": "background_affine", "inliers": 0}

    def optical_motion(self, image, timestamp, hints=None):
        self.camera_motion = {"available": False, "method": "background_affine", "inliers": 0}
        if image is None:
            return {}, None, None
        h, w = image.shape[:2]
        scale = min(1., 640/max(h, w))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if scale < 1:
            gray = cv2.resize(gray, (round(w*scale), round(h*scale)))
        previous, old_time = self.previous_gray, self.previous_timestamp
        self.previous_gray, self.previous_timestamp = gray, timestamp
        if previous is None or previous.shape != gray.shape or not 0 < timestamp-old_time <= 2:
            return {}, None, old_time
        bg_mask = np.full(gray.shape, 255, np.uint8)
        points, owners = [], []
        for tid, track in list(self.tracks.items())[:40]:
            if abs(track['time']-old_time) > .001:
                continue
            x1, y1, x2, y2 = np.rint(np.asarray(track['box'])*scale).astype(int)
            x1, x2 = np.clip([x1, x2], 0, gray.shape[1])
            y1, y2 = np.clip([y1, y2], 0, gray.shape[0])
            bg_mask[max(0,y1-4):y2+4, max(0,x1-4):x2+4] = 0
            mask = np.zeros(gray.shape, np.uint8)
            rings = track.get('contours', [])
            if rings:
                for hole in (False, True):
                    for ring in rings:
                        if bool(ring.get('hole')) == hole:
                            polygon = np.rint(np.asarray(ring['points'])*scale).astype(np.int32)
                            cv2.fillPoly(mask, [polygon], 0 if hole else 255)
            else:
                mask[y1:y2, x1:x2] = 255
            features = cv2.goodFeaturesToTrack(previous, 24, .015, 4, mask=mask, blockSize=5)
            if features is not None:
                points.extend(features.reshape(-1,2)); owners.extend([tid]*len(features))
        background = cv2.goodFeaturesToTrack(previous, 240, .02, 8, mask=bg_mask, blockSize=5)
        if background is not None:
            points.extend(background.reshape(-1,2)); owners.extend([-1]*len(background))
        if not points:
            return {}, None, old_time
        start = np.asarray(points, np.float32).reshape(-1,1,2)
        # A source-time detection/prediction seeds large displacements; LK then
        # refines real image features rather than locking onto nearby background.
        hints = hints or {}
        initial = start.copy()
        for index, owner in enumerate(owners):
            if owner in hints:
                initial[index,0] += np.asarray(hints[owner],np.float32)*scale
        params = dict(winSize=(21,21), maxLevel=3,
                      criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.03))
        end, status, error = cv2.calcOpticalFlowPyrLK(previous, gray, start, initial,
                            flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **params)
        if end is None:
            return {}, None, old_time
        back, reverse, _ = cv2.calcOpticalFlowPyrLK(gray, previous, end, start.copy(),
                            flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **params)
        if back is None:
            return {}, None, old_time
        start, end, back = start.reshape(-1,2), end.reshape(-1,2), back.reshape(-1,2)
        valid = ((status.ravel()==1)&(reverse.ravel()==1)&
                 (np.linalg.norm(start-back,axis=1)<1.5)&(error.ravel()<35))
        owners = np.asarray(owners)
        affine = None
        background_ok = valid & (owners==-1)
        if self.compensate and background_ok.sum() >= 12:
            fit, inliers = cv2.estimateAffinePartial2D(start[background_ok], end[background_ok],
                       method=cv2.RANSAC, ransacReprojThreshold=2., maxIters=500, confidence=.97)
            if fit is not None and inliers is not None:
                number = int(inliers.sum())
                zoom = math.hypot(fit[0,0], fit[1,0])
                if number >= 12 and number/background_ok.sum() >= .5 and .85 < zoom < 1.15:
                    affine = fit.copy(); affine[:,2] /= scale
                    dt = timestamp-old_time
                    self.camera_motion = {"available":True,"method":"background_affine","inliers":number,
                        "x_px_s":round(float(affine[0,2]/dt),2),"y_px_s":round(float(affine[1,2]/dt),2)}
        moves = {}
        for tid in set(owners[valid]) - {-1}:
            delta = (end[valid & (owners==tid)]-start[valid & (owners==tid)])/scale
            if len(delta) < 4:
                continue
            center = np.median(delta,axis=0)
            residual = np.linalg.norm(delta-center,axis=1)
            kept = delta[residual < max(2.,float(np.median(residual))*3)]
            if len(kept) >= 4:
                move = np.median(kept,axis=0)
                hint = hints.get(int(tid))
                box = self.tracks[int(tid)]['box']
                tolerance = max(5.,math.hypot(box[2]-box[0],box[3]-box[1])*.2)
                if hint is None or np.linalg.norm(move-hint)<=tolerance:
                    moves[int(tid)] = move
        return moves, affine, old_time

    def update(self, detections, timestamp, width, height, image=None):
        self.tracks = {k:v for k,v in self.tracks.items() if 0 <= timestamp-v['time'] <= self.max_age}
        tids = list(self.tracks)
        hints = {}
        preliminary = np.full((len(detections),len(tids)),1e4)
        for j,tid in enumerate(tids):
            track = self.tracks[tid]
            dt = timestamp-track['time']
            predicted = np.asarray(track['center'])+np.asarray(track['velocity'])*dt
            box = track['box']
            gate = max(25.,min(math.hypot(width,height)*.2,math.hypot(box[2]-box[0],box[3]-box[1])*1.4+dt*80))
            for i,d in enumerate(detections):
                if track['class']!=d['class_name'] and not {track['class'],d['class_name']} <= {'car','bus','truck'}:
                    continue
                distance = float(np.linalg.norm(predicted-np.asarray(d['center'])))
                if distance<=gate:
                    preliminary[i,j] = .7*distance/gate+.3*(1-overlap(box,d['bbox']))
        for i,j in assignment(preliminary):
            hints[tids[j]] = np.asarray(detections[i]['center'])-np.asarray(self.tracks[tids[j]]['center'])
        moves, affine, old_time = self.optical_motion(image, timestamp,hints)
        cost = np.full((len(detections),len(tids)), 1e4)
        motorized = {'car','truck','bus'}
        for j, tid in enumerate(tids):
            t = self.tracks[tid]; dt = timestamp-t['time']
            center = np.asarray(t['center'])
            if tid in moves:
                delta = moves[tid]
            elif affine is not None and t['time'] == old_time:
                delta = affine[:,:2]@center+affine[:,2]-center
                delta += np.asarray(t.get('relative') or [0.,0.])*dt
            else:
                delta = np.asarray(t['velocity'])*dt
            predicted = center+delta
            box = np.asarray(t['box'])+np.tile(delta,2)
            size = math.hypot(box[2]-box[0], box[3]-box[1])
            gate = max(25., min(math.hypot(width,height)*.2, size*1.4+dt*80))
            old_area = max(1.,(box[2]-box[0])*(box[3]-box[1]))
            for i, d in enumerate(detections):
                same = t['class']==d['class_name']
                if not same and not {t['class'],d['class_name']} <= motorized:
                    continue
                distance = float(np.linalg.norm(predicted-np.asarray(d['center'])))
                iou = overlap(box, d['bbox'])
                area = (d['bbox'][2]-d['bbox'][0])*(d['bbox'][3]-d['bbox'][1])/old_area
                if (distance <= gate or iou > .12) and .15 < area < 6:
                    cost[i,j] = .55*(1-iou)+.4*min(distance/gate,1)+(.05 if not same else 0)
        matched = {i:tids[j] for i,j in assignment(cost)}
        out = []
        for i, d in enumerate(detections):
            tid = matched.get(i)
            if tid is None:
                tid, self.next_id = self.next_id, self.next_id+1
                self.tracks[tid] = dict(center=d['center'],box=d['bbox'],velocity=[0.,0.],relative=None,
                    time=timestamp,first=timestamp,**{'class':d['class_name']},votes={},hits=0,
                    history=deque(maxlen=max(1,self.trail)))
            t = self.tracks[tid]; dt = timestamp-t['time']
            source = 'model_center'
            if dt > 0:
                delta = moves.get(tid, np.asarray(d['center'])-np.asarray(t['center']))
                source = 'optical_flow' if tid in moves else 'model_center'
                alpha = 1. if t['hits']==1 else 1-math.exp(-dt/.18)
                t['velocity'] = (alpha*delta/dt+(1-alpha)*np.asarray(t['velocity'])).tolist()
                if affine is not None and t['time']==old_time:
                    center = np.asarray(t['center'])
                    global_delta = affine[:,:2]@center+affine[:,2]-center
                    relative = (delta-global_delta)/dt
                    t['relative'] = (alpha*relative+(1-alpha)*np.asarray(t['relative'] or relative)).tolist()
                else:
                    t['relative'] = None
            votes = {k:v*.85 for k,v in t['votes'].items()}
            votes[d['class_name']] = votes.get(d['class_name'],0)+d['confidence']
            t.update(center=d['center'],box=d['bbox'],time=timestamp,hits=t['hits']+1,
                     votes=votes,contours=d.get('contours',[]))
            t['class'] = max(votes,key=votes.get)
            if self.trail:
                t['history'].append([*d['center'],round(timestamp,4)])
            def vector(value):
                return {'x':round(float(value[0]),2),'y':round(float(value[1]),2),
                        'speed':round(math.hypot(*value),2)}
            velocity = vector(t['velocity'])
            relative = vector(t['relative']) if t['relative'] is not None else None
            speed = (relative or velocity)['speed']
            out.append({**d,'id':tid,'class_name':t['class'],'model_class_name':d['class_name'],
                'age_seconds':round(timestamp-t['first'],3),'hits':t['hits'],'velocity':velocity,
                'relative_velocity':relative,'motion_source':source,
                'movement':'moving' if speed>=5 else ('stationary' if t['hits']>=2 else 'unknown'),
                'direction_image_deg':round(math.degrees(math.atan2(velocity['y'],velocity['x']))%360,1)
                                      if velocity['speed']>=2 else None,
                'history':list(t['history']) if self.trail else []})
        return out


def group_status(objects, width, height, min_group=3, radius=.35):
    """Proximity plus coherent motion; prefer background-relative motion when reliable."""
    eligible = [o for o in objects if o['hits']>=3]
    adjacency = {o['id']:set() for o in eligible}
    compensated = bool(eligible) and all(o.get('relative_velocity') for o in eligible)
    for i,a in enumerate(eligible):
        for b in eligible[i+1:]:
            distance = math.hypot((a['center'][0]-b['center'][0])/width,(a['center'][1]-b['center'][1])/height)
            av, bv = (a.get('relative_velocity') or a['velocity']), (b.get('relative_velocity') or b['velocity'])
            norms = math.hypot(av['x'],av['y'])*math.hypot(bv['x'],bv['y'])
            aligned = norms>25 and (av['x']*bv['x']+av['y']*bv['y'])/norms>.7
            if distance<radius and aligned:
                adjacency[a['id']].add(b['id']);adjacency[b['id']].add(a['id'])
    best,visited=[],set()
    for tid in adjacency:
        if tid in visited:
            continue
        group,stack=[],[tid]
        while stack:
            node=stack.pop()
            if node not in visited:
                visited.add(node);group.append(node);stack.extend(adjacency[node]-visited)
        if len(group)>len(best):
            best=group
    found=len(best)>=min_group
    return {'candidate':found,'size':len(best) if found else 0,'track_ids':best if found else [],
        'method':'proximity_and_relative_motion' if compensated else 'proximity_and_image_motion',
        'status':'Candidate moving group' if found else 'No moving group candidate',
        'note':'Unverified image-space heuristic; background camera compensation applied.' if compensated
               else 'Unverified image-space heuristic; camera compensation unavailable.'}
