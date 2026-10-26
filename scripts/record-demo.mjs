import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(process.env.FOLLOWDESK_BROWSER_PACKAGE||'D:/codex/rx-market-pulse/dashboard/package.json');
const {chromium}=require('playwright');
const follow=process.env.FOLLOWDESK_URL||'http://127.0.0.1:5059';
const loop=process.env.LOOPDESK_URL||'http://127.0.0.1:5055';
await fs.mkdir('artifacts/recording-raw',{recursive:true});
const browser=await chromium.launch({headless:true});
// Prepare fictional CRM data and consume the pairing code before recording.
// Cookies and codes stay in memory and are never written to artifacts.
const setup=await browser.newContext();const prep=await setup.newPage();
await prep.goto(loop);await prep.getByRole('button',{name:'Try demo'}).click();
await prep.goto(loop+'/scope-import');
await prep.getByLabel('Reviewed ScopeDesk JSON').setInputFiles(path.resolve('artifacts/worked-scope-reviewed.json'));
await prep.getByRole('button',{name:'Preview scope import'}).click();
await prep.getByLabel('Organisation',{exact:true}).selectOption({label:'Cedar Circuit'});
await prep.getByLabel('Contact',{exact:true}).selectOption({label:'Alex Example 01 · Cedar Circuit'});
await prep.getByRole('button',{name:'Confirm reviewed scope import'}).click();
const opportunity=prep.url(),oid=opportunity.split('/').at(-1);
await prep.goto(loop+'/integrations/followdesk');await prep.getByRole('button',{name:'Create pairing code'}).click();
let code=await prep.locator('#pair-code').inputValue();
await prep.goto(follow);await prep.getByRole('button',{name:'Open a private demo'}).click();
await prep.goto(follow+'/connection');await prep.getByLabel('One-use pairing code').fill(code);
await prep.getByRole('button',{name:'Connect workspace',exact:true}).click();code=undefined;
assert.ok((await prep.locator('main').innerText()).includes('Connected to this LoopDesk demo'));
const state=await setup.storageState();await setup.close();
const context=await browser.newContext({storageState:state,viewport:{width:1440,height:960},recordVideo:{dir:'artifacts/recording-raw',size:{width:1440,height:960}}});
const p=await context.newPage(),chapters=[],started=Date.now();
async function chapter(title,body,seconds){
  chapters.push({seconds:Number(((Date.now()-started)/1000).toFixed(2)),title,body});
  await p.evaluate(({title,body})=>{
    document.querySelector('#demo-caption')?.remove();
    const box=document.createElement('div');box.id='demo-caption';
    if(!document.title.includes('FollowDesk'))box.style.cssText='position:fixed;bottom:18px;left:40px;right:40px;background:#163e31;color:#fff;padding:17px 24px;border:1px solid #9abbac;border-radius:8px;z-index:1000;font:15px/1.5 Segoe UI,sans-serif;pointer-events:none';
    const h=document.createElement('strong');h.textContent=title;
    const b=document.createElement('div');b.textContent=body;
    box.append(h,b);document.body.append(box);
  },{title,body});
  await p.waitForTimeout(seconds*1000);
}
try{
  await p.goto(follow+'/queue');
  await chapter('FollowDesk / Reviewed sales outreach','Independent software prototype: existing CRM enquiry → reviewed message → simulated inbox → recorded outcome. Fictional data throughout.',7);
  await p.goto(follow+'/enroll');await p.getByLabel('LoopDesk opportunity').selectOption(oid);
  await p.getByLabel('Published plan version').selectOption({label:'Reviewed scope next discussion · v1'});
  await chapter('01 / Start with the existing enquiry','Live, limited LoopDesk access reads the current contact and scope last received by the CRM. Enrolment does not send anything.',7);
  await p.getByRole('button',{name:'Create run & inspect draft'}).click();
  await p.getByLabel('Subject',{exact:true}).fill('Discussion of your reviewed ITAD scope');
  await p.getByLabel('Message · plain text, maximum 4 KiB').fill('Hello Alex,\n\nCould we arrange a discussion of the reviewed laptop scope and confirm access windows at Dubai and Sharjah? Any remaining assumptions still need confirmation.\n\nThis message is part of a fictional demonstration.');
  await p.getByRole('button',{name:'Save draft & clear approval'}).click();
  await chapter('02 / Edit the message with its context visible','The plan version is pinned. Original CRM next action and received-scope identity remain visible. Internal review does not mean customer acceptance.',8);
  await p.getByRole('link',{name:'Review saved draft',exact:true}).click();
  await chapter('03 / Confirm the exact saved snapshot','Recipient, content, schedule and live CRM context are checked. A changed draft or recipient invalidates the review; unsaved text cannot silently replace it.',8);
  await p.getByRole('button',{name:'Confirm exact saved message'}).click();
  await p.getByRole('button',{name:'Deliver to demo inbox'}).click();
  await chapter('04 / One safe, immutable delivery receipt','Delivery writes a receipt, advances the step and queues CRM history together. This built-in inbox is simulated: no real email is sent.',8);
  await p.getByRole('button',{name:'Record synthetic reply & stop future steps'}).click();
  await p.locator('.steps').scrollIntoViewIfNeeded();
  await chapter('05 / A reply stops future work','The synthetic reply cancels pending steps while preserving the delivered message. Opt-outs also suppress matching contacts and destinations.',8);
  await p.goto(follow+'/reports');
  await chapter('06 / Outcomes stay separate from CRM delivery','Counts come from immutable events. Two history events await acknowledgement; retrying CRM synchronisation never repeats the message.',6);
  await p.getByRole('button',{name:'Retry pending CRM history'}).click();
  await p.getByRole('button',{name:'Retry pending CRM history'}).click();
  await p.goto(opportunity);await p.getByText(/FollowDesk · demo_delivery/).first().scrollIntoViewIfNeeded();
  assert.equal(((await p.locator('main').innerText()).match(/FollowDesk · /g)||[]).length,2);
  await chapter('07 / Real CRM history, repeat-safe updates','LoopDesk receives exactly one delivery and one reply event. Its stage, owner, value, next action and tasks are preserved.',8);
  await p.goto(follow+'/reports');
  await chapter('Local demonstration / verified boundaries','Real local apps and SQLite data; explicitly simulated message transport. PostgreSQL, production vault dependencies and hosted HTTPS still require verification.',7);
}finally{
  const video=p.video();await context.close();await video.saveAs(path.resolve('artifacts/FollowDesk-Demo.webm'));
  const result={recordedAt:new Date().toISOString(),captureWallSeconds:Number(((Date.now()-started)/1000).toFixed(2)),captions:'Presentation captions over actual local application responses. Pairing credentials excluded; fictional data and simulated inbox.',chapters};
  await fs.writeFile('artifacts/demo-chapters.json',JSON.stringify(result,null,2));await browser.close();console.log(JSON.stringify(result,null,2));
}
