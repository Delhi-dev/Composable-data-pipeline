import {api} from "./api.js";
import {match, bindLinks} from "./router.js";
import {renderShell, bindGlobalLookup} from "./shell.js";
import {permissionError} from "./ui.js";
import * as home from "./pages/home.js";
import * as lifecycle from "./pages/lifecycle.js";
import * as workspace from "./pages/workspace.js";
import * as runs from "./pages/runs.js";
import * as cases from "./pages/cases.js";
import * as reports from "./pages/reports.js";
import * as oversight from "./pages/oversight.js";
import * as settings from "./pages/settings.js";
import * as reference from "./pages/reference.js";

const pages={home,lifecycle,workspace,runs,cases,reports,oversight,settings,reference};
const state={me:null,health:null,broad:false,caseBroad:false,impersonationUsers:[]};

async function start(){
  const view=document.querySelector('#view');
  try{
    [state.me,state.health]=await Promise.all([api('/api/v1/me'),api('/api/v1/health')]);
    state.broad=state.me.roles.some(role=>['auditor','platform_admin'].includes(role));
    state.caseBroad=state.broad||state.me.roles.includes('case_manager');
    if(state.health.ui_impersonation) state.impersonationUsers=await api('/api/v1/impersonation-users').catch(()=>[]);
    bindGlobalLookup(); window.addEventListener('popstate',render); await render();
  }catch(error){view.innerHTML=permissionError(error,'start the application');}
}

async function render(){
  const route=match(),view=document.querySelector('#view');
  renderShell(state,route.name==='workspace'?'lifecycle':route.name);
  if(!pages[route.name]){view.innerHTML='<div class="page-error"><h1>Page not found</h1><p><a href="/" data-route>Return home</a></p></div>';bindLinks(view);return}
  view.innerHTML='<div class="loading-state"><span class="spinner"></span> Loading…</div>';
  await pages[route.name].render(view,state,route.parts);
  document.querySelector('#route-status').textContent=`${document.querySelector('#view h1')?.textContent||'Page'} loaded`;
  view.focus({preventScroll:true});
}

start();
