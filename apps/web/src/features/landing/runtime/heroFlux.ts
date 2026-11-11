import { q, sizeCanvas } from "./dom";
import type { Scope } from "@/shared/lib/scope";

// Ruled lines displaced by simplex noise. The pointer bends them like a lens (uMouse), a click
// leaves a swirl that decays (uSw: x, y, start time, direction), and uIntro reveals the lines from
// the top on load.
const FRAGMENT_SHADER = `#extension GL_OES_standard_derivatives : enable
precision highp float;
uniform vec2 uRes; uniform float uT; uniform vec3 uMouse; uniform vec4 uSw[4]; uniform float uIntro;
vec3 m289(vec3 x){return x-floor(x*(1./289.))*289.;} vec4 m289(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 perm(vec4 x){return m289(((x*34.)+1.)*x);} vec4 tis(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){const vec2 C=vec2(1./6.,1./3.);const vec4 D=vec4(0.,.5,1.,2.);
vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.-g;
vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+C.yyy;vec3 x3=x0-D.yyy;
i=m289(i);vec4 p=perm(perm(perm(i.z+vec4(0.,i1.z,i2.z,1.))+i.y+vec4(0.,i1.y,i2.y,1.))+i.x+vec4(0.,i1.x,i2.x,1.));
float n_=.142857142857;vec3 ns=n_*D.wyz-D.xzx;vec4 j=p-49.*floor(p*ns.z*ns.z);vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.*x_);
vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.-abs(x)-abs(y);vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
vec4 s0=floor(b0)*2.+1.;vec4 s1=floor(b1)*2.+1.;vec4 sh=-step(h,vec4(0.));vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
vec4 nm=tis(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));p0*=nm.x;p1*=nm.y;p2*=nm.z;p3*=nm.w;
vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.);m=m*m;
return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));}
void main(){
 vec2 fc=gl_FragCoord.xy; vec2 p=(fc-.5*uRes)/uRes.y; float t=uT;
 for(int i=0;i<4;i++){ vec2 c=(uSw[i].xy-.5*uRes)/uRes.y; float age=t-uSw[i].z;
  if(age>0. && age<7.){ vec2 d=p-c; float r2=dot(d,d); float ease=1.-exp(-age*3.);
   float s=uSw[i].w*ease*exp(-age*.55)*exp(-r2/.05)*4.2; float cs=cos(s),sn=sin(s); p=c+mat2(cs,-sn,sn,cs)*d; } }
 vec2 q=p*1.6;
 float n=snoise(vec3(q*.5,t*.11))*.68+snoise(vec3(q*1.25+7.,t*.17))*.24+snoise(vec3(q*2.6-3.,t*.23))*.08;
 vec2 mpos=(uMouse.xy-.5*uRes)/uRes.y; vec2 dm=p-mpos; float lens=exp(-dot(dm,dm)/(.35*.35*.42))*uMouse.z;
 float v=(q.y+t*.175)*6.2+n*2.3+lens*1.35;
 float fw=max(fwidth(v),1e-4); float d=abs(fract(v)-.5);
 float core=clamp(1.-(d-fw*.1)/(fw*1.05),0.,1.);
 float glow=exp(-d/(fw*5.5))*.24+exp(-d/(fw*16.))*.07;
 float sh=.62+.38*snoise(vec3(q.x*1.1-t*.55,floor(v)*.31,t*.15));
 float rim=.2*smoothstep(.0,.35,abs(n));
 float inten=(core*(.62+.38*sh)+glow*(1.+rim)*sh*2.)*(.9+lens*.55);
 float yTop=1.-fc.y/uRes.y; float rev=smoothstep(0.,.18,uIntro*1.25-yTop);
 vec2 uv=fc/uRes; float vig=smoothstep(0.,.12,uv.x)*smoothstep(1.,.88,uv.x)*smoothstep(0.,.1,uv.y)*smoothstep(1.,.9,uv.y);
 vig=.5+.5*vig;
 gl_FragColor=vec4(vec3(.043)+vec3(.96)*inten*rev*vig,1.);
}`;
const VERTEX_SHADER = "attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}";

type Swirl = { x: number; y: number; t: number; dir: number };
type Program = {
  gl: WebGLRenderingContext;
  res: WebGLUniformLocation | null;
  time: WebGLUniformLocation | null;
  mouse: WebGLUniformLocation | null;
  swirls: WebGLUniformLocation | null;
  intro: WebGLUniformLocation | null;
};

function compile(canvas: HTMLCanvasElement): Program | null {
  const gl = canvas.getContext("webgl", { antialias: false, alpha: false });
  if (!gl || !gl.getExtension("OES_standard_derivatives")) return null;
  const shader = (type: number, source: string) => {
    const s = gl.createShader(type);
    if (!s) return null;
    gl.shaderSource(s, source);
    gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
  };
  const vertex = shader(gl.VERTEX_SHADER, VERTEX_SHADER);
  const fragment = shader(gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
  const program = gl.createProgram();
  if (!vertex || !fragment || !program) return null;
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  gl.useProgram(program);
  // One triangle that covers the whole canvas.
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, "a");
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  return {
    gl,
    res: gl.getUniformLocation(program, "uRes"),
    time: gl.getUniformLocation(program, "uT"),
    mouse: gl.getUniformLocation(program, "uMouse"),
    swirls: gl.getUniformLocation(program, "uSw"),
    intro: gl.getUniformLocation(program, "uIntro"),
  };
}

