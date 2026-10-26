import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(process.env.FOLLOWDESK_BROWSER_PACKAGE||'D:/codex/rx-market-pulse/dashboard/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({headless:true});
const p=await browser.newPage({viewport:{width:1440,height:960}});
try{
  await p.goto('file:///'+path.resolve('artifacts/FollowDesk-Demo.webm').replaceAll('\\','/'));
  const result=await p.locator('video').evaluate(async v=>{
    v.pause();
    if(v.readyState<1)await new Promise(resolve=>v.addEventListener('loadedmetadata',resolve,{once:true}));
    return {duration:v.duration,width:v.videoWidth,height:v.videoHeight,readyState:v.readyState};
  });
  assert.ok(result.duration>=60&&result.duration<=90,'Encoded recording duration');
  assert.equal(result.width,1440);assert.equal(result.height,960);
  for(const [name,at] of [['review',25],['receipt',35],['crm-history',58]]){
    await p.locator('video').evaluate(async(v,at)=>{v.currentTime=at;await new Promise(resolve=>v.addEventListener('seeked',resolve,{once:true}));},at);
    await p.screenshot({path:`artifacts/video-${name}.png`});
  }
  result.verifiedAt=new Date().toISOString();result.playable=true;
  await fs.writeFile('artifacts/video-verification.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close();}
