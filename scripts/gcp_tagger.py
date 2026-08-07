"""sceneforge GCP tagger — a small, fully-local, fully-open image tagging tool.

Load a control-points file (proj header + "E N Z name" rows) and a folder of
images; click each target in the photos that show it; export a complete ODM
gcp_list.txt. Every click is saved server-side immediately (gcp_tags.json next
to the control file), so closing the browser never loses work.

Usage:
  python scripts/gcp_tagger.py data/copr/webodm_gcp.txt data/copr/images
  -> open http://localhost:8100
"""
import argparse
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

STATE_LOCK = threading.Lock()
CFG = {}


def load_control(path: Path):
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip()]
    points = []
    for l in lines[1:]:
        p = l.split()
        points.append({"name": p[3] if len(p) > 3 else f"pt{len(points)}",
                       "e": float(p[0]), "n": float(p[1]), "z": float(p[2])})
    return lines[0], points


def load_ortho(path: Path):
    """Read a GeoTIFF orthophoto: PNG bytes + UTM bounds from the geo tags."""
    im = Image.open(path)
    sx, sy, _ = im.tag_v2[33550]           # ModelPixelScale
    _, _, _, e0, n_top, _ = im.tag_v2[33922][:6]   # ModelTiepoint
    w, h = im.size
    im.thumbnail((1600, 1600))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), [e0, n_top - h * sy, e0 + w * sx, n_top]


def load_tags():
    if CFG["tags_path"].exists():
        return json.loads(CFG["tags_path"].read_text())
    return {}


def save_tags(tags):
    CFG["tags_path"].write_text(json.dumps(tags, indent=1))


def export_text(tags):
    rows = [CFG["proj"]]
    by_name = {p["name"]: p for p in CFG["points"]}
    for name in sorted(tags):
        p = by_name.get(name)
        if not p:
            continue
        for t in tags[name]:
            rows.append(f"{p['e']:.3f} {p['n']:.3f} {p['z']:.3f} "
                        f"{t['x']:.1f} {t['y']:.1f} {t['image']} {name}")
    return "\n".join(rows) + "\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path == "/":
            self._send(PAGE, "text/html")
        elif path == "/api/meta":
            with STATE_LOCK:
                self._send(json.dumps({"proj": CFG["proj"], "points": CFG["points"],
                                       "images": CFG["images"], "tags": load_tags(),
                                       "control_file": CFG["control_name"],
                                       "map_bounds": CFG.get("map_bounds")}))
        elif path == "/ortho.png" and CFG.get("ortho_png"):
            self._send(CFG["ortho_png"], "image/png")
        elif path == "/api/export":
            with STATE_LOCK:
                text = export_text(load_tags())
                out = CFG["export_path"]
                out.write_text(text)
            self._send(json.dumps({"written": str(out), "lines": text.count("\n")}))
        elif path.startswith("/img/") or path.startswith("/thumb/"):
            name = path.split("/", 2)[2]
            f = CFG["images_dir"] / name
            if not f.is_file() or f.parent != CFG["images_dir"]:
                return self._send("not found", "text/plain", 404)
            if path.startswith("/thumb/") and HAVE_PIL:
                im = Image.open(f)
                im.thumbnail((520, 520))
                buf = io.BytesIO()
                im.convert("RGB").save(buf, "JPEG", quality=80)
                self._send(buf.getvalue(), "image/jpeg")
            else:
                self._send(f.read_bytes(), "image/jpeg")
        else:
            self._send("not found", "text/plain", 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with STATE_LOCK:
            tags = load_tags()
            if self.path == "/api/tag":
                tags.setdefault(body["name"], []).append(
                    {"image": body["image"], "x": body["x"], "y": body["y"]})
            elif self.path == "/api/untag":
                lst = tags.get(body["name"], [])
                tags[body["name"]] = [t for i, t in enumerate(lst) if i != body["index"]]
            save_tags(tags)
        self._send(json.dumps({"ok": True, "tags": tags}))


PAGE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>sceneforge · GCP tagger</title>
<style>
:root{
  --bg:#14161a; --panel:#1b1e24; --line:#2a2e36; --ink:#d7dce3; --dim:#6b7280;
  --flag:#ff6a00; --fix:#38d160; --warn:#e8b93c; --bad:#e5484d;
}
*{box-sizing:border-box; margin:0}
body{background:var(--bg); color:var(--ink); height:100vh; display:flex; flex-direction:column;
  font:13px/1.5 "Cascadia Mono","Cascadia Code",Consolas,monospace;}
header{display:flex; align-items:center; gap:16px; padding:10px 16px;
  border-bottom:1px solid var(--line); background:var(--panel);}
header h1{font-size:13px; letter-spacing:.18em; font-weight:600}
header h1 b{color:var(--flag); font-weight:600}
#proj{color:var(--dim); font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1}
button{background:none; border:1px solid var(--line); color:var(--ink); padding:6px 14px;
  font:inherit; letter-spacing:.08em; cursor:pointer}
button:hover{border-color:var(--flag); color:var(--flag)}
#exportBtn{border-color:var(--flag); color:var(--flag)}
#exportBtn:hover{background:var(--flag); color:#14161a}
main{display:flex; flex:1; min-height:0}
#rail{width:250px; border-right:1px solid var(--line); background:var(--panel);
  overflow-y:auto; padding:8px 0; flex-shrink:0}
