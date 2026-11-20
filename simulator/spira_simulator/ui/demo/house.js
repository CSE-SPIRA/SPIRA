import * as THREE from "./three.module.min.js";
import { HOUSE_DEVICES } from "./chain.js";

export const TV_SCENES = { kids_party: "어린이 파티", party: "파티", calm: "차분한 분위기", cinema: "영화" };

export function hsvColor({ hue, saturation, brightness } = {}) {
  if (![hue, saturation, brightness].every(Number.isFinite)) return null;
  const value = brightness / 100;
  const chroma = value * saturation / 100;
  const segment = ((hue % 360 + 360) % 360) / 60;
  const offset = chroma * (1 - Math.abs(segment % 2 - 1));
  const colors = [[chroma, offset, 0], [offset, chroma, 0], [0, chroma, offset],
    [0, offset, chroma], [offset, 0, chroma], [chroma, 0, offset]];
  return "#" + colors[Math.floor(segment)]
    .map((channel) => Math.round((channel + value - chroma) * 255).toString(16).padStart(2, "0"))
    .join("");
}

function traceLabel(chain, device) {
  const task = chain.tasks.find(({ id }) => id === device.traces[0]);
  if (!task?.line) return "";
  const intent = chain.intents.find(({ id }) => id === task.intentId);
  const taskText = `${task.line} ${task.need}`;
  const slots = (intent?.slotIds ?? []).flatMap((id) => {
    const slot = chain.slots.find((entry) => entry.id === id);
    if (!slot?.value) return [];
    const item = slot.basis.find((id) => chain.items.some((entry) => entry.id === id));
    const words = new Set(`${slot.label} ${slot.value}`.match(/[\p{L}\p{N}]+/gu));
    const matches = [...words].filter((word) => word.length > 1 && taskText.includes(word)).length;
    return [{ slot, item, matches }];
  });
  // The task links to an intent. Prefer item-backed slots that share its wording.
  const [link] = slots.sort((a, b) => Number(Boolean(b.item)) - Number(Boolean(a.item)) || b.matches - a.matches);
  return [task.line, link && `${link.slot.label}: ${link.slot.value}`, link?.item].filter(Boolean).join(" ← ");
}

export function houseDevicePresentation(chain) {
  return new Map(chain.devices.map((device) => [device.logicalId, {
    resting: chain.hasHubPlan && !device.chosen,
    evidence: chain.hasHubPlan && device.chosen ? traceLabel(chain, device) : "",
  }]));
}

export function layoutHouseLabels(markers, viewWidth, viewHeight) {
  const gap = 8;
  const boxes = markers.map(({ x, y, width, height, ...marker }) => {
    const left = Math.max(gap, Math.min(x - width / 2, viewWidth - width - gap));
    return { ...marker, x, y, left, right: left + width, height };
  }).sort((a, b) => a.y - b.y);
  const shareColumn = (a, b) => a.left < b.right + gap && a.right + gap > b.left;

  // Reserve space for lower labels before placing each label near its anchor.
  for (let index = boxes.length - 1; index >= 0; index--) {
    const box = boxes[index];
    const lower = boxes.slice(index + 1).filter((other) => shareColumn(box, other));
    box.latestTop = Math.min(viewHeight - 44, ...lower.map((other) => other.latestTop - gap)) - box.height;
  }
  for (const [index, box] of boxes.entries()) {
    const upper = boxes.slice(0, index).filter((other) => shareColumn(box, other));
    const earliestTop = Math.max(46, ...upper.map((other) => other.top + other.height + gap));
    box.top = Math.max(earliestTop, Math.min(box.y - box.height - 12, box.latestTop));
  }
  return boxes;
}

