/* Slow-CPU regression: native frame cadence must survive delayed real inference. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'..'),temporary=fs.mkdtempSync(path.join(os.tmpdir(),'vision-smooth-'));
const python=process.env.PYTHON_EXECUTABLE||path.join(ROOT,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));let server,browser,logs='';
(async()=>{
  const clip=path.join(temporary,'long-video.avi');
  const generated=spawnSync(python,['-c',`import cv2,sys\ncap=cv2.VideoCapture(sys.argv[1]);frames=[]\nwhile True:\n ok,frame=cap.read()\n if not ok:break\n frames.append(frame)\ncap.release();h,w=frames[0].shape[:2]\nwriter=cv2.VideoWriter(sys.argv[2],cv2.VideoWriter_fourcc(*'MJPG'),15,(w,h))\nfor _ in range(4):\n for frame in frames:writer.write(frame)\nwriter.release()`,path.join(ROOT,'samples/vehicle-validation.mp4'),clip]);
  assert.equal(generated.status,0,generated.stderr?.toString());
  server=spawn(python,['-m','uvicorn','tests.slow_app:app','--host','127.0.0.1','--port','8133','--workers','1'],{cwd:ROOT,env:{...process.env,ADMIN_PASSWORD:'Slow-CPU-test-2026',DATA_DIR:path.join(temporary,'data'),PUBLIC_ORIGIN:'http://127.0.0.1:8133'},stdio:['ignore','pipe','pipe']});
  server.stdout.on('data',data=>logs+=data);server.stderr.on('data',data=>logs+=data);
  let ready=false;for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:8133/api/health')).ok){ready=true;break}}catch{}await delay(100)}assert(ready,logs);
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}),args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];let jpegRequests=0;
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/api\/jobs\/.*\/frames\/.*\.jpg/.test(r.url()))jpegRequests++});
  await page.goto('http://127.0.0.1:8133');await page.fill('#password','Slow-CPU-test-2026');await page.click('#login-form button[type=submit]');await page.waitForSelector('#workspace:not([hidden])');
  await page.setInputFiles('#video-upload',clip);await page.waitForFunction(()=>document.querySelector('#media-select').value);
  await page.click('#run-analysis');await page.waitForFunction(()=>document.querySelector('#playback-video').currentTime>.2);
  // Collect actual decoded video presentation times while each real inference takes >450 ms.
  const observations=await page.evaluate(()=>new Promise(resolve=>{
    const video=document.querySelector('#playback-video'),times=[],start=performance.now(),initial=video.currentTime;
    function sample(_now,metadata){times.push(metadata.mediaTime);if(performance.now()-start>3500){const q=video.getVideoPlaybackQuality();resolve({elapsed:(performance.now()-start)/1000,advanced:video.currentTime-initial,times,total:q.totalVideoFrames,dropped:q.droppedVideoFrames})}else video.requestVideoFrameCallback(sample)}
    video.requestVideoFrameCallback(sample);
  }));
  assert(observations.advanced>3.2,'Playback stalled under slow inference');
  assert(observations.times.length>=40,'Not enough displayed frames for 15 FPS source');
  const gaps=observations.times.slice(1).map((t,i)=>t-observations.times[i]);assert(Math.max(...gaps)<.25,'A visible playback gap exceeded 250 ms');
  assert.equal(jpegRequests,0,'Dashboard sought JPEGs during native playback');
  await page.waitForFunction(()=>document.querySelector('#run-status').textContent==='COMPLETED',null,{timeout:30000});
  const analysis=await page.evaluate(async()=>{
    const jobs=await(await fetch('/api/jobs')).json();return(await fetch(`/api/jobs/${jobs[0].id}/export/json`)).json();
  });
  assert(analysis.frames.length>=10&&analysis.frames.length<60,'Adaptive sampling did not respond to slow processing');
  assert(analysis.frames.every(f=>f.inference_ms>=440),'Slow inference fixture was inactive');
  assert(analysis.frames.some(f=>f.objects.some(o=>o.class_name==='bus'&&o.mask_area_px>0)),'Real neural segmentation did not run');
  assert(analysis.frames.some(f=>f.sampling_fps<3),'Sampling was not adapted to CPU load');
  assert(analysis.frames.some(f=>f.objects.some(o=>o.hits>=2&&o.velocity.speed>2)),'Moving image tracks were not measured');
  assert.deepEqual(errors,[]);
  const report={test:'slow_real_inference_native_playback',...observations,max_frame_gap_seconds:Math.max(...gaps),analyzed_frames:analysis.frames.length,mean_inference_ms:analysis.frames.reduce((s,f)=>s+f.inference_ms,0)/analysis.frames.length,jpeg_requests:jpegRequests};
  delete report.times;
  const output=process.env.PERFORMANCE_REPORT||path.join(temporary,'performance.json');fs.writeFileSync(output,JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
})().catch(error=>{console.error(error);console.error(logs.slice(-5000));process.exitCode=1}).finally(async()=>{if(browser)await browser.close();if(server)server.kill('SIGTERM');setTimeout(()=>fs.rmSync(temporary,{recursive:true,force:true}),1500)});