.pt{padding:7px 14px; cursor:pointer; display:flex; align-items:center; gap:9px;
  border-left:3px solid transparent}
.pt:hover{background:#22262e}
.pt.sel{border-left-color:var(--flag); background:#22262e}
.pt .dot{width:9px; height:9px; border-radius:50%; background:var(--bad); flex-shrink:0}
.pt.n1 .dot,.pt.n2 .dot{background:var(--warn)}
.pt.ok .dot{background:var(--fix)}
.pt .nm{flex:1}
.pt .ct{color:var(--dim); font-size:11px}
.pt.sel .ct{color:var(--flag)}
#railfoot{padding:10px 14px; color:var(--dim); font-size:11px; border-top:1px solid var(--line); margin-top:8px}
#stage{flex:1; min-width:0; display:flex; flex-direction:column}
#hint{padding:6px 16px; color:var(--dim); font-size:11px; border-bottom:1px solid var(--line)}
#hint b{color:var(--flag); font-weight:600}
#grid{flex:1; overflow-y:auto; display:grid; gap:10px; padding:12px;
  grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); align-content:start}
.th{position:relative; border:1px solid var(--line); cursor:crosshair; aspect-ratio:4/3;
  background:#000; overflow:hidden}
.th:hover{border-color:var(--flag)}
.th img{width:100%; height:100%; object-fit:cover; display:block; opacity:.88}
.th .cap{position:absolute; left:0; right:0; bottom:0; padding:2px 7px; font-size:10px;
  background:rgba(20,22,26,.82)}
.th .badge{position:absolute; top:6px; right:6px; width:11px; height:11px; border-radius:50%;
  background:var(--flag); border:2px solid #14161a; display:none}
.th.tagged .badge{display:block}
#viewer{position:fixed; inset:0; background:rgba(10,11,13,.97); display:none; flex-direction:column}
#viewer.open{display:flex}
#vhead{display:flex; align-items:center; gap:14px; padding:8px 16px; border-bottom:1px solid var(--line)}
#vhead .fn{color:var(--flag)}
#vhead .sp{flex:1; color:var(--dim); font-size:11px}
#vwrap{flex:1; overflow:hidden; position:relative; cursor:crosshair}
#vpan{position:absolute; transform-origin:0 0}
#vpan img{display:block; user-select:none; -webkit-user-drag:none}
.mk{position:absolute; width:26px; height:26px; margin:-13px 0 0 -13px; pointer-events:auto; cursor:pointer}
.mk svg{width:100%; height:100%}
.mk .lbl{position:absolute; left:16px; top:-7px; font-size:10px; white-space:nowrap;
  color:var(--flag); text-shadow:0 0 4px #000}
.mk.other{opacity:.4}
.mk.other .lbl{color:var(--ink)}
#toast{position:fixed; bottom:18px; left:50%; transform:translateX(-50%); background:var(--panel);
  border:1px solid var(--fix); color:var(--fix); padding:8px 18px; display:none; font-size:12px}
#map{position:fixed; right:14px; top:56px; width:360px; background:var(--panel);
  border:1px solid var(--line); z-index:50; display:none; box-shadow:0 8px 30px rgba(0,0,0,.55)}
#map.open{display:block}
#maphead{display:flex; align-items:center; padding:6px 10px; border-bottom:1px solid var(--line);
  font-size:11px; letter-spacing:.14em; color:var(--dim)}