// The fixed I1 cutaway. View direction and entrance cues are separate from device values.
export function createHouse(stage, overlay, view) {
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true});
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.16;
  stage.append(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera();
  const floorGlow = new THREE.Color();
  const reflectedWhite = new THREE.Color("#fff4ea");
  const restingGlow = new THREE.Color("#e6e2df");
  const mainLight = new THREE.DirectionalLight("#fff0d8", 2.4);
  mainLight.position.set(-5,12,7); mainLight.castShadow = true;
  Object.assign(mainLight.shadow.camera,{left:-11,right:11,top:9,bottom:-9,near:.5,far:35});
  mainLight.shadow.mapSize.set(2048,2048);
  mainLight.shadow.normalBias = .03;
  scene.add(mainLight, new THREE.HemisphereLight("#fff5e7","#ac8877",1.65));
  const fill = new THREE.DirectionalLight("#eee6ff", .75);
  fill.position.set(5,5,-7); scene.add(fill);

  const material = (color, props={}) => new THREE.MeshStandardMaterial({color,roughness:.78,...props});
  const oak=material("#b98f65"), wood=material("#936d51"), stone=material("#efe4ca"), wall=material("#e9dfca");
  const sage=material("#777d68"), cream=material("#e5c8a5"), dark=material("#403936"), glass=material("#292334",{roughness:.29});
  const brass=material("#ad7544",{metalness:.5,roughness:.31}), linen=material("#b18b72"), ivory=material("#eee0c5");
  const steel=material("#c4a99f",{metalness:.31}), tile=material("#c4b49e");
  const foliage=["#65744e","#88946a","#a3a67a"].map(color=>material(color));
  const roundGeometry = new Map();
  function roundedGeometry(w,h,d,r) {
    const key = [w,h,d,r].join(",");
    if (roundGeometry.has(key)) return roundGeometry.get(key);
    const bevel = Math.min(r,w*.22,h*.22,d*.22);
    const x=w/2-bevel,y=h/2-bevel;
    const shape = new THREE.Shape();
    shape.moveTo(-x,-y); shape.lineTo(x,-y); shape.lineTo(x,y); shape.lineTo(-x,y); shape.closePath();
    const geo = new THREE.ExtrudeGeometry(shape,{depth:d-2*bevel,bevelEnabled:true,bevelSize:bevel,bevelThickness:bevel,bevelSegments:3,steps:1});
    geo.translate(0,0,-d/2+bevel);
    roundGeometry.set(key,geo);
    return geo;
  }
  function mesh(geometry, surface, x,y,z,parent=scene) {
    const object = new THREE.Mesh(geometry,surface);
    object.position.set(x,y,z); object.castShadow=true;object.receiveShadow=true;parent.add(object);return object;
  }
  function box(w,h,d,s,x,y,z,r=.035,parent=scene) {
    return mesh(roundedGeometry(w,h,d,r),s,x,y,z,parent);
  }
  function disk(r,h,s,x,y,z,parent=scene,bottom=r) {
    return mesh(new THREE.CylinderGeometry(r,bottom,h,48),s,x,y,z,parent);
  }
  function sphere(w,h,d,s,x,y,z,parent=scene) {
    const object=mesh(new THREE.SphereGeometry(1,24,14),s,x,y,z,parent);
    object.scale.set(w,h,d);return object;
  }
  function tube(points,r,s,parent=scene) {
    const path=new THREE.CatmullRomCurve3(points.map(point=>new THREE.Vector3(...point)));
    return mesh(new THREE.TubeGeometry(path,24,r,8,false),s,0,0,0,parent);
  }
  function plane(w,h,s,x,y,z,parent=scene) {
    const object=mesh(new THREE.PlaneGeometry(w,h),s,x,y,z,parent);
    object.castShadow=false;return object;
  }
  function group(x,y,z) {
    const object=new THREE.Group();object.position.set(x,y,z);scene.add(object);return object;
  }
  function canvasTexture(width,height,draw) {
    const canvas=document.createElement("canvas");canvas.width=width;canvas.height=height;
    const ctx=canvas.getContext("2d");const texture=new THREE.CanvasTexture(canvas);
    texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=renderer.capabilities.getMaxAnisotropy();
    return {texture, paint(painter=draw){painter(ctx,width,height);texture.needsUpdate=true}};
  }
  function textile(base, thread) {
    const surface=canvasTexture(512,256,(ctx,w,h)=>{
      ctx.fillStyle=base;ctx.fillRect(0,0,w,h);
      for(let i=0;i<3000;i++){
        ctx.globalAlpha=.13 + (i%6)*.045;ctx.fillStyle=thread;
        ctx.fillRect((i*239)%w,(i*137)%h,1+(i%6),1);
      }
      ctx.globalAlpha=1;
    });
    surface.paint();
    return material("#ffffff",{map:surface.texture,bumpMap:surface.texture,bumpScale:.025});
  }

  const backing = new THREE.Mesh(new THREE.PlaneGeometry(120,120),new THREE.ShadowMaterial({opacity:.16}));
  backing.rotation.x=-Math.PI/2;backing.position.y=-.48;backing.receiveShadow=true;scene.add(backing);
  box(13.6,.42,7.95,material("#d6b498"),0,-.22,0,.12);
  box(13.35,.12,7.73,stone,0,-.026,0,.08);
  const planks=["#c48e61","#c5956b","#c99768","#d0a276","#d2a576","#c99265"].map(color=>material(color));
  for(let row=0;row<19;row++){
    const z=-3.54+row*.393;
    let x=-4.96,n=0;
    while (x<1.46){
      const width=Math.min(n===0?[.74,1.29,1.82][row%3]:2.1,1.46-x);
      if(width>.035) box(width-.015,.04,.378,planks[(row*7+n*3)%planks.length],x+width/2,.055,z,.009);
      x+=width;n++;
    }
  }
  for(let row=0;row<10;row++) for(let col=0;col<7;col++){
    box(.724,.028,.735,(row+col)%4===0?stone:tile,1.852+col*.74,.052,-3.38+row*.75,.006);
  }
  for(let row=0;row<10;row++) for(let col=0;col<3;col++){
    box(.52,.025,.737,(row+col)%2===0?tile:stone,-6.35+col*.535,.052,-3.38+row*.75,.006);
  }

  box(13.38,2.70,.22,wall,0,1.37,-3.85,.05);
  box(13.35,.15,.076,ivory,0,.15,-3.705,.012);
  box(.22,2.7,2.3,wall,-6.61,1.37,-2.78,.035);
  box(1.43,2.36,.10,oak,-5.73,1.23,-3.685,.048);
  box(1.16,2.13,.06,wood,-5.73,1.23,-3.61,.045);
  box(.028,1.78,.023,oak,-6.11,1.23,-3.57,.006);
  const entrySignal=material("#694a3c",{emissive:"#f0bc82",emissiveIntensity:0});
  box(.10,.24,.06,entrySignal,-5.29,1.17,-3.53,.02);
  box(1.22,.035,.79,textile("#7e6654","#b5a089"),-5.73,.07,-2.19,.06);
  box(1.36,.46,.49,oak,-5.77,.38,1.93,.06);
  box(1.25,.12,.53,cream,-5.77,.66,1.93,.045);
  for(const x of [-6.26,-5.27]) box(.10,.22,.36,wood,x,.16,1.93,.02);
  const parcel=group(-5.68,.08,-1.65);
  box(.54,.42,.46,material("#bf8e5f"),0,.22,0,.035,parcel);
  box(.089,.427,.474,cream,0,.23,0,.006,parcel);
  box(.20,.012,.12,ivory,.12,.449,.055,.003,parcel);

  const windowGlass=material("#d6e5de",{emissive:"#d7e5e3",emissiveIntensity:.35});
  box(2.03,1.49,.05,wood,-3.85,1.68,-3.697,.035);
  box(1.84,1.31,.06,windowGlass,-3.85,1.68,-3.657,.03);
  box(.05,1.33,.06,ivory,-3.85,1.68,-3.61,.02);
  box(1.87,.06,.06,ivory,-3.85,1.72,-3.61,.01);
  box(2.24,.10,.25,ivory,-3.85,.95,-3.60,.025);
  for(let pleat=0;pleat<12;pleat++){
    const x=-4.95+(pleat%6)*.077+(pleat>5?1.81:0);
    box(.108,1.78,.11,pleat%2?ivory:cream,x,1.58,-3.51+(pleat%2)*.027,.037);
  }
  tube([[-5.02,2.52,-3.46],[-3.81,2.52,-3.46],[-2.60,2.52,-3.46]],.025,brass);

  box(3.83,.052,2.64,textile("#d5b59d","#805f4c"),-1.77,.10,.46,.11);
  const carpetLines=material("#ddc5ad");
  for (const z of [-.69,1.61]) box(3.52,.008,.023,carpetLines,-1.77,.13,z,.002);
  for(let i=0;i<40;i++) for(const z of [-.89,1.80]) box(.024,.012,.107,carpetLines,-3.55+i*.091,.119,z,.003);

  const fabric=textile("#dfc5a8","#8c7355");
  box(3.18,.36,.98,fabric,-1.86,.35,2.38,.14);
  box(3.17,.64,.25,fabric,-1.86,.65,2.78,.09);
  for(const x of [-3.30,-.42]){
    box(.28,.49,1.10,fabric,x,.56,2.38,.09);
    for(const z of [2.02,2.77]) box(.095,.22,.10,wood,x,.18,z,.022);
  }
  for(const x of [-2.56,-1.16]){
    box(1.32,.16,.69,fabric,x,.543,2.25,.09);
    const cushion=box(1.30,.48,.19,fabric,x,.798,2.57,.08);cushion.rotation.x=-.11;
  }
  const pillow=box(.44,.43,.22,linen,-2.98,.83,2.47,.09);pillow.rotation.z=-.19;
  const pillow2=box(.43,.40,.23,sage,-.79,.81,2.49,.09);pillow2.rotation.z=.23;
  const throwFold=box(.52,.052,.53,textile("#e9d2a8","#aa8669"),-.62,.835,2.50,.019);
  throwFold.rotation.z=-.08;
  const coffee=disk(.76,.09,oak,-1.69,.57,.54);coffee.scale.set(1.25,1,.71);
  for(const [x,z] of [[-2.06,.38],[-1.26,.37],[-1.69,.78]]) disk(.055,.45,wood,x,.31,z,scene,.068);
  box(.37,.047,.26,cream,-1.93,.64,.54,.01).rotation.y=.16;
  box(.31,.033,.22,sage,-1.94,.68,.54,.01).rotation.y=.10;
  disk(.115,.078,ivory,-1.36,.66,.45,scene,.075);
  disk(.082,.005,wood,-1.36,.702,.45);
  function plant(x,y,z,scale){
    const plantGroup=group(x,y,z);plantGroup.scale.setScalar(scale);
    disk(.24,.38,linen,0,.23,0,plantGroup,.18);disk(.215,.016,wood,0,.423,0,plantGroup);
    for(let i=0;i<8;i++){
      const angle=i*2.399, dx=Math.cos(angle)*(.22+i*.016), dz=Math.sin(angle)*(.22+i*.016), top=.68+(i%4)*.105;
      tube([[0,.43,0],[dx*.35,top-.11,dz*.35],[dx,top,dz]],.014,foliage[0],plantGroup);
      const leaf=sphere(.092,.036,.23,foliage[i%3],dx,top,dz,plantGroup);leaf.rotation.set(.35-i*.08,angle,.10);
    }
  }
  plant(1.00,.075,-1.96,1.35);plant(-4.45,.075,2.90,.79);

  box(2.27,.48,.60,oak,-.72,.35,-3.15,.055);
  for(let i=0;i<3;i++){
    const x=-1.44+i*.72;
    box(.68,.35,.026,wood,x,.36,-2.84,.025);
    for(let slat=0;slat<8;slat++) box(.024,.30,.021,oak,x-.26+slat*.072,.36,-2.818,.006);
  }
  for(const x of [-1.52,.13]) box(.16,.11,.40,wood,x,.12,-3.14,.03);
  const tvTexture=canvasTexture(1024,576);
  const tvMaterial=new THREE.MeshBasicMaterial({map:tvTexture.texture,color:"#ffffff",toneMapped:false});
  const display=group(0,0,0);
  box(2.25,1.28,.10,dark,-.70,1.52,-3.48,.057,display);
  plane(2.12,1.16,tvMaterial,-.70,1.52,-3.419,display);
  const tvReflect = new THREE.PointLight("#df83bd",0,4,2);
  const tvTint = tvReflect.color.clone();
  tvReflect.position.set(-.72,1.53,-3.17);scene.add(tvReflect);

  const pendant = group(-1.42,2.73,-.23);
  mesh(new THREE.LatheGeometry([
    new THREE.Vector2(.10,.16),new THREE.Vector2(.16,.16),new THREE.Vector2(.19,.09),
    new THREE.Vector2(.49,-.17),new THREE.Vector2(.49,-.22),new THREE.Vector2(.46,-.23),
    new THREE.Vector2(.16,.08),new THREE.Vector2(.10,.10)
  ],48),material("#f3d6af",{side:THREE.DoubleSide}),0,0,0,pendant);
  const lampSource=material("#ffe4b4",{emissive:"#ffe4b4",emissiveIntensity:0});
  disk(.43,.016,lampSource,0,-.22,0,pendant);
  disk(.053,.47,brass,0,.37,0,pendant);
  disk(.15,.061,brass,0,.61,0,pendant);
  const lamp=new THREE.PointLight("#ffcf99",0,9,2);
  lamp.position.set(-1.42,2.44,-.23);scene.add(lamp);

  const spillTexture=canvasTexture(256,256,(ctx,w,h)=>{
    const grad=ctx.createRadialGradient(w/2,h/2,1,w/2,h/2,w/2);
    grad.addColorStop(0,"rgba(255,255,255,.92)");grad.addColorStop(.44,"rgba(255,255,255,.42)");grad.addColorStop(1,"rgba(255,255,255,0)");
    ctx.fillStyle=grad;ctx.fillRect(0,0,w,h);
  });
  spillTexture.paint();
  function lightPatch(w,h,x,y,z,flat) {
    const surface=new THREE.MeshBasicMaterial({map:spillTexture.texture,transparent:true,depthWrite:false,opacity:0,polygonOffset:true,polygonOffsetFactor:-2,toneMapped:false});
    const patch=plane(w,h,surface,x,y,z);
    if(flat) patch.rotation.x=-Math.PI/2;
    return surface;
  }
  const floorSpill=lightPatch(6.0,5.8,-1.55,.145,-.17,true);
  const wallSpill=lightPatch(4.8,3.1,-1.28,1.45,-3.726,false);

  const cleanerModel=group(0,0,0);
  box(.53,.19,.30,dark,.82,.16,-2.82,.055,cleanerModel);
  const cleaner=group(.82,.064,-2.59);
  cleanerModel.add(cleaner);
  disk(.275,.098,dark,0,.062,0,cleaner);disk(.264,.064,ivory,0,.125,0,cleaner);
  disk(.082,.052,steel,-.07,.171,-.053,cleaner);disk(.058,.014,dark,-.07,.200,-.053,cleaner);
  const vacuumLed=material("#778875",{emissive:"#85bfb6",emissiveIntensity:.3});
  disk(.020,.007,vacuumLed,.088,.159,.03,cleaner);
  const dock = cleaner.position.clone();
  const trailMaterial = new THREE.MeshBasicMaterial({color:"#66715f",transparent:true,opacity:.62});
  const cleaningTrail = [];
  const route = [[.61,-2.27],[.42,-1.73],[.53,-.70],[.94,.38],[.71,1.21],[.44,1.88],[.61,2.80]];
  const routeCurve=new THREE.CatmullRomCurve3(route.map(([x,z])=>new THREE.Vector3(x,.078,z)));
  for(let i=0;i<=22;i++){
    const point=routeCurve.getPoint(i/22);
    const dot=disk(.020,.009,trailMaterial,point.x,point.y,point.z,cleanerModel);dot.castShadow=false;cleaningTrail.push(dot);
  }

  const cabinet=material("#aba68b");
  box(4.31,.87,.98,cabinet,3.72,.52,-3.10,.047);
  box(4.43,.105,1.09,ivory,3.72,1.015,-3.08,.047);
  box(4.45,.34,.036,stone,3.73,1.235,-3.712,.010);
  for(let i=0;i<14;i++) box(.012,.29,.016,tile,1.66+i*.314,1.245,-3.685,.003);
  for(const x of [1.96,2.52,3.09,4.51,5.04,5.56]){
    box(.51,.72,.048,cabinet,x,.54,-2.585,.033);
    box(.496,.676,.019,sage,x,.54,-2.556,.023);
    box(.397,.562,.019,cabinet,x,.54,-2.543,.018);
    box(.17,.022,.049,brass,x,.795,-2.505,.008);
  }

  const cooktop=group(0,0,0);
  box(1.18,.063,.65,glass,2.24,1.088,-3.03,.034,cooktop);
  function ring(radius,stroke,s,x,y,z,parent) {
    const object=mesh(new THREE.TorusGeometry(radius,stroke,8,42),s,x,y,z,parent);
    object.rotation.x=-Math.PI/2;return object;
  }
  const burner=material("#60576a");
  ring(.157,.009,burner,2.00,1.124,-3.00,cooktop);
  ring(.107,.008,burner,2.43,1.124,-3.13,cooktop);
  ring(.079,.008,burner,2.50,1.124,-2.88,cooktop);
  const lockMaterial=material("#9c5c54",{emissive:"#ef7852",emissiveIntensity:0});
  const lockIcon=box(.12,.012,.096,lockMaterial,2.25,1.128,-2.755,.010,cooktop);
  const lockShackle=ring(.039,.011,lockMaterial,2.25,1.13,-2.807,cooktop);

  const oven=group(0,0,0);
  box(1.05,.73,.14,dark,3.73,.59,-2.569,.052,oven);
  box(.93,.47,.053,glass,3.73,.49,-2.477,.036,oven);
  const ovenWindow=material("#392f42",{roughness:.29,emissive:"#f3bd69",emissiveIntensity:0});
  box(.82,.35,.015,ovenWindow,3.73,.49,-2.447,.048,oven);
  box(.76,.039,.064,steel,3.73,.711,-2.42,.012,oven);
  const ovenTexture=canvasTexture(600,150);
  const ovenScreen=new THREE.MeshBasicMaterial({map:ovenTexture.texture,toneMapped:false});
  plane(.65,.14,ovenScreen,3.73,.846,-2.488,oven);

  const kettle=group(0,0,0);
  box(.21,.27,.12,ivory,5.14,1.27,-3.53,.027,kettle);
  const plugLed=material("#778875",{emissive:"#78d6ae",emissiveIntensity:0});
  disk(.025,.012,plugLed,5.14,1.29,-3.452,kettle).rotation.x=Math.PI/2;
  tube([[5.14,1.17,-3.45],[5.23,1.08,-3.40],[5.38,1.11,-3.28]],.022,dark,kettle);
  disk(.203,.059,dark,5.43,1.10,-3.16,kettle);
  disk(.154,.39,material("#d1a37c"),5.43,1.32,-3.16,kettle,.176);
  disk(.154,.035,brass,5.43,1.522,-3.16,kettle);disk(.046,.05,wood,5.43,1.558,-3.16,kettle);
  tube([[5.55,1.44,-3.16],[5.67,1.43,-3.16],[5.67,1.22,-3.16],[5.55,1.22,-3.16]],.033,dark,kettle);
  tube([[5.30,1.31,-3.13],[5.22,1.39,-3.12],[5.20,1.47,-3.11]],.041,brass,kettle);

  const fridge=group(0,0,0);
  box(.95,2.20,1.04,steel,6.12,1.17,-3.23,.08,fridge);
  box(.91,1.57,.075,ivory,6.12,1.48,-2.665,.046,fridge);
  box(.91,.55,.075,ivory,6.12,.382,-2.665,.046,fridge);
  box(.034,.44,.069,steel,5.79,1.39,-2.603,.014,fridge);
  box(.38,.034,.070,steel,6.09,.56,-2.603,.013,fridge);
  const fridgeTexture=canvasTexture(360,420);
  const fridgeScreen=new THREE.MeshBasicMaterial({map:fridgeTexture.texture,toneMapped:false});
  box(.37,.47,.034,dark,6.18,1.64,-2.616,.025,fridge);
  // The notice stays legible while the appliance rests.
  plane(.329,.426,fridgeScreen,6.18,1.64,-2.595);

  const tableTop=disk(.82,.094,oak,4.15,.86,1.50);tableTop.scale.x=1.23;
  disk(.18,.74,wood,4.15,.44,1.50,scene,.25);disk(.36,.08,wood,4.15,.13,1.50);
  disk(.22,.065,ivory,4.15,.938,1.53,scene,.14);
  for(const [x,z,rotation] of [[4.03,2.69,0],[2.87,1.27,Math.PI/2],[5.43,1.55,-Math.PI/2]]){
    const chair=group(x,.08,z);chair.rotation.y=rotation;
    box(.61,.09,.58,oak,0,.49,0,.047,chair);
    box(.61,.37,.095,sage,0,.86,.255,.037,chair);
    for(const a of [-.23,.23])for(const b of [-.21,.21])disk(.038,b > 0 ? .76 : .45,wood,a,b > 0 ? .38 : .23,b,chair,.031);
  }

  const anchors = {
    cleaner_01: [.82, .52, -2.50], light_01: [-1.42, 2.51, -.23], display_01: [-.70, 2.17, -3.41],
    cooktop_01: [2.28, 1.43, -2.79], oven_01: [3.74, 1.00, -2.40],
    fridge_01: [6.13, 2.14, -2.55], plug_kettle: [5.25, 1.72, -3.00],
  };
  const projected = new THREE.Vector3();
  const cleanPosition = new THREE.Vector3();
  const goalCamera = new THREE.Vector3();
  const goalTarget = new THREE.Vector3();
  const currentCamera = new THREE.Vector3();
  const currentTarget = new THREE.Vector3();
  const targetLamp = new THREE.Color("#ffd29a");
  const currentLamp = targetLamp.clone();
  const models = {
    cleaner_01: cleanerModel, light_01: pendant, display_01: display, cooktop_01: cooktop,
    oven_01: oven, fridge_01: fridge, plug_kettle: kettle,
  };
  const normalMaterials = new Map();
  const restingMaterials = new Map();
  const readings = new Map();
  const labels = new Map();
  let presentation = new Map();
  let spill = 0, targetSpill = 0, targetIntensity = 0;
  let jobRunning = false, cleanSince = 0, tvScene;
  let entrance = "";
  let zoom = 1, targetZoom = 1, hasDirection = false;
  let viewport = 1, viewWidth = 0, viewHeight = 0, request = 0, readyAt = 0;

  parcel.visible = false;
  lockIcon.visible = lockShackle.visible = false;
  cleaningTrail.forEach((dot) => { dot.visible = false; });
  const castle = new Image();
  castle.onload = () => {
    if (tvScene === "kids_party") {
      paintTv();
      queue();
    }
  };
  castle.src = "/demo/assets/castle.jpg";

  const tvColors = {
    kids_party: ["#dec2de", "#795184"], party: ["#e7a4ad", "#ad496e"],
    calm: ["#c6e0c7", "#587c78"], cinema: ["#b0add6", "#444076"],
  };

  function paintTv() {
    tvTexture.paint((ctx, w, h) => {
      const gradient = ctx.createLinearGradient(0, 0, w, h);
      const [start, end] = tvColors[tvScene] || ["#292633", "#191822"];
      gradient.addColorStop(0, start);
      gradient.addColorStop(1, end);
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, w, h);
      if (tvScene === "kids_party" && castle.naturalWidth) {
        const scale = Math.max(w / castle.naturalWidth, h / castle.naturalHeight);
        const width = castle.naturalWidth * scale, height = castle.naturalHeight * scale;
        ctx.drawImage(castle, (w - width) / 2, (h - height) / 2, width, height);
      } else if (tvScene) {
        ctx.fillStyle = "#fff9ed";
        ctx.font = '600 80px "IBM Plex Sans KR", sans-serif';
        ctx.textAlign = "center";
        ctx.fillText(TV_SCENES[tvScene] || tvScene, w / 2, h / 2, w - 80);
      }
    });
  }

  function paintOven({ preset, in_use, job_status }) {
    ovenWindow.emissiveIntensity = in_use ? .65 : 0;
    ovenTexture.paint((ctx, w, h) => {
      ctx.fillStyle = "#282632";
      ctx.fillRect(0, 0, w, h);
      if (!preset) return;
      ctx.fillStyle = "#ffdfaa";
      ctx.font = "600 75px monospace";
      ctx.textAlign = "center";
      ctx.fillText(`${preset.temp_c}°  ${preset.minutes}m`, w / 2, 101);
    });
    const status = in_use ? "사용 중" : job_status === "completed" ? "사용 완료" : "";
    const settings = preset && `${preset.temp_c}℃ · ${preset.minutes}분`;
    if (status) return [status, settings].filter(Boolean).join(" · ");
    return settings ? `${settings} 대기` : "대기 설정 없음";
  }

  function paintFridge(notice) {
    fridgeTexture.paint((ctx, w, h) => {
      ctx.fillStyle = notice ? "#edf0dc" : "#2b2c2b";
      ctx.fillRect(0, 0, w, h);
      if (!notice) return;
      ctx.fillStyle = "#385447";
      ctx.font = '600 34px "IBM Plex Sans KR", sans-serif';
      ctx.fillText("냉장고 안내", 22, 58);
      ctx.fillRect(22, 79, w - 44, 3);
      ctx.font = '500 25px "IBM Plex Sans KR", sans-serif';
      let line = "", y = 122;
      for (const char of notice) {
        if (ctx.measureText(line + char).width > w - 44) {
          ctx.fillText(line, 22, y);
          line = "";
          y += 37;
        }
        line += char;
      }
      ctx.fillText(line, 22, y);
    });
  }

  function paintLight({ power, color }) {
    const hsv = power && hsvColor(color || {});
    const warmHue = Math.min(44, 27 + ((color?.kelvin ?? 3000) - 2700) / 38);
    const tint = hsv || `hsl(${warmHue}, 90%, 76%)`;
    targetLamp.set(tint);
    targetIntensity = power ? (hsv ? 87 * color.brightness / 70 : 26) : 0;
    targetSpill = hsv ? color.brightness / 100 : 0;
    view.classList.toggle("has-color", targetSpill > 0);
    view.style.setProperty("--glow-tint", tint);
    if (power === false) return "꺼짐";
    if (hsv) return `색조 ${color.hue}° · 밝기 ${color.brightness}`;
    return color?.kelvin ? `${color.kelvin} K` : "켜짐";
  }

  const painters = {
    light_01: paintLight,
    display_01({ play_mood }) {
      tvScene = play_mood?.scene ?? null;
      paintTv();
      return TV_SCENES[tvScene] || tvScene || "꺼짐";
    },
    oven_01: paintOven,
    fridge_01({ show_notice }) {
      paintFridge(show_notice);
      return show_notice ? "보관·준비 안내" : "안내 없음";
    },
    cooktop_01({ child_lock, in_use }) {
      lockIcon.visible = lockShackle.visible = child_lock === true;
      lockMaterial.emissiveIntensity = child_lock ? .82 : 0;
      return child_lock ? "잠금" : in_use ? "사용 중" : "잠금 해제";
    },
    plug_kettle({ power }) {
      plugLed.color.set(power ? "#778875" : "#8a6c5b");
      plugLed.emissive.set(power ? "#78d6ae" : "#b9946e");
      plugLed.emissiveIntensity = power ? 1.4 : 0;
      return power ? "전원 켜짐" : "전원 차단";
    },
    cleaner_01({ job_status, in_use, clean }) {
      const running = job_status === "running" || in_use === true;
      if (running && !jobRunning) cleanSince = performance.now();
      jobRunning = running;
      vacuumLed.emissiveIntensity = running ? 1.7 : .3;
      if (!running) {
        cleaner.position.copy(dock);
        cleaningTrail.forEach((dot) => { dot.visible = false; });
      }
      return running ? `${clean?.room || ""} 청소 중`.trim() : job_status === "completed" ? "청소 완료" : "충전 위치";
    },
  };
  paintTv();
  paintOven({});
  paintFridge(null);

  function restingMaterial(normal) {
    if (!restingMaterials.has(normal)) {
      const muted = normal.clone();
      muted.onBeforeCompile = (shader) => {
        // Apply after lighting so textures and emissive surfaces also rest.
        shader.fragmentShader = shader.fragmentShader.replace("#include <opaque_fragment>", `
          float luma = dot(outgoingLight, vec3(0.2126, 0.7152, 0.0722));
          outgoingLight = mix(vec3(luma), outgoingLight, 0.12) * 0.46;
          #include <opaque_fragment>
        `);
      };
      restingMaterials.set(normal, muted);
    }
    return restingMaterials.get(normal);
  }

  function setChain(chain) {
    const next = houseDevicePresentation(chain);
    let changed = false;
    for (const [id, model] of Object.entries(models)) {
      const { resting = false, evidence = "" } = next.get(id) ?? {};
      const previous = presentation.get(id);
      if (resting !== (previous?.resting ?? false)) {
        model.traverse((object) => {
          if (!object.isMesh) return;
          if (!normalMaterials.has(object)) normalMaterials.set(object, object.material);
          const normal = normalMaterials.get(object);
          object.material = resting ? restingMaterial(normal) : normal;
        });
        changed = true;
      }
      if (resting !== (previous?.resting ?? false) || evidence !== (previous?.evidence ?? "")) {
        renderLabel(id, resting, evidence);
        changed = true;
      }
    }
    presentation = next;
    view.classList.toggle("resting-light", presentation.get("light_01")?.resting === true);
    if (changed) queue();
  }

  function renderLabel(id, resting, evidence) {
    const reading = readings.get(id);
    let label = labels.get(id);
    const visible = reading && (id === "fridge_01" ? reading.notice : !resting && reading.show);
    if (!visible) {
      if (label) label.hidden = true;
      return;
    }
    if (!label) {
      label = document.createElement("span");
      label.className = "marker";
      const value = document.createElement("span");
      value.className = "marker-value";
      const trace = document.createElement("span");
      trace.className = "marker-trace";
      label.append(value, trace);
      overlay.append(label);
      labels.set(id, label);
    }
    label.hidden = false;
    label.firstElementChild.textContent = reading.text;
    label.lastElementChild.textContent = evidence;
    label.lastElementChild.hidden = !evidence;
    label.classList.toggle("theme", reading.theme);
  }

  function update(snapshot) {
    let changed = false;
    const byId = new Map(snapshot.devices.map((device) => [device.logical_id, device]));
    for (const [id, paint] of Object.entries(painters)) {
      const device = byId.get(id);
      const values = device?.values ?? {};
      const observed = Object.keys(values).length > 0;
      const quality = !device?.values || device.available === false ? "연결 끊김"
        : !observed ? "확인할 수 없음" : device.observation === "stale" ? "이전 관측" : "";
      const key = JSON.stringify([values, quality]);
      const previous = readings.get(id);
      if (previous?.key === key) continue;
      changed = true;

      const detail = paint(values);
      const active = {
        light_01: Boolean(values.color?.hue != null && values.power) || values.power === false,
        display_01: Boolean(values.play_mood), oven_01: Boolean(values.preset || values.in_use),
        cooktop_01: Boolean(values.child_lock || values.in_use), plug_kettle: values.power === false,
        cleaner_01: jobRunning || values.job_status === "completed",
      }[id];
      readings.set(id, {
        key, show: Boolean(quality || active || previous),
        notice: Boolean(values.show_notice),
        text: [HOUSE_DEVICES[id].label, observed && detail, quality].filter(Boolean).join(" · "),
        theme: Boolean(id === "light_01" && targetSpill || id === "display_01" && tvScene === "kids_party"),
      });
      const { resting = false, evidence = "" } = presentation.get(id) ?? {};
      renderLabel(id, resting, evidence);
    }
    if (changed) {
      renderer.shadowMap.needsUpdate = true;
      queue();
    }
  }

  function project(id) {
    if (id === "cleaner_01" && jobRunning) projected.set(cleaner.position.x, .50, cleaner.position.z);
    else projected.fromArray(anchors[id]);
    projected.project(camera);
    return { x: (projected.x + 1) / 2, y: (1 - projected.y) / 2 };
  }

  function placeLabels() {
    // Measure in stage pixels, before the outer frame scales to the screen.
    const markers = Array.from(labels).flatMap(([id, label]) => {
      if (label.hidden) return [];
      const { x, y } = project(id);
      return [{ label, x: x * viewWidth, y: y * viewHeight, width: label.offsetWidth, height: label.offsetHeight }];
    });
    for (const { label, x, y, left, top, height } of layoutHouseLabels(markers, viewWidth, viewHeight)) {
      label.style.left = `${left}px`;
      label.style.top = `${top}px`;
      label.style.setProperty("--leader-x", `${x - left}px`);
      label.style.setProperty("--leader-top", `${Math.min(y - top, height)}px`);
      label.style.setProperty("--leader-height", `${Math.max(top - y, y - top - height, 0)}px`);
    }
  }

  function projection() {
    const extent = Math.max(5.35, 7.56 / viewport) / zoom;
    Object.assign(camera, { left: -extent * viewport, right: extent * viewport,
      top: extent, bottom: -extent, near: .1, far: 100 });
    camera.updateProjectionMatrix();
  }

  function syncViewport() {
    const width = stage.clientWidth, height = stage.clientHeight;
    if (!width || !height) return false;
    const scale = stage.getBoundingClientRect().width / width;
    const ratio = Math.min(devicePixelRatio * scale, 1.5);
    if (width === viewWidth && height === viewHeight && ratio === renderer.getPixelRatio()) return false;
    viewWidth = width;
    viewHeight = height;
    renderer.setPixelRatio(ratio);
    renderer.setSize(width, height, false);
    viewport = width / height;
    projection();
    return true;
  }

  function resize() {
    syncViewport();
    queue();
  }

  function focus(setting, { instant = false } = {}) {
    goalCamera.fromArray(setting.eye);
    goalTarget.fromArray(setting.aim);
    targetZoom = setting.zoom;
    if (!hasDirection || instant || motion.matches) {
      currentCamera.copy(goalCamera);
      currentTarget.copy(goalTarget);
      zoom = targetZoom;
      orient();
    }
    hasDirection = true;
    queue();
  }

  function setMoment(entry) {
    if (entry === entrance) return;
    entrance = entry;
    parcel.visible = entry === "package";
    entrySignal.emissiveIntensity = entry ? .9 : 0;
    renderer.shadowMap.needsUpdate = true;
    queue();
  }

  function queue() {
    readyAt = performance.now() + 1350;
    if (!request) request = requestAnimationFrame(frame);
  }

  function orient() {
    projection();
    camera.position.copy(currentCamera);
    camera.lookAt(currentTarget);
    camera.updateMatrixWorld();
  }

  function frame(now) {
    request = 0;
    if (!hasDirection || !stage.clientWidth) return;
    syncViewport();
    const amount = motion.matches || now > readyAt ? 1 : .093;
    currentCamera.lerp(goalCamera, amount);
    currentTarget.lerp(goalTarget, amount);
    zoom = THREE.MathUtils.lerp(zoom, targetZoom, amount);
    orient();
    const idleLamp = presentation.get("light_01")?.resting;
    const idleTv = presentation.get("display_01")?.resting;
    tvReflect.color.copy(idleTv ? restingGlow : tvTint);
    tvReflect.intensity = tvScene === "kids_party" ? (idleTv ? 3 : 12) : 0;
    currentLamp.lerp(targetLamp, amount);
    lamp.color.copy(currentLamp);
    if (idleLamp) lamp.color.lerp(restingGlow, .85);
    lamp.intensity = THREE.MathUtils.lerp(lamp.intensity, targetIntensity * (idleLamp ? .28 : 1), amount);
    lampSource.color.copy(currentLamp).lerp(reflectedWhite, .45);
    lampSource.emissive.copy(currentLamp);
    lampSource.emissiveIntensity = lamp.intensity / 26;
    spill = THREE.MathUtils.lerp(spill, targetSpill * (idleLamp ? .25 : 1), amount);
    floorGlow.copy(lamp.color).lerp(reflectedWhite, .18);
    floorSpill.color.copy(floorGlow);
    floorSpill.opacity = spill * .46;
    wallSpill.color.copy(floorGlow);
    wallSpill.opacity = spill * .33;
    if (jobRunning) {
      const progress = motion.matches ? .30 : ((now - cleanSince) % 6800) / 3400;
      const distance = 1 - Math.abs(1 - progress);
      routeCurve.getPoint(distance, cleanPosition);
      cleaner.position.set(cleanPosition.x, .064, cleanPosition.z);
      cleaningTrail.forEach((dot, index) => { dot.visible = index / 22 <= distance; });
      renderer.shadowMap.needsUpdate = true;
    }
    for (const [normal, muted] of restingMaterials) {
      muted.color.copy(normal.color);
      if (normal.emissive) {
        muted.emissive.copy(normal.emissive);
        muted.emissiveIntensity = normal.emissiveIntensity;
      }
    }
    renderer.render(scene, camera);
    placeLabels();
    if (!motion.matches && (now < readyAt || jobRunning)) request = requestAnimationFrame(frame);
  }

  new ResizeObserver(resize).observe(stage);
  return { resize, update, setChain, focus, setMoment, anchor: project };
}
