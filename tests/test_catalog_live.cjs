/* Offline unit harness: no browser, server or network is controlled here. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(){ this.listeners={};this.children=[];this.attrs={}; }
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this.attrs[name]=value;}
  removeAttribute(name){delete this.attrs[name];}
  replaceChildren(...children){this.children=children;}
  append(...children){this.children.push(...children);}
  get lastElementChild(){return this.children.at(-1);}
}
async function main(){
  const form=new Element(),search=new Element(),rows=new Element(),nav=new Element(),status=new Element(),count=new Element(),area=new Element();
  const buttons=[],requests=[],timers=new Map();let clock=0;
  search.value='';form.action='http://example.test/documents/';form.fields={q:search};
  form.querySelector=selector=>form.fields[selector.match(/name=([^\]]+)/)[1]];
  nav.querySelector=()=>null;rows.closest=()=>area;rows.children=[{text:'initial'}];
  const elements={'document-filters':form,'document-rows':rows,'document-pagination':nav,'table-load-status':status,'document-count':count};
  const location={href:'http://example.test/documents/'};
  const fetch=(url,options)=>new Promise(resolve=>requests.push({url:new URL(url),options,resolve}));
  const window={fetch,AbortController,scrollTo(){}};
  const sandbox={window,document:{getElementById:id=>elements[id],querySelectorAll:()=>[],createElement:()=>{const b=new Element();buttons.push(b);return b;}},location,history:{replaceState(_a,_b,url){location.href=String(url);}},URL,URLSearchParams,AbortController,
    FormData:class{constructor(form){this.entries=Object.entries(form.fields).map(([key,field])=>[key,field.value]);}[Symbol.iterator](){return this.entries[Symbol.iterator]();}},
    DOMParser:class{parseFromString(text){return {querySelector:()=>({children:[{text}]})};}},fetch,
    setTimeout(fn,delay){assert.equal(delay,300);timers.set(++clock,fn);return clock;},clearTimeout(id){timers.delete(id);}};
  vm.runInNewContext(fs.readFileSync('dms/static/dms/catalog.js','utf8'),sandbox);
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  async function type(text){search.value=text;search.listeners.input({isComposing:false});for(const fn of [...timers.values()])fn();timers.clear();await flush();}
  async function answer(request,html,next=null,total=1){request.resolve({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>({html,next_url:next,total_count:total})});await flush();}
  await type('a');await type('ab');assert.equal(requests.length,0);
  // Live search must initialize even when the initial page has no next-page link.
  search.value='abc';search.listeners.input({});search.value='abcd';search.listeners.input({});
  assert.equal(timers.size,1);for(const fn of timers.values())fn();timers.clear();await flush();
  assert.equal(requests.length,1);assert.equal(requests[0].url.searchParams.get('q'),'abcd');
  await type('new');assert.equal(requests[0].options.signal.aborted,true);
  await answer(requests[1],'LATEST','/documents/?q=new&page=2',31);
  await answer(requests[0],'STALE');assert.ok(rows.children[0].text.includes('LATEST'));assert.ok(!rows.children[0].text.includes('STALE'));
  buttons[0].listeners.click();await flush();assert.equal(requests[2].url.searchParams.get('q'),'new');assert.equal(requests[2].url.searchParams.get('page'),'2');
  await answer(requests[2],'SECOND',null,31);assert.equal(rows.children.length,2);assert.equal(buttons[0].hidden,true);
  await type('');assert.equal(requests[3].url.searchParams.get('q'),'');await answer(requests[3],'ALL');assert.equal(rows.children.length,1);assert.equal(count.textContent,1);
  console.log('Passed: 3-character threshold, debounce, stale-response cancellation, lazy append and empty-search reset.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