#maphead .sp{flex:1}
#mapbody{position:relative; cursor:default}
#mapbody img{width:100%; display:block; image-rendering:auto}
.mp{position:absolute; transform:translate(-50%,-50%); cursor:pointer; z-index:2}
.mp .d{width:10px; height:10px; border-radius:50%; border:2px solid #14161a; background:var(--bad)}
.mp.n1 .d,.mp.n2 .d{background:var(--warn)}
.mp.ok .d{background:var(--fix)}
.mp.sel .d{outline:2px solid var(--flag); outline-offset:2px}
.mp .t{position:absolute; left:12px; top:-6px; font-size:10px; color:#fff;
  text-shadow:0 0 4px #000,0 0 4px #000; white-space:nowrap}
.mp.sel .t{color:var(--flag)}
#mapnote{padding:5px 10px; font-size:10px; color:var(--dim); border-top:1px solid var(--line)}
</style></head><body>
<header>
  <h1>SCENEFORGE <b>/ GCP TAGGER</b></h1>
  <span id="proj"></span>
  <button id="mapBtn">MAP</button>
  <button id="exportBtn">EXPORT gcp_list</button>
</header>
<main>
  <div id="rail"></div>
  <div id="stage">
    <div id="hint"></div>
    <div id="grid"></div>
  </div>
</main>
<div id="viewer">
  <div id="vhead">
    <button id="backBtn">&#8592; GRID</button>
    <span class="fn" id="vname"></span>
    <span class="sp" id="vpos"></span>
    <button id="prevBtn">&#8592;</button><button id="nextBtn">&#8594;</button>
  </div>
  <div id="vwrap"><div id="vpan"><img id="vimg"></div></div>
</div>
<div id="map">
  <div id="maphead">SITE MAP · N &#8593;<span class="sp"></span><button id="mapClose">&#215;</button></div>
  <div id="mapbody"><img id="mapimg" src="/ortho.png"></div>
  <div id="mapnote">click a point to select it · colors match the target list</div>
</div>
<div id="toast"></div>
<script>
let M=null, sel=null, cur=-1, scale=1, tx=0, ty=0, drag=null, moved=false;
const $=id=>document.getElementById(id);
const count=n=>(M.tags[n]||[]).length;

async function boot(){
  M=await (await fetch('/api/meta')).json();
  $('proj').textContent=M.control_file+'  ·  '+M.proj;
  sel=M.points[0]?.name??null;
  if(!M.map_bounds)$('mapBtn').style.display='none';
  else $('map').classList.add('open');
  render();
}
function renderMap(){
  if(!M.map_bounds)return;
  document.querySelectorAll('.mp').forEach(e=>e.remove());
  const [e0,n0,e1,n1]=M.map_bounds, body=$('mapbody');
  for(const p of M.points){
    const c=count(p.name);
    const d=document.createElement('div');
    d.className='mp '+(c>=3?'ok':c>0?'n'+c:'')+(p.name===sel?' sel':'');
    d.style.left=((p.e-e0)/(e1-e0)*100)+'%';
    d.style.top=((n1-p.n)/(n1-n0)*100)+'%';
    d.innerHTML=`<div class="d"></div><span class="t">${p.name.replace('cop-','')}</span>`;
    d.onclick=()=>{sel=p.name; render();};
    body.appendChild(d);
  }
}
function render(){
  const rail=$('rail'); rail.innerHTML='';
  let done=0;
  for(const p of M.points){
    const c=count(p.name); if(c>=3)done++;
    const d=document.createElement('div');
    d.className='pt '+(c>=3?'ok':c>0?'n'+c:'')+(p.name===sel?' sel':'');
    d.innerHTML=`<span class="dot"></span><span class="nm">${p.name}</span><span class="ct">${c}&#215;</span>`;
    d.onclick=()=>{sel=p.name; render();};
    rail.appendChild(d);
  }
  const f=document.createElement('div'); f.id='railfoot';
  f.textContent=`${done}/${M.points.length} points fixed (3+ tags)`;
  rail.appendChild(f);
  $('hint').innerHTML=sel?`marking <b>${sel}</b> — open a photo showing this target, click its exact center`
                         :'select a control point on the left';
  const g=$('grid'); g.innerHTML='';
  M.images.forEach((im,i)=>{
    const tagged=sel&&(M.tags[sel]||[]).some(t=>t.image===im);
    const d=document.createElement('div');
    d.className='th'+(tagged?' tagged':'');
    d.innerHTML=`<img loading="lazy" src="/thumb/${im}"><span class="badge"></span><span class="cap">${im}</span>`;
    d.onclick=()=>openViewer(i);
    g.appendChild(d);
  });
  renderMap();
}
function openViewer(i){
  cur=i; $('viewer').classList.add('open');
  $('vname').textContent=M.images[i];
  const img=$('vimg');
  img.onload=()=>{fit(); markers();};
  img.src='/img/'+M.images[i];
}
function fit(){
  const w=$('vwrap').clientWidth, h=$('vwrap').clientHeight, img=$('vimg');
  scale=Math.min(w/img.naturalWidth, h/img.naturalHeight);
  tx=(w-img.naturalWidth*scale)/2; ty=(h-img.naturalHeight*scale)/2; apply();
}
function apply(){ $('vpan').style.transform=`translate(${tx}px,${ty}px) scale(${scale})`; }
function markers(){
  document.querySelectorAll('.mk').forEach(e=>e.remove());
  const im=M.images[cur];
  for(const p of M.points){
    (M.tags[p.name]||[]).forEach((t,idx)=>{
      if(t.image!==im)return;
      const mk=document.createElement('div');
      mk.className='mk'+(p.name===sel?'':' other');
      mk.style.left=t.x+'px'; mk.style.top=t.y+'px';
      const col=p.name===sel?'#ff6a00':'#d7dce3';
      mk.innerHTML=`<svg viewBox="0 0 26 26">
        <circle cx="13" cy="13" r="9" fill="none" stroke="${col}" stroke-width="1.6"/>
        <path d="M13 0v8M13 18v8M0 13h8M18 13h26" stroke="${col}" stroke-width="1.6"/>
      </svg><span class="lbl">${p.name}</span>`;
      mk.style.width=(26/scale)+'px'; mk.style.height=(26/scale)+'px';
      mk.style.margin=`${-13/scale}px 0 0 ${-13/scale}px`;
      mk.querySelector('.lbl').style.fontSize=(10/scale)+'px';
      mk.querySelector('.lbl').style.left=(16/scale)+'px';
      if(p.name===sel){
        mk.title='click to remove';
        mk.onclick=async ev=>{ev.stopPropagation();
          await post('/api/untag',{name:p.name,index:idx}); markers(); render();};
      }
      $('vpan').appendChild(mk);
    });
  }
}
async function post(url,body){
  const r=await (await fetch(url,{method:'POST',body:JSON.stringify(body)})).json();
  if(r.tags)M.tags=r.tags;
  return r;
}
$('vwrap').addEventListener('wheel',e=>{
  e.preventDefault();
  const f=e.deltaY<0?1.25:0.8, r=$('vwrap').getBoundingClientRect();
  const mx=e.clientX-r.left, my=e.clientY-r.top;
  tx=mx-(mx-tx)*f; ty=my-(my-ty)*f; scale*=f; apply(); markers();
},{passive:false});
$('vwrap').addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY}; moved=false;});
window.addEventListener('mousemove',e=>{
  if(!drag)return;
  const dx=e.clientX-drag.x, dy=e.clientY-drag.y;
  if(Math.abs(dx)+Math.abs(dy)>3)moved=true;
  tx+=dx; ty+=dy; drag={x:e.clientX,y:e.clientY}; apply();
});
window.addEventListener('mouseup',async e=>{
  const wasDrag=drag&&moved; drag=null;
  if(wasDrag||!$('viewer').classList.contains('open'))return;
  if(e.target.closest('.mk')||e.target.closest('#vhead'))return;
  if(!sel){toast('select a control point first','#e8b93c');return;}
  const r=$('vwrap').getBoundingClientRect();
  const x=(e.clientX-r.left-tx)/scale, y=(e.clientY-r.top-ty)/scale;
  const img=$('vimg');
  if(x<0||y<0||x>img.naturalWidth||y>img.naturalHeight)return;
  await post('/api/tag',{name:sel,image:M.images[cur],x:x,y:y});
  markers(); render();
  toast(`${sel} &#8853; ${M.images[cur]}  (${count(sel)}&#215;)`);
});
window.addEventListener('mousemove',e=>{
  if(!$('viewer').classList.contains('open'))return;
  const r=$('vwrap').getBoundingClientRect();
  const x=(e.clientX-r.left-tx)/scale, y=(e.clientY-r.top-ty)/scale;
  $('vpos').textContent=`px ${x.toFixed(0)}, ${y.toFixed(0)}   zoom ${(scale*100).toFixed(0)}%`;
});
function nav(d){ if(cur+d>=0&&cur+d<M.images.length)openViewer(cur+d); }
$('backBtn').onclick=()=>{$('viewer').classList.remove('open'); render();};
$('prevBtn').onclick=()=>nav(-1); $('nextBtn').onclick=()=>nav(1);
window.addEventListener('keydown',e=>{
  if(!$('viewer').classList.contains('open'))return;
  if(e.key==='Escape')$('backBtn').onclick();
  if(e.key==='ArrowLeft')nav(-1);
  if(e.key==='ArrowRight')nav(1);
});
$('mapBtn').onclick=()=>$('map').classList.toggle('open');
$('mapClose').onclick=()=>$('map').classList.remove('open');
$('exportBtn').onclick=async()=>{
  const r=await (await fetch('/api/export')).json();
  toast(`wrote ${r.written} (${r.lines} lines)`);
};
function toast(msg,color){
  const t=$('toast'); t.innerHTML=msg; t.style.borderColor=color||'#38d160';
  t.style.color=color||'#38d160'; t.style.display='block';
  clearTimeout(t._h); t._h=setTimeout(()=>t.style.display='none',2600);
}
boot();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("control_file", type=Path)
    ap.add_argument("images_dir", type=Path)
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--ortho", type=Path, default=None,
                    help="georeferenced orthophoto GeoTIFF to use as the map basemap")
    args = ap.parse_args()

    proj, points = load_control(args.control_file)
    if args.ortho and HAVE_PIL:
        png, bounds = load_ortho(args.ortho)
        CFG.update({"ortho_png": png, "map_bounds": bounds})
        print(f"map basemap: {args.ortho.name} bounds E {bounds[0]:.1f}-{bounds[2]:.1f} "
              f"N {bounds[1]:.1f}-{bounds[3]:.1f}")
    CFG.update({
        "proj": proj, "points": points,
        "control_name": args.control_file.name,
        "images_dir": args.images_dir.resolve(),
        "images": sorted(f.name for f in args.images_dir.iterdir()
                         if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")),
        "tags_path": args.control_file.parent / "gcp_tags.json",
        "export_path": args.control_file.parent / "gcp_list_tagged.txt",
    })
    print(f"{len(points)} control points, {len(CFG['images'])} images"
          + ("" if HAVE_PIL else " (no Pillow: serving full-size thumbnails)"))
    print(f"tags autosave to {CFG['tags_path']}")
    print(f"GCP tagger at http://localhost:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