/**
 * Whether this browser can run the shader, tried on a throwaway canvas. The hero's own canvas must
 * stay untouched until this is known: a canvas that has given out a WebGL context can never give
 * a 2D one, which the still fallback needs.
 */
function canRunShader(): boolean {
  const probe = compile(document.createElement("canvas"));
  probe?.gl.getExtension("WEBGL_lose_context")?.loseContext();
  return probe !== null;
}

/** Where the shader cannot run: the same ruled lines, drawn once and still. */
function drawStill(canvas: HTMLCanvasElement): void {
  const { ctx, w, h } = sizeCanvas(canvas);
  ctx.fillStyle = "#0b0b0b";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(243,243,241,0.7)";
  ctx.lineWidth = 1;
  for (let y = 40; y < h; y += 28) {
    ctx.beginPath();
    for (let x = 0; x <= w; x += 8) {
      const wave = y + Math.sin(x / 90 + y / 60) * 6;
      if (x) ctx.lineTo(x, wave);
      else ctx.moveTo(x, wave);
    }
    ctx.stroke();
  }
}

/** The hero: white ruled lines flowing down a black page, bent by the pointer and swirled by a click. */
export function mountHeroFlux(root: HTMLElement, scope: Scope, reduced: boolean): void {
  const canvas = q<HTMLCanvasElement>(root, "#hero-canvas");
  const stage = canvas.parentElement ?? canvas;
  const program = canRunShader() ? compile(canvas) : null;
  if (!program) {
    // No context has been taken from the canvas unless the shader ran on the probe, so 2D is free.
    if (canvas.getContext("2d")) {
      drawStill(canvas);
      scope.onResize(() => drawStill(canvas));
    }
    return;
  }
  const { gl } = program;
  const swirls: Swirl[] = [];
  const started = performance.now();
  const pointer = { x: 0, y: 0, targetX: 0, targetY: 0, strength: 0, target: 0 };
  let dpr = 1;
  let visible = true;
  let frame = 0;

  const size = () => {
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.max(1, Math.round(canvas.clientWidth * dpr));
    canvas.height = Math.max(1, Math.round(canvas.clientHeight * dpr));
    gl.viewport(0, 0, canvas.width, canvas.height);
  };
  const render = (now: number) => {
    const t = (now - started) / 1000;
    pointer.x += (pointer.targetX - pointer.x) * 0.12;
    pointer.y += (pointer.targetY - pointer.y) * 0.12;
    pointer.strength += (pointer.target - pointer.strength) * 0.06;
    const intro = reduced ? 1 : 1 - Math.pow(1 - Math.min(1, t / 1.8), 3);
    const packed = new Float32Array(16);
    swirls.forEach((swirl, i) => packed.set([swirl.x, swirl.y, swirl.t, swirl.dir], i * 4));
    gl.uniform2f(program.res, canvas.width, canvas.height);
    gl.uniform1f(program.time, reduced ? 4 : t);
    gl.uniform3f(program.mouse, pointer.x, pointer.y, pointer.strength);
    gl.uniform4fv(program.swirls, packed);
    gl.uniform1f(program.intro, intro);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
  const loop = () => {
    if (frame) return;
    const tick = (now: number) => {
      render(now);
      frame = visible && !reduced ? scope.frame(tick) : 0;
    };
    frame = scope.frame(tick);
  };
  // Shader coordinates: device pixels from the canvas's bottom-left corner.
  const position = (event: MouseEvent) => {
    const box = canvas.getBoundingClientRect();
    return { x: (event.clientX - box.left) * dpr, y: (box.bottom - event.clientY) * dpr };
  };

  scope.on<PointerEvent>(stage, "pointermove", (event) => {
    const at = position(event);
    pointer.targetX = at.x;
    pointer.targetY = at.y;
    if (!pointer.target) {
      pointer.x = at.x;
      pointer.y = at.y;
    }
    pointer.target = 1;
    if (reduced) render(performance.now());
  });
  scope.on(stage, "pointerleave", () => {
    pointer.target = 0;
  });
  scope.on<MouseEvent>(stage, "click", (event) => {
    if ((event.target as Element).closest("a, button")) return;
    const at = position(event);
    const dir = swirls.length % 2 ? -1 : 1;
    swirls.push({ ...at, t: (performance.now() - started) / 1000, dir });
    if (swirls.length > 4) swirls.shift();
  });
  scope.onResize(() => {
    size();
    // Resizing clears the canvas, and under reduced motion no loop is running to redraw it.
    if (reduced) render(performance.now());
  });
  size();
  scope.whenVisible(canvas, (nowVisible) => {
    visible = nowVisible;
    if (!nowVisible) return;
    if (reduced) render(performance.now());
    else loop();
  });
}
