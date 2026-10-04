import {colors} from './charts.js';

// Model observations remain unchanged in storage. Only the display is interpolated.
export function frameAt(frames, time, maxExtrapolation=.35) {
  if (!frames.length) return null;
  let previous=null, next=null;
  for (const frame of frames) {
    if (frame.timestamp<=time+.001) previous=frame;
    else { next=frame; break; }
  }
  if (!previous) return null;
  const elapsed=Math.max(0,time-previous.timestamp);
  if (!next && elapsed>maxExtrapolation) return null;
  const fraction=next ? Math.min(1,elapsed/(next.timestamp-previous.timestamp)) : 0;
  const future=new Map((next?.objects||[]).map(o=>[o.id,o]));
  const objects=previous.objects.map(object=>{
    const following=future.get(object.id), old=object.bbox;
    let box;
    if (following) box=old.map((v,i)=>v+(following.bbox[i]-v)*fraction);
    else if (!next) {
      const dx=(object.velocity?.x||0)*elapsed,dy=(object.velocity?.y||0)*elapsed;
      box=[old[0]+dx,old[1]+dy,old[2]+dx,old[3]+dy];
    } else box=old;
    const sx=(box[2]-box[0])/Math.max(1,old[2]-old[0]);
    const sy=(box[3]-box[1])/Math.max(1,old[3]-old[1]);
    const transform=([x,y])=>[box[0]+(x-old[0])*sx,box[1]+(y-old[1])*sy];
    const center=[(box[0]+box[2])/2,(box[1]+box[3])/2];
    const history=(object.history||[]).filter(p=>p[2]<=time).map(p=>p.slice());
    if (history.length) history.push([...center,time]);
    return {...object,bbox:box,center,history,
      contours:(object.contours||[]).map(r=>({...r,points:r.points.map(transform)}))};
  });
  return {...previous,objects,display_timestamp:time,
    display_method:elapsed<.001?'observation':next?'interpolated':'brief_prediction'};
}

function paint(ctx, frame, view, options) {
  if (!frame) return;
  const {opacity=.48,labels=true,selected=null}=options;
  ctx.lineWidth=2;
  ctx.font='13px system-ui';
  for (const object of frame.objects) {
    const color=colors[object.class_name]||'#a0a8b0';
    ctx.strokeStyle=color;ctx.fillStyle=color;
    if (view==='overlay'||view==='mask') {
      ctx.beginPath();
      for (const ring of object.contours||[]) {
        ring.points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();
      }
      ctx.globalAlpha=view==='mask'?.85:opacity;ctx.fill('evenodd');ctx.globalAlpha=1;
    }
    if (view==='mask') continue;
    const [x1,y1,x2,y2]=object.bbox;
    ctx.lineWidth=selected===object.id?4:2;ctx.strokeRect(x1,y1,x2-x1,y2-y1);
    if (view==='trail'||view==='overlay') {
      ctx.beginPath();(object.history||[]).forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();
      // Direction arrow uses source-time image velocity, with a bounded display length.
      const v=object.velocity||{x:0,y:0,speed:0},[cx,cy]=object.center;
      if (v.speed>=5) {
        const length=Math.min(55,Math.max(12,v.speed*.4)),angle=Math.atan2(v.y,v.x);
        const ex=cx+length*Math.cos(angle),ey=cy+length*Math.sin(angle);
        ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(ex,ey);
        ctx.moveTo(ex-7*Math.cos(angle-.5),ey-7*Math.sin(angle-.5));ctx.lineTo(ex,ey);
        ctx.lineTo(ex-7*Math.cos(angle+.5),ey-7*Math.sin(angle+.5));ctx.stroke();
      }
    }
    if (labels) {
      const text=`${object.class_name} #${object.id} ${object.confidence.toFixed(2)}`;
      const y=Math.max(17,y1);ctx.fillRect(x1,y-17,ctx.measureText(text).width+8,17);
      ctx.fillStyle='#fff';ctx.fillText(text,x1+4,y-4);ctx.fillStyle=color;
    }
  }
}

