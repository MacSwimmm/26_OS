// Start an isolated local API for the browser suite and always close it afterward.
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import net from 'node:net';
const reservation=net.createServer();
reservation.listen(0,'127.0.0.1');
await once(reservation,'listening');
const port=reservation.address().port;
await new Promise(resolve=>reservation.close(resolve));
const server=spawn(process.env.PYTHON_BIN||'python3',['dashboard_server.py','--port',String(port)],{stdio:['ignore','ignore','pipe']});
let output='';
server.stderr.on('data',chunk=>output+=chunk);
const closed=once(server,'close');
try {
  const base=`http://127.0.0.1:${port}`;
  let ready=false;
  for(let attempt=0;attempt<100;attempt++){
    if(server.exitCode!==null)throw new Error(`API exited: ${output}`);
    try {ready=(await fetch(`${base}/api/health`)).ok;}catch{}
    if(ready)break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!ready)throw new Error(`API did not become ready: ${output}`);
  process.env.DASHBOARD_URL=base;
  await import('../tests/dashboard_browser.mjs');
} finally {
  if(server.exitCode===null)server.kill('SIGTERM');
  await closed;
}