export class SmoothPlayer {
  constructor({video,overlay,mask,trail,fetchJSON,onFrame,onClock,onStatus,onError,options}) {
    Object.assign(this,{video,overlay,mask,trail,fetchJSON,onFrame,onClock,onStatus,onError,options});
    this.frames=new Map();this.generation=0;this.pending=false;this.lastFetch=0;this.lastHUD=0;
    this.mode=null;this.callback=null;this.destroyed=false;
    video.addEventListener('seeked',()=>{this.lastFetch=0;this.prefetch(true);this.draw(video.currentTime)});
    video.addEventListener('loadeddata',()=>{this.draw(video.currentTime);this.prefetch(true)});
    video.addEventListener('pause',()=>{this.draw(this.clock());this.onClock?.(this.clock(),false)});
    video.addEventListener('play',()=>this.onClock?.(this.clock(),true));
    video.addEventListener('ended',()=>this.onClock?.(this.clock(),false));
    video.addEventListener('error',()=>{if(this.mode==='file')this.onError?.('Video could not be decoded. Re-upload an H.264 MP4.')});
    this.loop();
  }
  reset() {
    this.generation++;this.controller?.abort();this.pending=false;
    if('cancelVideoFrameCallback' in this.video)this.video.cancelVideoFrameCallback(this.callback);
    else cancelAnimationFrame(this.callback);
    this.frames.clear();this.job=null;this.mode=null;this.lastHUD=0;this.lastFetch=0;
    this.video.pause();this.video.srcObject=null;this.video.removeAttribute('src');this.video.load();
    this.video.hidden=true;for(const canvas of [this.overlay,this.mask,this.trail]){canvas.hidden=true;canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height)}
    this.loop();
  }
  async openFile(job,url,autoplay=false) {
    this.reset();this.job=job;this.mode='file';this.video.hidden=false;
    this.video.src=url;this.video.playbackRate=1;this.video.load();
    await this.prefetch(true);
    if (autoplay) await this.video.play().catch(()=>this.onStatus?.('Press play to start the video'));
  }
  async openCamera(job,stream) {
    this.reset();this.job=job;this.mode='camera';this.start=performance.now();
    this.video.hidden=false;this.video.srcObject=stream;await this.video.play();
  }
  updateJob(job) { if(this.job?.id===job.id)this.job=job; }
  add(frame) {
    if(!frame)return;this.frames.set(frame.seq,frame);
    if(this.frames.size>500) {
      const time=this.clock();const sorted=[...this.frames.values()].sort((a,b)=>Math.abs(a.timestamp-time)-Math.abs(b.timestamp-time));
      this.frames=new Map(sorted.slice(0,400).map(f=>[f.seq,f]));
    }
  }
  clock() { return this.mode==='camera'?(performance.now()-this.start)/1000:this.video.currentTime; }
  async prefetch(force=false) {
    if(this.mode!=='file'||!this.job||this.pending)return;
    const now=performance.now(),time=this.video.currentTime;
    const sorted=[...this.frames.values()].sort((a,b)=>a.timestamp-b.timestamp);
    const first=sorted[0],last=sorted.at(-1);
    if(!force) {
      if(now-this.lastFetch<600)return;
      const covered=first&&first.timestamp<=time+.01&&last.timestamp>=time+3;
      const complete=this.job.status==='completed'&&last?.seq>=this.job.analyzed_frames-1&&first?.timestamp<=time;
      if(covered||complete)return;
    }
    this.pending=true;this.lastFetch=now;
    const generation=this.generation,jid=this.job.id;
    const controller=new AbortController();this.controller=controller;
    try {
      const data=await this.fetchJSON(`/api/jobs/${jid}/timeline?at=${time.toFixed(3)}&ahead=8&limit=240`,{signal:controller.signal});
      if(generation===this.generation)for(const frame of data.frames)this.add(frame);
    } catch(error) {if(generation===this.generation)this.onError?.(error.message)}
    finally {if(generation===this.generation)this.pending=false;}
    if(generation===this.generation&&this.video.paused)this.draw(this.clock());
  }
  loop() {
    const tick=(_now,metadata)=>{
      if(this.destroyed)return;
      const time=this.mode==='camera'?this.clock():(metadata?.mediaTime??this.video.currentTime);
      this.draw(time);this.prefetch();
      this.schedule(tick);
    };
    this.schedule(tick);
  }
  schedule(tick) {
    if('requestVideoFrameCallback' in this.video)this.callback=this.video.requestVideoFrameCallback(tick);
    else this.callback=requestAnimationFrame(tick);
  }
  draw(time=this.clock()) {
    if(!this.mode||this.video.readyState<2)return;
    if(this.video.closest('[hidden]'))return;
    const frames=[...this.frames.values()].sort((a,b)=>a.timestamp-b.timestamp);
    const frame=frameAt(frames,time,this.mode==='camera'?.55:.4);
    const reference=frame||frames[0];
    const width=reference?.width||Math.min(960,this.video.videoWidth),height=reference?.height||Math.round(width*this.video.videoHeight/this.video.videoWidth);
    if(!width||!height)return;
    const opts=this.options?.()||{},view=opts.view||'overlay';
    for(const [canvas,kind]of [[this.overlay,view],[this.mask,'mask'],[this.trail,'trail']]) {
      if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height}
      const ctx=canvas.getContext('2d');ctx.clearRect(0,0,width,height);canvas.hidden=false;
      if(canvas!==this.overlay){ctx.drawImage(this.video,0,0,width,height);if(kind==='mask'){ctx.fillStyle='#020914';ctx.globalAlpha=.88;ctx.fillRect(0,0,width,height);ctx.globalAlpha=1}}
      if(kind!=='original')paint(ctx,frame,kind,opts);
    }
    if(performance.now()-this.lastHUD>=120||this.video.paused) {
      this.lastHUD=performance.now();this.onFrame?.(frame,time);
      this.onClock?.(time,!this.video.paused&&!this.video.ended);
      this.onStatus?.(frame ? `${frame.inference_ms.toFixed(0)} ms · ${(frame.sampling_fps||this.job.config.analysis_fps).toFixed(1)} analysis FPS · ${frame.display_method.replaceAll('_',' ')}`
                           : 'Video playing · waiting for time-aligned analysis');
    }
  }
  seek(time) {if(this.mode==='file'){this.video.currentTime=Math.max(0,Math.min(time,this.video.duration||this.job.duration));this.prefetch(true)}}
  pause() {this.video.pause()}
  async toggle() {
    if(this.mode!=='file')return;
    if(this.video.paused){if(this.video.ended)this.video.currentTime=0;await this.video.play()}
    else this.video.pause();
  }
  snapshot() {
    const canvas=document.createElement('canvas');canvas.width=this.overlay.width;canvas.height=this.overlay.height;
    const ctx=canvas.getContext('2d');ctx.drawImage(this.video,0,0,canvas.width,canvas.height);ctx.drawImage(this.overlay,0,0);
    return new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.92));
  }
}
